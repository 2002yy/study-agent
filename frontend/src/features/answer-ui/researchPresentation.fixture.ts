import type { ResearchPresentation } from "./researchPresentation";
export const researchFixture = (): ResearchPresentation => ({
  snapshot_kind: "turn", turn_updated_at: "2026-10-08T10:00:00Z",
  protocol_version: 1, session_id: "s1", turn_id: "t1", publication_status: "observation_only",
  publication_authority: false, truncated: false, audit_status: null, watch: true, audit_integrity: "absent",
  blocks: [{ block_id: "r1:research", run_id: "r1", revision: 2, tier: "lookup", research_status: "running",
    stage: "reading", publication_status: "observation_only", updated_at: "2026-10-08T10:00:00Z",
    candidate_count: 3, read_count: null, open_critical_gap_count: 1, read_attempt_count: null,
    sources_truncated: false, gaps: [], bindings: [], research_phase: "reading", wave: null, stop_reason: "", evidence_gate_status: null, conflict_count: null,
    sources: [{ block_id: "r1:source:1", source_id: "1", run_id: "r1",
      source_truth_version: 2, title: "官方资料", url: "https://example.com/a", read_status: "unknown", publication_status: "observation_only" }] }],
});
