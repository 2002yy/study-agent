# Research Presentation-1 (B line)

Status: implementation in progress; not CLOSED. Authority baseline: main
`766c0b67442bfbbc4b8fc63e4acd00757c0062bb` (Deep-4A merged; Deep-4B NO-GO).
Owner: `codex/reading-notebook-ui`, separate from Learning State-1.

2026-10-08 user ruling: continue B independently while #201 closes separately.
The earlier sequencing dependency is lifted; UI and learning merge gates are not
claimed closed by this work.

## Locked scope

R1–R5 add a read-only common projection for existing Lookup/Standard/Deep runs,
an additive SSE event, and a recoverable conversation workspace. Run revisions,
session/turn ownership, source IDs, read states, evidence associations, gaps,
wave/stop state and the existing validated audit ledger drive the UI.

`research_status` describes execution; `publication_status=observation_only`
and `publication_authority=false` describe presentation. Neither source discovery,
a successful read, support metadata, nor an audited Deep candidate authorizes an
answer. Candidate bodies and unapproved numeric values are omitted. Existing
whole-answer publication buffering is unchanged. No per-segment publication,
research engine/budget changes, Learning State writes or arbitrary JavaScript.

## Presentation contract

- `research_presentation` SSE carries a bounded per-run snapshot during prepare.
- `GET /sessions/{session_id}/turns/{turn_id}/research-presentation` restores the
  durable snapshot and follows existing continuations without executing them.
- Protocol v1 uses stable `run_id:research` block IDs and monotonic run revisions.
  Scope mismatch is rejected. Equal/older revisions cannot overwrite a newer run.
  Cancellation/retry generation guards reject late callbacks; unmount aborts fetch.
- `snapshot_kind=run` SSE only updates run observations; it cannot replace the
  durable turn audit. `snapshot_kind=turn` recovery carries the existing
  `ChatTurn.updated_at` as `turn_updated_at`. Older turn observations cannot
  roll back audit metadata; newer invalid audit ledgers invalidate the view.
  SSE revisions do not restart pending restoration requests.
- Polling occurs only while the server reports unfinished work; hidden tabs pause.
  Unknown counters remain null. Missing information is not interpreted as zero.
- Standard read provenance reuses the existing body-hash projection. Deep audit
  status reuses `validate_recorded_publication`; invalid ledgers grant no status.
- Existing synchronous Deep runs use the server's recorded `research_mode`;
  missing modern cursor waves remain unknown. Counters use recorded run metrics,
  instrumented owned turn recovery or actual read summaries. Default zero fields
  from an uninstrumented tool trace are not evidence of zero observations.
- Legacy model-selected study-ui components remain available for ordinary teaching;
  research answers do not use model-supplied unbound numeric widgets.

## Acceptance and delivery boundary

R1–R5 require projection/ownership/publication negative controls, stream EOF,
revision and cancellation isolation, restoration, desktop/mobile and keyboard checks.
R6 additionally requires real Lookup, Standard and Deep cases, component selection,
operation and latency evidence. Mock browser cases and deterministic backend tests
prove rendering/contracts, not real provider research quality. The 12-call Flash
pilot proves only small-sample teaching component selection; TTUV remains unmeasured.
No R6 closure or product speed claim is permitted on those samples alone.

The user requested that prior UI improvements reach main promptly. They are now
being integrated separately in `codex/ui-main-integration`, using the frozen
`511f21286e9fc7545dbacaac831945bf2470af00` UI baseline. This contract's uncommitted
research work stays in this worktree and does not enter the earlier UI PR.
The UI integration is now ready-for-review PR #201, UI production head
`e1a24697f1fad1546614fd81123bc56db90cdca4`, docs-only delivery head
`4b229fa94af7751759b2617ba754b859889ee722`. Local frontend/browser/real-stack
gates passed (453/77/14). Backend full regression at its earlier backend candidate
f60c27e5 passed 4142 with 6 skips; subsequent UI/docs changes leave that backend tree
unchanged. Current-head CI run `37762704761` was observed pending once; independent
final review and CI remain merge gates. This does not qualify RP1 or close R6.
After synchronizing the refinement, RP1 frontend tests 460/build passed; backend
projection/Standard binding/Deep execution impact tests passed 65. The uncommitted
feature snapshot is exported outside the repo for recovery; no RP1 PR exists yet.

## 2026-10-08 independent B checkpoint

Implementation adds stale-audit and partial-event isolation, stable block identity
validation, cancellation-safe polling and automatic resumption when new work arrives.
Frontend 466/build PASS; final named L2 258 PASS (102.31s); Ruff PASS; mypy baseline 122/128 NEW0. Named L1/L2 sets are now recorded in
`tests/stage_gates.json`. Final stage/browser/API gates are recorded in the handoff.
The completed 79-test browser run includes desktop/mobile restoration, source and
audit state, answer invariance, keyboard refresh and layout; screenshots were viewed.

Five real HTTP/SSE observations are retained under
`D:/study-agent-validation/reading-notebook-ui-evidence/rp1-live*` (original SQLite,
events, timings, server logs and production digests). Current projection replay is
`rp1-live-reprojection.json`: 5/5 real persisted turns, zero new provider calls,
unchanged database bytes. It confirms Lookup read count 1 and synchronous Deep
read count 4; that Deep run has no modern cursor wave, so its wave stays unknown.

TTFP was 4.797–11.125 seconds across these single observations. TTUV remains null;
first progress and token timing are not qualification of useful published content.
Four extended-wording cases ended `requested_claim_plan_unavailable`; the supported
FastAPI version/release-date case ended `no_verified_relevant_source`. Neither
entered modern Standard/Deep. These are retained failed qualification samples,
not simulated successes. R6 remains NOT CLOSED. The next R6 slice requires a real
qualified Standard-to-background-Deep path and restoration/operation/TTUV evidence.
Changing engine admission, evidence authority or publication is outside RP1 scope.
No new backend L3/remote GO is claimed before RP1 phase closure.

Final frozen-code gates: browser 79 PASS / 2.1m; real React/FastAPI/SQLite browser 14 PASS / 49.8s; restoration-specific unit 13 PASS. A focused two-case browser invocation passed its cases but failed the repository-wide teardown because it did not generate the complete Golden Journey manifest; the full final run above supplies that manifest without weakening teardown. This slice is a local R1-R5 checkpoint, not RP1 phase closure. No RP PR or remote CI was triggered. Once the separate UI integration reaches main, transfer only the RP increment from ec02590f onto that final main, preserving its image-consent fix and Learning State-1. Existing real observations remain tied to their original dirty source digests; the final projection evidence is explicitly frozen replay, not new-head provider execution.
