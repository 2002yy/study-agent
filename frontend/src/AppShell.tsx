import type { ReactNode } from "react";

export type AppShellProps = { children: ReactNode };

/** Pure application layout. Runtime state and feature orchestration live elsewhere. */
export default function AppShell({ children }: AppShellProps) {
  return <div className="app-shell">{children}</div>;
}
