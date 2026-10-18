import type { ChatResearchApproach, ChatResearchProgress } from "../../types";

/**
 * Research opening ("研究开场") — pure view helpers.
 *
 * The opening is display-only.  These helpers never touch answer content and
 * must never be merged into the copied answer text.
 */

/** Keep the newest approach; a stale (lower-sequence) or absent one never erases a known opening. */
export function mergeApproach(
  previous: ChatResearchApproach | null | undefined,
  incoming: ChatResearchApproach | null | undefined,
): ChatResearchApproach | null {
  if (!incoming) return previous ?? null;
  if (previous && incoming.sequence < previous.sequence) return previous;
  return incoming;
}

/** Carry the opening forward across progress events that omit it (legacy/older servers). */
export function mergeResearchProgress(
  previous: ChatResearchProgress | null | undefined,
  incoming: ChatResearchProgress | null | undefined,
): ChatResearchProgress | null {
  if (!incoming) return previous ?? null;
  // A different research run (or a session switch) must never inherit another
  // run's opening: isolation is keyed on the *current* run identity, not on the
  // lineage root (which a child may legitimately share with its parent).
  if (!previous || previous.run_id !== incoming.run_id) {
    return { ...incoming, approach: incoming.approach ?? null };
  }
  if (incoming.version < previous.version) return previous;
  const blocks = new Map((previous.narration ?? []).map(block => [block.block_id, block]));
  for (const block of incoming.narration ?? []) blocks.set(block.block_id, block);
  return {
    ...incoming,
    approach: mergeApproach(previous.approach, incoming.approach),
    narration: Array.from(blocks.values()).slice(-12),
    // Findings are a snapshot: [] explicitly removes excerpts invalidated by
    // steering. Legacy events that omit the field preserve the current view.
    findings: incoming.findings ?? previous.findings,
    reading_gaps: incoming.reading_gaps ?? previous.reading_gaps,
  };
}

/** The user-visible opening sentence, or null when there is nothing honest to show yet. */
export function approachSummary(progress?: ChatResearchProgress | null): string | null {
  const approach = progress?.approach;
  if (!approach || approach.status !== "ready" || !approach.summary.trim()) return null;
  return approach.summary;
}

export function approachFocus(progress?: ChatResearchProgress | null): string[] {
  const approach = progress?.approach;
  if (!approach || approach.status !== "ready") return [];
  return approach.focus.filter((item) => item.trim().length > 0);
}

/**
 * Whether the run is still in flight.  ``cancelled`` is terminal and must never
 * be rendered as a completed opening.
 */
export function isResearchActive(progress?: ChatResearchProgress | null): boolean {
  return !!progress && (progress.status === "pending" || progress.status === "running");
}
