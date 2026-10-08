import { humanizeUiError } from "../../utils/uiLabels";
import { answerCopyText } from "../answer-ui/answerUiProtocol";
import { useCallback, useRef, useState, type Dispatch, type SetStateAction } from "react";
import {
  archiveSession,
  cancelChatResearchRuns,
  cancelChatTurn,
  createNewSession,
  getChatTurnStatus,
  loadSessionDetail,
  sendChatStream,
  steerResearchRun,
} from "../../api";
import { operationRegistry } from "../../app/operationRegistry";
import { useWorkspace } from "../../app/WorkspaceProvider";
import type { StreamRecoveryState } from "../../app/workspaceReducer";
import type {
  ChatMessage,
  ChatResearchProgress,
  ChatResponse,
  ChatSettings,
  RagSettings,
  SessionDetailResponse,
} from "../../types";
import {
  buildContinuationHistory,
  buildRetryHistory,
  sanitizeSingleChatMessages,
  seedMessages,
  tailInterruptedTurn,
  toChatHistoryPayload,
} from "../single-chat/chatHistory";
import { evidenceFromResponse, evidenceFromSessionTurns, pedagogySummaryFromSnapshot } from "../evidence/evidenceHelpers";
import { phaseTrail } from "../pedagogy/pedagogyLabels";
import { turnStatusCopy } from "./turnStatusCopy";

const WEB_CONSENT_MARKER = "__STUDY_AGENT_WEB_CONSENT__";

type ControllerOptions = {
  chatSettings: ChatSettings;
  chatSettingsDefaults: ChatSettings;
  setChatSettings: Dispatch<SetStateAction<ChatSettings>>;
  ragSettings: RagSettings;
  ragSettingsDefaults: RagSettings;
  setRagSettings: Dispatch<SetStateAction<RagSettings>>;
  ragEnabled: boolean;
  setRagEnabled: Dispatch<SetStateAction<boolean>>;
  keepCurrentRole: boolean;
  setKeepCurrentRole: Dispatch<SetStateAction<boolean>>;
  conversationInstruction: string;
  setConversationInstruction: Dispatch<SetStateAction<string>>;
  webLookupSource: string;
  webLookupRunId?: string;
  useWebLookup: boolean;
  webPolicy?: string;
  // G16: memory ask inputs resolved from runtime settings + memory status.
  // Consent state is checked per-send against the backend session detail.
  memoryPolicy?: string;
  memoryAvailable?: boolean;
  setUseWebLookup: Dispatch<SetStateAction<boolean>>;
  setInput: Dispatch<SetStateAction<string>>;
  setOperationError: Dispatch<SetStateAction<string>>;
  clearChatArtifacts: () => void;
  refresh: () => Promise<void>;
  onResearchRunDiscovered: (runId: string, refresh?: boolean) => void;
};

type SendOptions = {
  continuationOfTurnId?: string;
  retryOfTurnId?: string;
  partialReply?: string;
  turnId?: string;
};

export function createEmptyRag(): ChatResponse["rag"] {
  return {
    status: "waiting",
    query: "",
    retrieval_mode: "",
    reason: "",
    context: "",
    sources: "",
    result_count: 0,
    results: [],
    debug: {},
    attempts: [],
    rewritten_query: "",
  };
}

export function useChatController(options: ControllerOptions) {
  const { state, dispatch } = useWorkspace();
  const [isSending, setIsSending] = useState(false);
  const [researchProgress, setResearchProgress] = useState<ChatResearchProgress | null>(null);
  const activeTurnIdRef = useRef<string | null>(null);
  const activeOperationIdRef = useRef<string>("");
  // G18: the run id of an in-flight deep-research journey; while set, main
  // input messages become mid-run steering (decision 12).
  const deepRunIdRef = useRef<string | null>(null);
  // G12 decision 13: the server is the only writer of partial replies. The
  // controller only reflects durable turn states; commitTurn is gone.
  const cancelledSettledRef = useRef(false);
  const cancelPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const cancelMarkRef = useRef<
    ((status: string, partial?: string) => void) | null
  >(null);

  const cancelActiveResearch = useCallback((turnId: string) => {
    void cancelChatResearchRuns(turnId)
      .then((runs) => {
        const runId = runs[0]?.id;
        if (runId) {
          setResearchProgress(null);
          options.onResearchRunDiscovered(runId, true);
        }
      })
      .catch(() => undefined);
  }, [options.onResearchRunDiscovered]);

  const stopCancelPolling = useCallback(() => {
    if (cancelPollRef.current !== null) {
      clearInterval(cancelPollRef.current);
      cancelPollRef.current = null;
    }
  }, []);

  // G12 decision 20: the client learns the durable terminal state by polling
  // the turn-status endpoint; the Cancel POST only confirms registration.
  const startCancelPolling = useCallback(
    (turnId: string) => {
      stopCancelPolling();
      let ticks = 0;
      cancelPollRef.current = setInterval(() => {
        ticks += 1;
        void getChatTurnStatus(turnId)
          .then((status) => {
            const terminal = [
              "cancelled",
              "interrupted",
              "completed",
              "failed",
              "abandoned",
              "superseded",
            ];
            if (status.cancel_requested_at && !terminal.includes(status.status)) {
              if (ticks === 8) {
                cancelMarkRef.current?.("cancelling-slow");
              }
              return;
            }
            cancelledSettledRef.current = true;
            stopCancelPolling();
            if (status.status === "interrupted") {
              cancelMarkRef.current?.("interrupted", status.assistant_message || undefined);
            } else {
              cancelMarkRef.current?.(status.status);
            }
          })
          .catch(() => undefined);
      }, 500);
    },
    [stopCancelPolling]
  );

  const setMessages: Dispatch<SetStateAction<ChatMessage[]>> = useCallback(
    (value) => dispatch({ type: "SET_CHAT_MESSAGES", value }),
    [dispatch]
  );
  const setLastChat: Dispatch<SetStateAction<ChatResponse | null>> = useCallback(
    (value) => dispatch({ type: "SET_LAST_CHAT", value }),
    [dispatch]
  );
  const setStreamRecovery = useCallback(
    (value: StreamRecoveryState | null) => dispatch({ type: "SET_STREAM_RECOVERY", value }),
    [dispatch]
  );
  const setThreadId = useCallback(
    (threadId?: string) => dispatch({ type: "SET_ACTIVE_CHAT_THREAD", threadId }),
    [dispatch]
  );
  const transitionSession = useCallback(
    (
      threadId: string,
      messages: ChatMessage[],
      lastChat: ChatResponse | null,
      streamRecovery: StreamRecoveryState | null = null
    ) =>
      dispatch({
        type: "TRANSITION_CHAT_SESSION",
        threadId,
        messages,
        lastChat,
        streamRecovery,
      }),
    [dispatch]
  );

  const cancelWorkspaceRuns = useCallback(() => {
    const activeTurnId = activeTurnIdRef.current;
    if (activeTurnId) {
      cancelActiveResearch(activeTurnId);
    }
    operationRegistry.invalidate("chat");
    setIsSending(false);
  }, [cancelActiveResearch]);

  const send = async (
    question: string,
    historyBase = state.chatMessages,
    extraOpts: SendOptions = {}
  ) => {
    if (!question || isSending) return;

    // G18 decision 12: while a deep-research run is streaming, a message from
    // the main input becomes mid-run steering instead of a new chat turn.
    if (deepRunIdRef.current) {
      const runId = deepRunIdRef.current;
      try {
        await steerResearchRun(runId, question);
        setMessages((current) => [
          ...current,
          {
            role: "user" as const,
            content: question,
            avatarRole: "user" as const,
            transient: true,
            turnStatus: "cancelling-registered",
          },
        ]);
        options.setInput("");
        options.setOperationError("");
      } catch (error) {
        options.setOperationError(
          `研究方向注入失败：${error instanceof Error ? error.message : "未知错误"}`
        );
      }
      return;
    }

    const operationOwner = state.activeChatThreadId;
    const { operationId, controller: abortController, generationId } = operationRegistry.start(
      "chat",
      operationOwner
    );
    const isCurrent = () =>
      operationRegistry.isCurrent(operationId, generationId, operationOwner);
    const isOwned = () =>
      operationRegistry.isOwned(operationId, generationId, operationOwner);
    const isContinuation = Boolean(extraOpts.continuationOfTurnId);
    const nextMessages: ChatMessage[] = isContinuation
      ? [...historyBase]
      : [...historyBase, { role: "user", content: question, avatarRole: "user" }];
    const userIndex = isContinuation ? -1 : nextMessages.length - 1;
    const assistantIndex = isContinuation ? nextMessages.length - 1 : nextMessages.length;

    setMessages(
      isContinuation
        ? nextMessages
        : [...nextMessages, { role: "assistant", content: "", avatarRole: "auto" }]
    );
    options.setInput("");
    setStreamRecovery(null);
    setResearchProgress(null);
    options.setOperationError("");
    setIsSending(true);
    let streamedReply = "";
    let fullReply = "";
    let streamedRoute: Record<string, unknown> = {};
    let streamedRag: ChatResponse["rag"] | null = null;
    let activeSessionId = state.activeChatThreadId ?? "";
    let activeTurnId =
      extraOpts.turnId ?? `turn_${globalThis.crypto.randomUUID()}`;
    activeTurnIdRef.current = activeTurnId;
    // G12 decision 20: the official client pre-allocates the operation handle
    // so cancellation can target (turn_id, expected_operation_id) even before
    // the server assigns its own operation id.
    const clientOperationId = extraOpts.turnId ? undefined : `op_${globalThis.crypto.randomUUID()}`;
    let activeOperationId = clientOperationId ?? "";
    activeOperationIdRef.current = activeOperationId;
    cancelledSettledRef.current = false;
    cancelMarkRef.current = (status: string, partial?: string) => {
      const notice = turnStatusCopy(status) ?? status;
      setMessages((current) =>
        current.map((message, index) => {
          if (index === userIndex) {
            return {
              ...message,
              transient: true,
              turnId: activeTurnId || message.turnId,
              turnStatus: status,
              cancelNotice: notice,
            };
          }
          if (index === assistantIndex) {
            return {
              ...message,
              content: partial !== undefined && partial !== "" ? partial : message.content,
              transient: true,
              turnId: activeTurnId || message.turnId,
              turnStatus: partial ? "interrupted" : status,
              cancelNotice: notice,
            };
          }
          return message;
        })
      );
    };
    const shouldConsumeWebLookup = options.useWebLookup && Boolean(options.webLookupSource);
    let turnWebContext = shouldConsumeWebLookup ? options.webLookupSource : "";
    if (
      !turnWebContext &&
      options.webPolicy === "ask" &&
      window.confirm("允许本轮联网搜索吗？搜索词会发送给外部搜索服务。")
    ) {
      turnWebContext = WEB_CONSENT_MARKER;
    }
    // G16 decisions 4-5, 9, 12: ask for cross-session memory only when the
    // policy demands it and memory is non-empty. The grant state is checked
    // against the backend session detail (authoritative), so restored
    // sessions never re-prompt after a prior consent.
    let memoryConsent = false;
    if (options.memoryPolicy === "ask" && options.memoryAvailable) {
      let granted = false;
      const sessionIdForConsent = state.activeChatThreadId;
      if (sessionIdForConsent) {
        try {
          const detail = await loadSessionDetail(sessionIdForConsent);
          granted = Boolean(detail.settings?.memory_consent_granted);
        } catch {
          granted = false;
        }
      }
      if (!granted && !extraOpts.continuationOfTurnId && !extraOpts.retryOfTurnId) {
        memoryConsent = window.confirm(
          "允许本会话使用你的跨会话记忆吗（如学习者画像、历史摘要）？同意后本会话内不再询问。"
        );
      }
    }

    try {
      const response = await sendChatStream(
        question,
        toChatHistoryPayload(historyBase),
        {
          ragEnabled: options.ragEnabled,
          sessionId: state.activeChatThreadId,
          chatSettings: options.chatSettings,
          ragSettings: options.ragSettings,
          keepCurrentRole: options.keepCurrentRole,
          previousMode:
            typeof state.lastChat?.route?.mode === "string"
              ? String(state.lastChat.route.mode)
              : undefined,
          conversationInstruction: options.conversationInstruction,
          webContext: turnWebContext,
          webContextRunId: shouldConsumeWebLookup ? options.webLookupRunId : undefined,
          memoryConsent,
          continuationOfTurnId: extraOpts.continuationOfTurnId,
          retryOfTurnId: extraOpts.retryOfTurnId,
          partialReply: extraOpts.partialReply ?? "",
          turnId: activeTurnId,
          operationId: clientOperationId
        },
        {
          onSession: (sessionId, meta) => {
            if (!isCurrent()) return;
            activeSessionId = sessionId;
            activeTurnId = meta?.turnId ?? activeTurnId;
            activeTurnIdRef.current = activeTurnId;
            activeOperationId = meta?.operationId ?? activeOperationId;
            setThreadId(sessionId);
            if (activeTurnId) {
              setMessages((current) =>
                current.map((message, index) =>
                  index === userIndex || index === assistantIndex
                    ? { ...message, turnId: activeTurnId, turnStatus: "streaming" }
                    : message
                )
              );
            }
          },
          onRoute: (route) => {
            if (!isCurrent()) return;
            streamedRoute = route;
            setLastChat((current) => ({
              reply: current?.reply ?? streamedReply,
              session_id: current?.session_id ?? state.activeChatThreadId ?? "streaming",
              route,
              rag: current?.rag ?? createEmptyRag(),
            }));
            setMessages((current) =>
              current.map((message, index) =>
                index === assistantIndex
                  ? { ...message, avatarRole: String(route.role ?? "auto") }
                  : message
              )
            );
          },
          onRag: (rag) => {
            if (!isCurrent()) return;
            streamedRag = rag;
            const researchRunId = rag.web_tools?.run_id;
            if (researchRunId) options.onResearchRunDiscovered(researchRunId);
            setLastChat((current) => ({
              reply: current?.reply ?? streamedReply,
              session_id: current?.session_id ?? state.activeChatThreadId ?? "streaming",
              route: current?.route ?? {},
              rag,
            }));
          },
          onResearch: (progress) => {
            if (!isCurrent()) return;
            setResearchProgress(progress);
            // G18: a deep run (round field present) opens the steering
            // channel while it runs; terminal states close it.
            if (progress.round != null) {
              deepRunIdRef.current =
                ["completed", "partial", "failed", "cancelled"].includes(
                  progress.status
                ) || progress.status === "pending"
                  ? null
                  : progress.run_id;
              if (deepRunIdRef.current === null) stopCancelPolling();
            }
            options.onResearchRunDiscovered(
              progress.run_id,
              ["completed", "partial", "failed", "cancelled"].includes(progress.status),
            );
          },
          onCancelled: (data) => {
            if (!isCurrent()) return;
            const partial = typeof data.partial === "string" ? data.partial : "";
            cancelledSettledRef.current = true;
            stopCancelPolling();
            const fullPartial =
              extraOpts.partialReply && !extraOpts.partialReply.includes(streamedReply)
                ? extraOpts.partialReply + streamedReply
                : streamedReply || partial;
            // The recovery card stays available after a cooperative stop:
            // retry creates a fresh operation with full retrieval (decision 8).
            setStreamRecovery({
              question,
              reply: fullPartial,
              reason: "已停止生成",
              sessionId: activeSessionId || undefined,
              turnId: activeTurnId || null,
            });
            cancelMarkRef.current?.(partial ? "interrupted" : "cancelled", partial || undefined);
          },
          onToken: (token) => {
            if (!isCurrent()) return;
            streamedReply += token;
            setMessages((current) =>
              current.map((message, index) =>
                index === assistantIndex
                  ? { ...message, content: `${message.content}${token}` }
                  : message
              )
            );
            setLastChat((current) => (current ? { ...current, reply: streamedReply } : current));
          },
          onDone: (done) => {
            if (!isCurrent()) return;
            if (typeof done.session_id === "string") {
              activeSessionId = done.session_id;
              setThreadId(done.session_id);
            }
            if (typeof done.turn_id === "string") activeTurnId = done.turn_id;
            if (typeof done.reply === "string") {
              fullReply = done.reply;
              const donePedagogy = (done as { pedagogy?: ChatResponse["pedagogy"] }).pedagogy;
              setMessages((current) =>
                current.map((message, index) =>
                  index === assistantIndex
                    ? {
                        ...message,
                        content: done.reply as string,
                        turnStatus: "completed",
                        evidence: donePedagogy
                          ? { pedagogy: donePedagogy, route: streamedRoute, rag: streamedRag ?? undefined }
                          : message.evidence,
                      }
                    : index === userIndex
                      ? { ...message, turnStatus: "completed" }
                      : message
                )
              );
              if (donePedagogy?.phase) {
                dispatch({
                  type: "SET_PEDAGOGY_PHASES",
                  value: phaseTrail([...state.pedagogyPhases, donePedagogy.phase]),
                });
              }
            }
          },
        },
        { signal: abortController.signal }
      );
      if (!isCurrent()) return;
      activeSessionId = response.session_id;
      activeTurnId = response.turn_id ?? activeTurnId;
      setThreadId(response.session_id);
      const effectiveReply = fullReply || response.reply;
      setLastChat(fullReply ? { ...response, reply: effectiveReply } : response);
      options.setOperationError("");
      if (shouldConsumeWebLookup) options.setUseWebLookup(false);
      setMessages((current) =>
        current.map((message, index) =>
          index === assistantIndex
            ? {
                ...message,
                content: effectiveReply,
                avatarRole: String(response.route.role ?? "auto"),
                evidence: evidenceFromResponse(response),
              }
            : message
        )
      );
      await options.refresh();
    } catch (error) {
      if (!isOwned()) return;
      const isAbort = error instanceof DOMException && error.name === "AbortError";
      const message = isAbort
        ? "已停止生成"
        : error instanceof Error
          ? humanizeUiError(error, "本次回答未能完成，请稍后重试。")
          : "聊天请求失败";
      const fullPartial = extraOpts.partialReply
        ? extraOpts.partialReply + streamedReply
        : streamedReply;
      const preserved = fullPartial
        ? `${fullPartial}\n\n---\n生成中断：${message}`
        : `生成中断：${message}`;
      setStreamRecovery({
        question,
        reply: fullPartial,
        reason: message,
        sessionId: activeSessionId || undefined,
        turnId: activeTurnId || null,
      });
      if (!isAbort) options.setOperationError(`聊天请求失败：${message}`);
      if (cancelledSettledRef.current) {
        // G12: a settled cancellation already wrote the durable terminal
        // state and the UI reflects it; do not overwrite with interrupted.
        return;
      }
      setMessages((current) =>
        current.map((item, index) =>
          index === userIndex
            ? {
                ...item,
                transient: true,
                turnId: activeTurnId || item.turnId,
                turnStatus: "interrupted",
              }
            : index === assistantIndex
              ? {
                  ...item,
                  avatarRole: item.avatarRole ?? "auto",
                  content: preserved,
                  transient: true,
                  turnId: activeTurnId || item.turnId,
                  turnStatus: "interrupted",
                }
              : item
        )
      );
    } finally {
      stopCancelPolling();
      if (activeTurnIdRef.current === activeTurnId) {
        activeTurnIdRef.current = null;
        activeOperationIdRef.current = "";
      }
      cancelMarkRef.current = null;
      deepRunIdRef.current = null;
      const ownsSettlement = isOwned();
      operationRegistry.complete(operationId);
      if (ownsSettlement) setIsSending(false);
    }
  };

  const retry = async () => {
    const recovery = state.streamRecovery;
    if (!recovery || isSending) return;
    const trimmedHistory = buildRetryHistory(state.chatMessages, recovery);
    await send(recovery.question, trimmedHistory, {
      retryOfTurnId: recovery.turnId ?? undefined,
    });
  };

  const continueInterrupted = async () => {
    const recovery = state.streamRecovery;
    if (!recovery?.reply || isSending) return;
    if (!recovery.turnId) {
      options.setOperationError("缺少中断 Turn ID，无法安全续写；请改用重试。");
      return;
    }
    const history = buildContinuationHistory(state.chatMessages, recovery);
    setStreamRecovery(null);
    await send(recovery.question, history, {
      continuationOfTurnId: recovery.turnId,
      partialReply: recovery.reply,
      turnId: recovery.turnId,
    });
  };

  const copyInterrupted = async () => {
    if (state.streamRecovery?.reply) {
      await navigator.clipboard.writeText(answerCopyText(state.streamRecovery.reply));
    }
  };

  const applySessionDetail = (detail: SessionDetailResponse) => {
    const restoredMessages = detail.messages.filter(
      (message) => message.role === "user" || message.role === "assistant"
    );
    const restoredSettings = detail.settings ?? {};
    const restoredRagSettings = restoredSettings.ragSettings ?? {};
    const hasFullSettings =
      typeof restoredSettings.selectedRole === "string" ||
      typeof restoredSettings.selectedMode === "string" ||
      typeof restoredSettings.relationshipMode === "string";
    const nextChatSettings: ChatSettings = hasFullSettings
      ? {
          selectedRole:
            typeof restoredSettings.selectedRole === "string"
              ? restoredSettings.selectedRole
              : options.chatSettingsDefaults.selectedRole,
          selectedMode:
            typeof restoredSettings.selectedMode === "string"
              ? restoredSettings.selectedMode
              : options.chatSettingsDefaults.selectedMode,
          selectedModel:
            typeof restoredSettings.selectedModel === "string"
              ? restoredSettings.selectedModel
              : options.chatSettingsDefaults.selectedModel,
          relationshipMode:
            typeof restoredSettings.relationshipMode === "string"
              ? restoredSettings.relationshipMode
              : options.chatSettingsDefaults.relationshipMode,
          contextMode:
            typeof restoredSettings.contextMode === "string"
              ? restoredSettings.contextMode
              : options.chatSettingsDefaults.contextMode,
        }
      : options.chatSettings;
    const nextRagSettings: RagSettings =
      typeof restoredSettings.ragEnabled === "boolean"
        ? { ...options.ragSettingsDefaults, ...restoredRagSettings }
        : options.ragSettings;
    const lastAssistant = [...restoredMessages]
      .reverse()
      .find((message) => message.role === "assistant");
    const baseRoute = detail.route ?? {};
    const committedLearningState = detail.learning_state ?? {};
    const restoredRoute = Object.keys(committedLearningState).length
      ? { ...baseRoute, learning_state: committedLearningState }
      : baseRoute;
    const restoredRag =
      detail.rag && Object.keys(detail.rag).length
        ? (detail.rag as ChatResponse["rag"])
        : createEmptyRag();
    const interrupted = tailInterruptedTurn(detail.turns);
    const restoredLastChat: ChatResponse | null =
      Object.keys(restoredRoute).length || lastAssistant
        ? {
            reply: lastAssistant?.content ?? "",
            session_id: detail.session_id,
            turn_id: interrupted?.turn_id ?? null,
            route: restoredRoute,
            rag: restoredRag,
            pedagogy: pedagogySummaryFromSnapshot(detail.pedagogy),
          }
        : null;
    const restoredRecovery = interrupted?.assistant_message
      ? {
          question: interrupted.user_message,
          reply: interrupted.assistant_message,
          reason: "上次生成中断",
          sessionId: detail.session_id,
          turnId: interrupted.turn_id,
        }
      : null;
    const restoredResearchRunId = restoredRag.web_tools?.run_id;
    if (restoredResearchRunId) options.onResearchRunDiscovered(restoredResearchRunId);

    const evidenceByTurn = evidenceFromSessionTurns(detail.turns ?? []);
    const restoredWithEvidence = restoredMessages.map((message) =>
      message.turnId && evidenceByTurn.has(message.turnId)
        ? { ...message, evidence: evidenceByTurn.get(message.turnId) }
        : message
    );

    transitionSession(
      detail.session_id,
      restoredWithEvidence.length ? restoredWithEvidence : seedMessages,
      restoredLastChat,
      restoredRecovery
    );
    const phases = phaseTrail(
      (detail.turns ?? [])
        .filter((turn) => turn.status === "completed")
        .map((turn) => {
          const snap = turn.pedagogy_snapshot ?? {};
          const committed = snap.committed_learning_state;
          if (committed && typeof committed === "object") {
            return String((committed as { phase?: string }).phase ?? "");
          }
          return String((snap as { phase?: string }).phase ?? "");
        })
        .filter(Boolean)
    );
    dispatch({ type: "SET_PEDAGOGY_PHASES", value: phases });
    options.setChatSettings(nextChatSettings);
    options.setRagSettings(nextRagSettings);
    if (typeof restoredSettings.ragEnabled === "boolean") {
      options.setRagEnabled(restoredSettings.ragEnabled);
    }
    if (typeof restoredSettings.keepCurrentRole === "boolean") {
      options.setKeepCurrentRole(restoredSettings.keepCurrentRole);
    }
    options.setConversationInstruction(detail.conversation_instruction ?? "");
    options.setInput("");
    options.clearChatArtifacts();
  };

  const restoreSession = async (sessionId: string) => {
    options.setOperationError("");
    cancelWorkspaceRuns();
    try {
      applySessionDetail(await loadSessionDetail(sessionId));
    } catch (error) {
      options.setOperationError(
        `会话恢复失败：${error instanceof Error ? error.message : "会话恢复失败"}`
      );
    }
  };

  const hydrateSession = async (sessionId: string, cachedMessages?: ChatMessage[]) => {
    setThreadId(sessionId);
    try {
      applySessionDetail(await loadSessionDetail(sessionId));
    } catch {
      if (cachedMessages?.length) {
        transitionSession(sessionId, sanitizeSingleChatMessages(cachedMessages), null);
      } else {
        setMessages(seedMessages);
      }
    }
  };

  const archiveCurrentSession = async (sessionId: string) => {
    options.setOperationError("");
    cancelWorkspaceRuns();
    const isActive = sessionId === state.activeChatThreadId;
    try {
      const archived = await archiveSession(sessionId);
      if (archived.queued) {
        // G12 decision 15: the intent is persisted server-side; it executes
        // when the cancelled operation settles (or on restart). The user can
        // still switch or start a new session right away.
        if (isActive) {
          const created = await createNewSession();
          transitionSession(created.session_id, seedMessages, null);
          options.setInput("");
          options.clearChatArtifacts();
          options.setConversationInstruction("");
        }
        await options.refresh();
        return;
      }
      if (isActive) {
        const created = await createNewSession();
        transitionSession(created.session_id, seedMessages, null);
        options.setInput("");
        options.clearChatArtifacts();
        options.setConversationInstruction("");
      }
      await options.refresh();
    } catch (error) {
      // Decision 15: a failed archive keeps the session active and shows a
      // distinct error instead of silently dropping the session.
      options.setOperationError(
        `会话归档失败：${error instanceof Error ? error.message : "会话归档失败"}`
      );
    }
  };

  const startNewSession = async () => {
    options.setOperationError("");
    cancelWorkspaceRuns();
    try {
      const created = await createNewSession();
      transitionSession(created.session_id, seedMessages, null);
      options.setInput("");
      options.clearChatArtifacts();
      options.setConversationInstruction("");
      const settings = created.settings ?? {};
      options.setChatSettings({
        ...options.chatSettingsDefaults,
        selectedRole:
          typeof settings.selected_role === "string"
            ? settings.selected_role
            : options.chatSettingsDefaults.selectedRole,
        selectedMode:
          typeof settings.selected_mode === "string"
            ? settings.selected_mode
            : options.chatSettingsDefaults.selectedMode,
        selectedModel:
          typeof settings.selected_model === "string"
            ? settings.selected_model
            : options.chatSettingsDefaults.selectedModel,
        relationshipMode:
          typeof settings.relationship_mode === "string"
            ? settings.relationship_mode
            : options.chatSettingsDefaults.relationshipMode,
        contextMode:
          typeof settings.context_mode === "string"
            ? settings.context_mode
            : options.chatSettingsDefaults.contextMode,
      });
      options.setRagEnabled(
        typeof settings.rag_enabled === "boolean" ? settings.rag_enabled : true
      );
      options.setRagSettings({
        ...options.ragSettingsDefaults,
        retrievalMode:
          settings.rag_retrieval_mode ?? options.ragSettingsDefaults.retrievalMode,
        topK:
          settings.rag_search_top_k ??
          settings.rag_top_k ??
          options.ragSettingsDefaults.topK,
        chatTopK:
          settings.rag_chat_top_k ??
          settings.rag_top_k ??
          options.ragSettingsDefaults.chatTopK,
        minScore: settings.rag_min_score ?? options.ragSettingsDefaults.minScore,
      });
      options.setKeepCurrentRole(false);
      await options.refresh();
    } catch (error) {
      options.setOperationError(
        `新建会话失败：${error instanceof Error ? error.message : "新建会话失败"}`
      );
    }
  };

  return {
    threadId: state.activeChatThreadId,
    messages: state.chatMessages,
    lastChat: state.lastChat,
    streamRecovery: state.streamRecovery,
    isSending,
    researchProgress,
    setMessages,
    setLastChat,
    setStreamRecovery,
    setThreadId,
    transitionSession,
    applySessionDetail,
    send,
    stop: () => {
      const activeTurnId = activeTurnIdRef.current;
      const operationId = activeOperationIdRef.current;
      if (activeTurnId) {
        cancelActiveResearch(activeTurnId);
      }
      if (!activeTurnId || !operationId) {
        // Legacy request without a pre-allocated handle: cooperative turn
        // cancellation cannot target it. Abort the stream only; the server's
        // disconnect settlement owns the durable state.
        operationRegistry.abort("chat");
        return;
      }
      // Decision 4: synchronous UI acknowledgement within 200 ms.
      cancelMarkRef.current?.("cancelling");
      void cancelChatTurn(activeTurnId, operationId)
        .then((result) => {
          if (result.outcome === "already_completed") {
            cancelledSettledRef.current = true;
            cancelMarkRef.current?.("completed");
            operationRegistry.abort("chat");
            return;
          }
          if (result.outcome === "accepted" || result.outcome === "already_terminal") {
            // The cancelled SSE event may already have delivered the durable
            // terminal state; never overwrite a settled turn (decision 13).
            if (!cancelledSettledRef.current) {
              // Decision 12: fixed copy distinguishes 停止中 from 慢收尾.
              cancelMarkRef.current?.("cancelling");
              startCancelPolling(activeTurnId);
            }
            return;
          }
          // not_found / operation_mismatch: fall back to aborting the stream;
          // server-side disconnect settlement still closes the turn out.
          options.setOperationError("停止请求失败：无法定位进行中的回答");
          operationRegistry.abort("chat");
        })
        .catch(() => {
          options.setOperationError("停止请求失败：取消请求未送达");
          operationRegistry.abort("chat");
        });
    },
    retry,
    continueInterrupted,
    copyInterrupted,
    restoreSession,
    hydrateSession,
    archiveCurrentSession,
    startNewSession,
    cancelWorkspaceRuns,
  };
}
