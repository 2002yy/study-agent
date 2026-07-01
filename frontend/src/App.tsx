import AppShell from "./AppShell";

/**
 * Stable application entrypoint.
 *
 * Feature state and server-owned run orchestration live in controllers used by
 * AppShell. Keeping this file deliberately small prevents feature workflows
 * from drifting back into the entry component.
 */
export default function App() {
  return <AppShell />;
}
