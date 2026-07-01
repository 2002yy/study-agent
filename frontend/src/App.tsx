import WorkspaceRuntime from "./app/WorkspaceRuntime";

/**
 * Stable application entrypoint.
 *
 * Feature state and server-owned run orchestration live behind
 * WorkspaceRuntime. Keeping this file deliberately small prevents feature
 * workflows from drifting back into the entry component.
 */
export default function App() {
  return <WorkspaceRuntime />;
}
