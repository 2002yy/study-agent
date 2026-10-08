import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";

import {
  createEmptyRag,
  useChatController,
} from "../features/chat/chatController";
import { abandonInterruptedTurn } from "../features/chat/recoveryApi";
import { packAnswerUiContext } from "../features/answer-ui/answerUiProtocol";
import { useMemoryController } from "../features/learning-memory/memoryController";
import {
  buildFireflyConversationContext,
  createDefaultFireflyLessonState,
  type FireflyLessonState,
} from "../features/learning/defaultFireflyLesson";
import {
  getLearningResume,
  type LearningResumeResponse,
} from "../features/learning/learningResumeApi";
import {
  CHAT_SETTINGS_DEFAULTS,
  modeOptions,
  RAG_SETTINGS_DEFAULTS,
} from "../features/settings/SettingsPanel";
import { seedMessages } from "../features/single-chat/chatHistory";
import type { ApiSnapshot, ChatSettings } from "../types";
import {
  selectActiveLearningSession,
  selectLearningSessionSummary,
} from "./learningSessionViewModel";
import type { EvidenceLearningPort } from "./useEvidenceRuntime";
import type { WorkspaceRecovery } from "./WorkspacePersistence";
import { useWorkspace } from "./WorkspaceProvider";

type RuntimeSettings = NonNullable<ApiSnapshot["runtimeSettings"]>["settings"];

type LearningResumeState = {
  sessionId: string;
  resume: LearningResumeResponse;
};

type LearningResumeErrorState = {
  sessionId: string;
  error: string;
};

export type LearningArtifactPort = {
  clearChatArtifacts: () => void;
};

export type LearningRecoveryInput = Pick<
  WorkspaceRecovery,
  | "singleChatSessionId"
  | "sessionId"
  | "memoryRunId"
  | "learningClosureRunId"
  | "chatSettings"
  | "keepCurrentRole"
  | "conversationInstruction"
  | "lastRoute"
  | "lastRag"
  | "lastSessionId"
  | "cachedMessages"
> & {
  fireflyLessonState?: FireflyLessonState;
};

export type LearningRecoveryState = Pick<
  WorkspaceRecovery,
  | "singleChatSessionId"
  | "memoryRunId"
  | "learningClosureRunId"
  | "lastRoute"
  | "lastRag"
  | "lastSessionId"
  | "cachedMessages"
> & {
  chatSettings: ChatSettings;
  keepCurrentRole: boolean;
  conversationInstruction: string;
  fireflyLessonState: FireflyLessonState;
  isSending: boolean;
};

export type LearningRecoveryPort = {
  state: LearningRecoveryState;
  restore: (recovery: LearningRecoveryInput | null) => boolean;
  hydrateRuntimeSettings: (settings: RuntimeSettings) => void;
};

export function useLearningSessionRuntime(options: {
  refresh: () => Promise<void>;
  sessions: ApiSnapshot["sessions"];
  setInput: Dispatch<SetStateAction<string>>;
  setOperationError: Dispatch<SetStateAction<string>>;
  evidence: EvidenceLearningPort;
  webPolicy: string;
  memoryPolicy?: string;
  memoryAvailable?: boolean;
}) {
  const { state, dispatch } = useWorkspace();
  const [chatSettings, setChatSettings] = useState<ChatSettings>(
    CHAT_SETTINGS_DEFAULTS,
  );
  const [keepCurrentRole, setKeepCurrentRole] = useState(false);
  const [conversationInstruction, setConversationInstruction] = useState("");
  const [fireflyLessonState, setFireflyLessonState] = useState<FireflyLessonState>(
    createDefaultFireflyLessonState,
  );
  const [learningResumeState, setLearningResumeState] =
    useState<LearningResumeState | null>(null);
  const [learningResumeErrorState, setLearningResumeErrorState] =
    useState<LearningResumeErrorState | null>(null);
  const [learningResumeRefreshRevision, setLearningResumeRefreshRevision] =
    useState(0);
  const artifactPortRef = useRef<LearningArtifactPort>({
    clearChatArtifacts: () => undefined,
  });

  const bindArtifactPort = useCallback((port: LearningArtifactPort) => {
    artifactPortRef.current = port;
    return () => {
      if (artifactPortRef.current === port) {
        artifactPortRef.current = { clearChatArtifacts: () => undefined };
      }
    };
  }, []);
  const clearChatArtifacts = useCallback(
    () => artifactPortRef.current.clearChatArtifacts(),
    [],
  );

  const updateFireflyLesson = useCallback((patch: Partial<FireflyLessonState>) => {
    setFireflyLessonState((current) => ({ ...current, ...patch }));
  }, []);
  const resetFireflyLesson = useCallback(() => {
    setFireflyLessonState(createDefaultFireflyLessonState());
  }, []);
  const fireflyLesson = useMemo(
    () => ({
      state: fireflyLessonState,
      update: updateFireflyLesson,
      reset: resetFireflyLesson,
    }),
    [fireflyLessonState, resetFireflyLesson, updateFireflyLesson],
  );

  const memoryRunId = state.activeMemoryRunId;
  const learningClosureRunId = state.activeLearningClosureRunId;
  const setMemoryRunId = useCallback(
    (runId?: string) => dispatch({ type: "SET_ACTIVE_MEMORY_RUN", runId }),
    [dispatch],
  );
  const setLearningClosureRunId = useCallback(
    (runId?: string) =>
      dispatch({ type: "SET_ACTIVE_LEARNING_CLOSURE_RUN", runId }),
    [dispatch],
  );
  const refreshLearningState = useCallback(async () => {
    await options.refresh();
    setLearningResumeRefreshRevision((revision) => revision + 1);
  }, [options.refresh]);

  const refreshLearningResume = useCallback(() => {
    setLearningResumeRefreshRevision((revision) => revision + 1);
  }, []);

  const memoryController = useMemoryController({
    activeRunId: memoryRunId,
    setActiveRunId: setMemoryRunId,
    activeClosureRunId: learningClosureRunId,
    setActiveClosureRunId: setLearningClosureRunId,
    onMemoryChanged: refreshLearningState,
    onSummaryChanged: (summary) =>
      dispatch({ type: "SET_SESSION_SUMMARY", summary }),
  });

  const defaultLessonContext = useMemo(
    () => buildFireflyConversationContext(fireflyLessonState),
    [fireflyLessonState],
  );
  const effectiveConversationInstruction = useMemo(
    () => packAnswerUiContext(conversationInstruction, defaultLessonContext),
    [conversationInstruction, defaultLessonContext],
  );

  const chatController = useChatController({
    chatSettings,
    chatSettingsDefaults: CHAT_SETTINGS_DEFAULTS,
    setChatSettings,
    ragSettings: options.evidence.ragSettings,
    ragSettingsDefaults: RAG_SETTINGS_DEFAULTS,
    setRagSettings: options.evidence.setRagSettings,
    ragEnabled: options.evidence.ragEnabled,
    setRagEnabled: options.evidence.setRagEnabled,
    keepCurrentRole,
    setKeepCurrentRole,
    conversationInstruction: effectiveConversationInstruction,
    setConversationInstruction,
    webLookupSource: options.evidence.webLookupSource,
    webLookupRunId: options.evidence.webLookupRunId,
    useWebLookup: options.evidence.useWebLookup,
    webPolicy: options.webPolicy,
    memoryPolicy: options.memoryPolicy,
    memoryAvailable: options.memoryAvailable,
    setUseWebLookup: options.evidence.setUseWebLookup,
    setInput: options.setInput,
    setOperationError: options.setOperationError,
    clearChatArtifacts,
    refresh: options.refresh,
    onResearchRunDiscovered: options.evidence.onResearchRunDiscovered,
  });

  useEffect(() => {
    const sessionId = chatController.threadId;
    if (!sessionId) {
      setLearningResumeState(null);
      setLearningResumeErrorState(null);
      return;
    }

    const controller = new AbortController();
    setLearningResumeErrorState(null);
    void getLearningResume(sessionId, controller.signal)
      .then((resume) => {
        if (controller.signal.aborted) return;
        setLearningResumeState({ sessionId, resume });
      })
      .catch((error) => {
        if (controller.signal.aborted) return;
        setLearningResumeErrorState({
          sessionId,
          error: error instanceof Error ? error.message : "读取学习恢复状态失败",
        });
      });

    return () => controller.abort();
  }, [
    chatController.threadId,
    chatController.lastChat?.turn_id,
    learningClosureRunId,
    learningResumeRefreshRevision,
  ]);

  const activeSession = useMemo(
    () =>
      selectActiveLearningSession(options.sessions, chatController.threadId),
    [options.sessions, chatController.threadId],
  );
  const sessionSummary = useMemo(
    () =>
      selectLearningSessionSummary(
        activeSession,
        state.sessionSummary,
        chatController.threadId,
      ),
    [activeSession, state.sessionSummary, chatController.threadId],
  );

  const abandonRecovery = useCallback(async () => {
    const interrupted = chatController.streamRecovery;
    if (!interrupted) return;
    if (!interrupted.sessionId || !interrupted.turnId) {
      chatController.setStreamRecovery(null);
      return;
    }
    try {
      await abandonInterruptedTurn(interrupted.sessionId, interrupted.turnId);
      chatController.setStreamRecovery(null);
      await options.refresh();
    } catch (error) {
      options.setOperationError(
        `放弃恢复失败：${error instanceof Error ? error.message : "未知错误"}`,
      );
    }
  }, [
    chatController.streamRecovery,
    chatController.setStreamRecovery,
    options.refresh,
    options.setOperationError,
  ]);

  const restore = useCallback(
    (recovery: LearningRecoveryInput | null) => {
      if (!recovery) {
        chatController.setMessages(seedMessages);
        setFireflyLessonState(createDefaultFireflyLessonState());
        return false;
      }

      if (recovery.memoryRunId) setMemoryRunId(recovery.memoryRunId);
      if (recovery.learningClosureRunId) {
        setLearningClosureRunId(recovery.learningClosureRunId);
      }

      let restoredChatSettings = false;
      if (recovery.chatSettings) {
        setChatSettings({
          ...CHAT_SETTINGS_DEFAULTS,
          ...recovery.chatSettings,
        });
        restoredChatSettings = true;
      }
      if (typeof recovery.keepCurrentRole === "boolean") {
        setKeepCurrentRole(recovery.keepCurrentRole);
      }
      if (typeof recovery.conversationInstruction === "string") {
        setConversationInstruction(recovery.conversationInstruction);
      }

      const restoredThreadId =
        recovery.singleChatSessionId ?? recovery.sessionId ?? "";
      if (recovery.fireflyLessonState) {
        const defaults = createDefaultFireflyLessonState();
        setFireflyLessonState({
          ...defaults,
          ...recovery.fireflyLessonState,
          oneGold: {
            ...defaults.oneGold,
            ...recovery.fireflyLessonState.oneGold,
          },
        });
      } else if (restoredThreadId) {
        setFireflyLessonState({
          ...createDefaultFireflyLessonState(),
          active: false,
        });
      }

      if (restoredThreadId) {
        void chatController.hydrateSession(
          restoredThreadId,
          recovery.cachedMessages,
        );
      } else {
        chatController.setMessages(seedMessages);
      }
      if (recovery.lastRoute) {
        chatController.setLastChat({
          reply: "",
          session_id:
            recovery.lastSessionId ?? restoredThreadId ?? "restored",
          route: recovery.lastRoute,
          rag: recovery.lastRag ?? createEmptyRag(),
        });
      }
      return restoredChatSettings;
    },
    [chatController, setLearningClosureRunId, setMemoryRunId],
  );

  const hydrateRuntimeSettings = useCallback((settings: RuntimeSettings) => {
    const visibleMode = modeOptions.some(([value]) => value === settings.selected_mode)
      ? settings.selected_mode
      : "auto";
    setChatSettings({
      selectedRole: settings.selected_role,
      selectedMode: visibleMode,
      selectedModel: settings.selected_model,
      relationshipMode: settings.relationship_mode,
      contextMode:
        settings.context_mode === "fast" ||
        settings.context_mode === "light" ||
        settings.context_mode === "deep"
          ? settings.context_mode
          : "",
    });
  }, []);

  const recovery = useMemo<LearningRecoveryPort>(
    () => ({
      state: {
        singleChatSessionId: chatController.threadId,
        memoryRunId,
        learningClosureRunId,
        chatSettings,
        keepCurrentRole,
        conversationInstruction,
        fireflyLessonState,
        lastRoute: chatController.lastChat?.route,
        lastRag: chatController.lastChat?.rag,
        lastSessionId: chatController.lastChat?.session_id,
        cachedMessages: chatController.messages,
        isSending: chatController.isSending,
      },
      restore,
      hydrateRuntimeSettings,
    }),
    [
      chatController.threadId,
      chatController.lastChat,
      chatController.messages,
      chatController.isSending,
      memoryRunId,
      learningClosureRunId,
      chatSettings,
      keepCurrentRole,
      conversationInstruction,
      fireflyLessonState,
      restore,
      hydrateRuntimeSettings,
    ],
  );

  const learningResume =
    learningResumeState && learningResumeState.sessionId === chatController.threadId
      ? learningResumeState.resume
      : null;
  const learningResumeError =
    learningResumeErrorState &&
    learningResumeErrorState.sessionId === chatController.threadId
      ? learningResumeErrorState.error
      : "";

  useEffect(() => {
    if (
      learningResume?.source === "durable" &&
      learningResume.status === "active" &&
      fireflyLessonState.active
    ) {
      setFireflyLessonState((current) => ({ ...current, active: false }));
    }
  }, [
    learningResume?.source,
    learningResume?.status,
    fireflyLessonState.active,
  ]);

  const view = useMemo(
    () => ({
      activeSession,
      sessionSummary,
      sessionId: chatController.threadId,
      isSending: chatController.isSending,
      streamRecovery: chatController.streamRecovery,
      visitedPhases: state.pedagogyPhases,
      learningResume,
      learningResumeError,
      fireflyLesson,
      refreshLearningResume,
      abandonRecovery,
    }),
    [
      activeSession,
      sessionSummary,
      chatController.threadId,
      chatController.isSending,
      chatController.streamRecovery,
      state.pedagogyPhases,
      learningResume,
      learningResumeError,
      fireflyLesson,
      refreshLearningResume,
      abandonRecovery,
    ],
  );

  return {
    chatSettings,
    setChatSettings,
    keepCurrentRole,
    setKeepCurrentRole,
    conversationInstruction,
    setConversationInstruction,
    memoryRunId,
    learningClosureRunId,
    setMemoryRunId,
    setLearningClosureRunId,
    memoryController,
    chatController,
    fireflyLesson,
    bindArtifactPort,
    recovery,
    view,
  };
}

export type LearningSessionRuntime = ReturnType<
  typeof useLearningSessionRuntime
>;
