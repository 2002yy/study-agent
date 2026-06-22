import type { ChatMessage, ChatResponse } from "../types";

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
  activeToolRunId?: string;
  chatMessages: ChatMessage[];
  lastChat: ChatResponse | null;
  streamRecovery: StreamRecoveryState | null;
  selectedPanel: WorkspacePanel;
  transitionVersion: number;
};

export type WorkspaceAction =
  | { type: "SET_ACTIVE_CHAT_THREAD"; threadId?: string }
  | { type: "SET_ACTIVE_GROUP_THREAD"; threadId?: string }
  | { type: "SET_ACTIVE_NEWS_RUN"; runId?: string }
  | { type: "SET_ACTIVE_TOOL_RUN"; runId?: string }
  | { type: "SET_CHAT_MESSAGES"; value: ChatMessage[] | ((current: ChatMessage[]) => ChatMessage[]) }
  | { type: "SET_LAST_CHAT"; value: ChatResponse | null | ((current: ChatResponse | null) => ChatResponse | null) }
  | { type: "SET_STREAM_RECOVERY"; value: StreamRecoveryState | null }
  | {
      type: "TRANSITION_CHAT_SESSION";
      threadId: string;
      messages: ChatMessage[];
      lastChat: ChatResponse | null;
      streamRecovery?: StreamRecoveryState | null;
    }
  | { type: "RESTORE_CHAT_SESSION"; threadId: string }
  | { type: "START_NEW_CHAT_SESSION"; threadId: string }
  | { type: "RESET_GROUP_THREAD"; threadId?: string }
  | { type: "SELECT_PANEL"; panel: WorkspacePanel };

export function createWorkspaceRuntimeState(
  partial: Partial<WorkspaceRuntimeState> = {}
): WorkspaceRuntimeState {
  return {
    selectedPanel: "chat",
    transitionVersion: 0,
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
    case "SET_ACTIVE_TOOL_RUN":
      return { ...state, activeToolRunId: action.runId };
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
    case "TRANSITION_CHAT_SESSION":
      return {
        ...state,
        activeChatThreadId: action.threadId,
        chatMessages: action.messages,
        lastChat: action.lastChat,
        streamRecovery: action.streamRecovery ?? null,
        transitionVersion: state.transitionVersion + 1
      };
    case "RESTORE_CHAT_SESSION":
      return {
        ...state,
        activeChatThreadId: action.threadId,
        transitionVersion: state.transitionVersion + 1
      };
    case "START_NEW_CHAT_SESSION":
      return {
        ...state,
        activeChatThreadId: action.threadId,
        chatMessages: [],
        lastChat: null,
        streamRecovery: null,
        activeNewsRunId: undefined,
        activeToolRunId: undefined,
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
    default:
      return state;
  }
}
