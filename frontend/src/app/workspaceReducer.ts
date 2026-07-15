import type { ChatMessage, ChatResponse, DrawerId } from "../types";
import type { SessionSummary } from "../features/sessions/sessionSummary";
import { emptySessionSummary } from "../features/sessions/sessionSummary";

export type WorkspacePanel = "chat" | "sources" | "group" | "news" | "tools" | "memory";

export type StreamRecoveryState = {
  question: string;
  reply: string;
  reason: string;
  sessionId?: string;
  turnId?: string | null;
};

export type WorkspaceRuntimeState = {
  activeChatThreadId?: string;
  activeGroupThreadId?: string;
  activeNewsRunId?: string;
  activeWebLookupRunId?: string;
  activeToolRunId?: string;
  activeMemoryRunId?: string;
  activeLearningClosureRunId?: string;
  activeRagQueryRunId?: string;
  activeRagWriteRunId?: string;
  sessionSummary: SessionSummary | null;
  chatMessages: ChatMessage[];
  lastChat: ChatResponse | null;
  streamRecovery: StreamRecoveryState | null;
  selectedPanel: WorkspacePanel;
  activeDrawer: DrawerId | null;
  pedagogyPhases: string[];
  transitionVersion: number;
};

export type WorkspaceAction =
  | { type: "SET_ACTIVE_CHAT_THREAD"; threadId?: string }
  | { type: "SET_ACTIVE_GROUP_THREAD"; threadId?: string }
  | { type: "SET_ACTIVE_NEWS_RUN"; runId?: string }
  | { type: "SET_ACTIVE_WEB_LOOKUP_RUN"; runId?: string }
  | { type: "SET_ACTIVE_TOOL_RUN"; runId?: string }
  | { type: "SET_ACTIVE_MEMORY_RUN"; runId?: string }
  | { type: "SET_ACTIVE_LEARNING_CLOSURE_RUN"; runId?: string }
  | { type: "SET_ACTIVE_RAG_QUERY_RUN"; runId?: string }
  | { type: "SET_ACTIVE_RAG_WRITE_RUN"; runId?: string }
  | { type: "SET_SESSION_SUMMARY"; summary: SessionSummary | null }
  | { type: "MARK_COMPLETED_TURN"; turnId: string }
  | { type: "SET_CHAT_MESSAGES"; value: ChatMessage[] | ((current: ChatMessage[]) => ChatMessage[]) }
  | { type: "SET_LAST_CHAT"; value: ChatResponse | null | ((current: ChatResponse | null) => ChatResponse | null) }
  | { type: "SET_STREAM_RECOVERY"; value: StreamRecoveryState | null }
  | {
      type: "TRANSITION_CHAT_SESSION";
      threadId: string;
      messages: ChatMessage[];
      lastChat: ChatResponse | null;
      summary?: SessionSummary | null;
      streamRecovery?: StreamRecoveryState | null;
    }
  | { type: "RESTORE_CHAT_SESSION"; threadId: string }
  | { type: "START_NEW_CHAT_SESSION"; threadId: string }
  | { type: "RESET_GROUP_THREAD"; threadId?: string }
  | { type: "SELECT_PANEL"; panel: WorkspacePanel }
  | { type: "OPEN_DRAWER"; drawer: DrawerId }
  | { type: "CLOSE_DRAWER" }
  | { type: "SET_PEDAGOGY_PHASES"; value: string[] };

export function createWorkspaceRuntimeState(
  partial: Partial<WorkspaceRuntimeState> = {}
): WorkspaceRuntimeState {
  return {
    selectedPanel: "chat",
    activeDrawer: null,
    pedagogyPhases: [],
    transitionVersion: 0,
    sessionSummary: null,
    chatMessages: [],
    lastChat: null,
    streamRecovery: null,
    ...partial
  };
}

export function workspaceReducer(
  state: WorkspaceRuntimeState,
  action: WorkspaceAction
): WorkspaceRuntimeState {
  switch (action.type) {
    case "SET_ACTIVE_CHAT_THREAD":
      return { ...state, activeChatThreadId: action.threadId };
    case "SET_ACTIVE_GROUP_THREAD":
      return { ...state, activeGroupThreadId: action.threadId };
    case "SET_ACTIVE_NEWS_RUN":
      return { ...state, activeNewsRunId: action.runId };
    case "SET_ACTIVE_WEB_LOOKUP_RUN":
      return { ...state, activeWebLookupRunId: action.runId };
    case "SET_ACTIVE_TOOL_RUN":
      return { ...state, activeToolRunId: action.runId };
    case "SET_ACTIVE_MEMORY_RUN":
      return { ...state, activeMemoryRunId: action.runId };
    case "SET_ACTIVE_LEARNING_CLOSURE_RUN":
      return { ...state, activeLearningClosureRunId: action.runId };
    case "SET_ACTIVE_RAG_QUERY_RUN":
      return { ...state, activeRagQueryRunId: action.runId };
    case "SET_ACTIVE_RAG_WRITE_RUN":
      return { ...state, activeRagWriteRunId: action.runId };
    case "SET_SESSION_SUMMARY":
      return { ...state, sessionSummary: action.summary };
    case "MARK_COMPLETED_TURN": {
      const current = state.sessionSummary;
      if (!current) return state;
      if (
        current.status === "summarized" &&
        current.last_completed_turn_id !== action.turnId
      ) {
        return {
          ...state,
          sessionSummary: {
            ...current,
            status: "needs_update",
            current_last_completed_turn_id: action.turnId,
            can_summarize: true,
          },
        };
      }
      return {
        ...state,
        sessionSummary: {
          ...current,
          current_last_completed_turn_id: action.turnId,
          can_summarize: current.status !== "summarized",
        },
      };
    }
    case "SET_CHAT_MESSAGES":
      return {
        ...state,
        chatMessages:
          typeof action.value === "function" ? action.value(state.chatMessages) : action.value
      };
    case "SET_LAST_CHAT":
      return {
        ...state,
        lastChat:
          typeof action.value === "function" ? action.value(state.lastChat) : action.value
      };
    case "SET_STREAM_RECOVERY":
      return { ...state, streamRecovery: action.value };
    case "TRANSITION_CHAT_SESSION": {
      const changedThread = state.activeChatThreadId !== action.threadId;
      return {
        ...state,
        activeChatThreadId: action.threadId,
        sessionSummary:
          action.summary ??
          (changedThread ? emptySessionSummary(action.threadId) : state.sessionSummary),
        chatMessages: action.messages,
        lastChat: action.lastChat,
        streamRecovery: action.streamRecovery ?? null,
        activeMemoryRunId: changedThread ? undefined : state.activeMemoryRunId,
        activeLearningClosureRunId: changedThread
          ? undefined
          : state.activeLearningClosureRunId,
        transitionVersion: state.transitionVersion + 1
      };
    }
    case "RESTORE_CHAT_SESSION": {
      const changedThread = state.activeChatThreadId !== action.threadId;
      return {
        ...state,
        activeChatThreadId: action.threadId,
        sessionSummary: changedThread
          ? emptySessionSummary(action.threadId)
          : state.sessionSummary,
        activeMemoryRunId: changedThread ? undefined : state.activeMemoryRunId,
        activeLearningClosureRunId: changedThread
          ? undefined
          : state.activeLearningClosureRunId,
        transitionVersion: state.transitionVersion + 1
      };
    }
    case "START_NEW_CHAT_SESSION":
      return {
        ...state,
        activeChatThreadId: action.threadId,
        sessionSummary: emptySessionSummary(action.threadId),
        chatMessages: [],
        lastChat: null,
        streamRecovery: null,
        pedagogyPhases: [],
        activeNewsRunId: undefined,
        activeWebLookupRunId: undefined,
        activeToolRunId: undefined,
        activeMemoryRunId: undefined,
        activeLearningClosureRunId: undefined,
        activeRagQueryRunId: undefined,
        activeRagWriteRunId: undefined,
        transitionVersion: state.transitionVersion + 1
      };
    case "RESET_GROUP_THREAD":
      return {
        ...state,
        activeGroupThreadId: action.threadId,
        activeNewsRunId: undefined,
        transitionVersion: state.transitionVersion + 1
      };
    case "SELECT_PANEL":
      return { ...state, selectedPanel: action.panel };
    case "OPEN_DRAWER":
      return { ...state, activeDrawer: action.drawer };
    case "CLOSE_DRAWER":
      return { ...state, activeDrawer: null };
    case "SET_PEDAGOGY_PHASES":
      return { ...state, pedagogyPhases: action.value };
    default:
      return state;
  }
}
