export type ResearchSource = {
  block_id: string; source_id: string; run_id: string; source_truth_version: number;
  title: string; url: string; read_status: string; publication_status: "observation_only";
};
export type ResearchBlock = {
  block_id: string; run_id: string; revision: number; tier: "lookup" | "standard" | "deep";
  research_status: string; stage: string; publication_status: "observation_only";
  candidate_count: number | null; read_count: number | null; open_critical_gap_count: number | null;
  read_attempt_count: number | null; updated_at: string; sources: ResearchSource[]; sources_truncated: boolean;
  gaps: { block_id: string; field: string; research_state: "OPEN" | "SOURCE_ACQUIRED"; support_status: string; publication_status: "observation_only" }[];
  bindings: { block_id: string; evidence_id: string; claim_id: string; source_url: string; relation: "supports" | "contradicts"; locator: string; publication_status: "observation_only" }[];
  research_phase: string | null; wave: number | null; stop_reason: string;
  evidence_gate_status: string | null; conflict_count: number | null;
};
export type ResearchPresentation = {
  snapshot_kind: "run" | "turn"; turn_updated_at: string | null;
  protocol_version: 1; session_id: string; turn_id: string; publication_status: "observation_only";
  publication_authority: false; blocks: ResearchBlock[]; truncated: boolean;
  audit_status: "pending" | "audited" | "blocked" | null;
  watch: boolean;
  audit_integrity: "absent" | "valid" | "invalid";
};
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const str = (v: unknown, max = 200): v is string => typeof v === "string" && v.length > 0 && v.length <= max;
const count = (v: unknown): v is number => Number.isSafeInteger(v) && (v as number) >= 0;
const optionalCount = (v: unknown) => v === null || count(v);
const url = (v: unknown): v is string => {
  if (!str(v, 2048) || /[\x00-\x20\\]/.test(v)) return false;
  try { const u = new URL(v); return ["https:", "http:"].includes(u.protocol) && !u.username && !u.password; } catch { return false; }
};
export function parseResearchPresentation(value: unknown): ResearchPresentation | null {
  if (!object(value) || value.protocol_version !== 1 || value.publication_authority !== false
    || !["run", "turn"].includes(String(value.snapshot_kind))
    || (value.turn_updated_at !== null && (!str(value.turn_updated_at, 100) || !Number.isFinite(Date.parse(value.turn_updated_at))))
    || (value.snapshot_kind === "run" && value.turn_updated_at !== null)
    || value.publication_status !== "observation_only" || !str(value.session_id) || !str(value.turn_id)
    || !Array.isArray(value.blocks) || value.blocks.length > 20 || typeof value.truncated !== "boolean"
    || typeof value.watch !== "boolean"
    || !["absent", "valid", "invalid"].includes(String(value.audit_integrity))
    || ![null, "pending", "audited", "blocked"].includes(value.audit_status as null)) return null;
  if (value.audit_status !== null && value.audit_integrity !== "valid") return null;
  const ids = new Set<string>();
  for (const b of value.blocks) {
    if (!object(b) || !str(b.block_id, 500) || ids.has(b.block_id) || !str(b.run_id)
      || b.block_id !== `${b.run_id}:research`
      || !count(b.revision) || !["lookup", "standard", "deep"].includes(String(b.tier))
      || b.publication_status !== "observation_only" || !str(b.research_status, 40) || !str(b.stage, 80)
      || !str(b.updated_at, 100) || !Array.isArray(b.sources) || b.sources.length > 20
      || !Array.isArray(b.gaps) || b.gaps.length > 12
      || !Array.isArray(b.bindings) || b.bindings.length > 24
      || !optionalCount(b.wave) || !optionalCount(b.conflict_count)
      || (b.research_phase !== null && !str(b.research_phase, 80))
      || typeof b.stop_reason !== "string" || b.stop_reason.length > 120
      || (b.evidence_gate_status !== null && !["pass", "partial", "conditional_pass", "fail", "unavailable", "abstain"].includes(String(b.evidence_gate_status)))
      || typeof b.sources_truncated !== "boolean"
      || ![b.candidate_count, b.read_count, b.open_critical_gap_count, b.read_attempt_count].every(optionalCount)) return null;
    ids.add(b.block_id);
    const gapIds = new Set<string>();
    for (const g of b.gaps) {
      if (!object(g) || !str(g.block_id, 500) || gapIds.has(g.block_id) || !str(g.field, 120)
        || !["OPEN", "SOURCE_ACQUIRED"].includes(String(g.research_state))
        || !["NOT_EVALUATED", "SPAN_BOUND", "SUPPORT", "CONFLICT", "INSUFFICIENT"].includes(String(g.support_status))
        || g.publication_status !== "observation_only") return null;
      gapIds.add(g.block_id);
    }
    const sourceIds = new Set<string>();
    for (const s of b.sources) {
      if (!object(s) || !str(s.block_id, 500) || sourceIds.has(s.block_id) || !str(s.source_id)
        || s.block_id !== `${b.run_id}:source:${s.source_id}`
        || s.run_id !== b.run_id || !count(s.source_truth_version) || !str(s.title) || !url(s.url)
        || !["unknown", "read", "failed", "skipped", "structured"].includes(String(s.read_status))
        || s.publication_status !== "observation_only") return null;
      sourceIds.add(s.block_id);
    }
    const bindingIds = new Set<string>();
    for (const r of b.bindings) {
      if (!object(r) || !str(r.block_id, 500) || bindingIds.has(r.block_id) || !str(r.evidence_id) || !str(r.claim_id)
        || !["supports", "contradicts"].includes(String(r.relation)) || !url(r.source_url)
        || !b.sources.some(s => object(s) && s.url === r.source_url)
        || typeof r.locator !== "string" || r.locator.length > 300 || r.publication_status !== "observation_only") return null;
      bindingIds.add(r.block_id);
    }
  }
  return value as unknown as ResearchPresentation;
}

// Keep newer revisions; duplicates/late events cannot roll back source identity.
export function mergeResearchPresentation(current: ResearchPresentation | null, incoming: ResearchPresentation): ResearchPresentation {
  if (!current || current.session_id !== incoming.session_id || current.turn_id !== incoming.turn_id) return incoming;
  const blocks = new Map(current.blocks.map(b => [b.block_id, b]));
  const staleRun = incoming.blocks.some(b => current.blocks.some(old => old.block_id === b.block_id && old.revision > b.revision));
  // Run SSE is a partial observation, not a replacement of the turn's audit ledger.
  const newerTurn = incoming.snapshot_kind === "turn" && !staleRun
    && (current.turn_updated_at === null || (incoming.turn_updated_at !== null
      && Date.parse(incoming.turn_updated_at) >= Date.parse(current.turn_updated_at)));
  // A full turn can enrich/correct a partial SSE at the same run revision.
  // Replace its block as a unit: counts can decrease or become unknown.
  for (const b of incoming.blocks) {
    const previous = blocks.get(b.block_id);
    if (!previous || previous.revision < b.revision || (previous.revision === b.revision && newerTurn)) blocks.set(b.block_id, b);
  }
  const all = [...blocks.values()];
  const envelope = newerTurn ? incoming : current;
  return { ...envelope, watch: envelope.watch || all.some(b => ["pending", "running"].includes(b.research_status)),
    blocks: all.length <= 20 ? all : [all[0], ...all.slice(-19)] };
}
