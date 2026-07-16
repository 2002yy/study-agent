import { useCallback, useRef, useState, type Dispatch, type SetStateAction } from "react";
import {
  archiveSession,
  cancelChatResearchRuns,
  commitTurn,
  createNewSession,
  loadSessionDetail,
  sendChatStream,
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

  const cancelActiveResearch = useCallback((turnId: string) => {
    void cancelChatResearchRuns(turnId)
      .then((runs) => {
        const runId = runs[0]?.id;
        if (runId) options.onResearchRunDiscovered(runId);
      })
      .catch(() => undefined);
  }, [options.onResearchRunDiscovered]);

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
    let activeOperationId = "";
    const shouldConsumeWebLookup = options.useWebLookup && Boolean(options.webLookupSource);
    let turnWebContext = shouldConsumeWebLookup ? options.webLookupSource : "";
    if (
      !turnWebContext &&
      options.webPolicy === "ask" &&
      window.confirm("允许本轮联网搜索吗？搜索词会发送给外部搜索服务。")
    ) {
      turnWebContext = WEB_CONSENT_MARKER;
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
          continuationOfTurnId: extraOpts.continuationOfTurnId,
          retryOfTurnId: extraOpts.retryOfTurnId,
          partialReply: extraOpts.partialReply ?? "",
          turnId: activeTurnId,
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
            options.onResearchRunDiscovered(
              progress.run_id,
              ["completed", "partial", "failed", "cancelled"].includes(progress.status),
            );
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
          ? error.message
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
      if (fullPartial && activeSessionId && activeOperationId) {
        try {
          await commitTurn(activeSessionId, {
            userInput: question,
            agentReply: fullPartial,
            role: String(streamedRoute.role ?? state.lastChat?.route?.role ?? "auto"),
            mode:
              typeof streamedRoute.mode === "string"
                ? String(streamedRoute.mode)
                : typeof state.lastChat?.route?.mode === "string"
                  ? String(state.lastChat.route.mode)
                  : "auto",
            model:
              typeof streamedRoute.model_profile === "string"
                ? String(streamedRoute.model_profile)
                : typeof state.lastChat?.route?.model_profile === "string"
                  ? String(state.lastChat.route.model_profile)
                  : "auto",
            memoryEnabled: options.ragEnabled,
            routeInfo: Object.keys(streamedRoute).length
              ? streamedRoute
              : (state.lastChat?.route ?? {}),
            ragInfo: streamedRag ?? state.lastChat?.rag ?? {},
            conversationInstruction: options.conversationInstruction,
            turnId: activeTurnId || undefined,
            operationId: activeOperationId,
          });
        } catch (commitError) {
          const commitMessage =
            commitError instanceof Error ? commitError.message : "未知错误";
          options.setOperationError((current) =>
            [current, `部分回答保存失败：${commitMessage}`].filter(Boolean).join("\n")
          );
        }
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
      if (activeTurnIdRef.current === activeTurnId) {
        activeTurnIdRef.current = null;
      }
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
      await navigator.clipboard.writeText(state.streamRecovery.reply);
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
      await archiveSession(sessionId);
      if (isActive) {
        const created = await createNewSession();
        transitionSession(created.session_id, seedMessages, null);
        options.setInput("");
        options.clearChatArtifacts();
        options.setConversationInstruction("");
      }
      await options.refresh();
    } catch (error) {
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
      if (activeTurnId) {
        cancelActiveResearch(activeTurnId);
      }
      operationRegistry.abort("chat");
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
