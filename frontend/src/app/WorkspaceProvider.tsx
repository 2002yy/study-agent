import { createContext, useContext, useMemo, useReducer, type Dispatch, type ReactNode } from "react";
import {
  createWorkspaceRuntimeState,
  workspaceReducer,
  type WorkspaceAction,
  type WorkspaceRuntimeState
} from "./workspaceReducer";

type WorkspaceContextValue = {
  state: WorkspaceRuntimeState;
  dispatch: Dispatch<WorkspaceAction>;
};

const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);

export function WorkspaceProvider({
  children,
  initialState
}: {
  children: ReactNode;
  initialState?: Partial<WorkspaceRuntimeState>;
}) {
  const [state, dispatch] = useReducer(workspaceReducer, createWorkspaceRuntimeState(initialState));
  const value = useMemo(() => ({ state, dispatch }), [state]);

  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export function useWorkspace() {
  const value = useContext(WorkspaceContext);
  if (!value) {
    throw new Error("useWorkspace must be used inside WorkspaceProvider");
  }
  return value;
}
