import type { ReactNode } from "react";
import type { TypographyPreset } from "./features/settings/typographyPreference";

export type AppShellProps = { children: ReactNode; typography?: TypographyPreset };

/** Pure application layout. Runtime state and feature orchestration live elsewhere. */
export default function AppShell({ children, typography = "balanced" }: AppShellProps) {
  return <div className="app-shell" data-typography={typography}>{children}</div>;
}
