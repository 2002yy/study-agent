export type WorkspacePanel = "chat" | "sources" | "group" | "news" | "tools" | "memory";

export type WorkspaceRuntimeState = {
  activeChatThreadId?: string;
  activeGroupThreadId?: string;
  activeNewsRunId?: string;
  selectedPanel: WorkspacePanel;
  transitionVersion: number;
};

export type WorkspaceAction =
  | { type: "SET_ACTIVE_CHAT_THREAD"; threadId?: string }
  | { type: "SET_ACTIVE_GROUP_THREAD"; threadId?: string }
  | { type: "SET_ACTIVE_NEWS_RUN"; runId?: string }
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
        activeNewsRunId: undefined,
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
