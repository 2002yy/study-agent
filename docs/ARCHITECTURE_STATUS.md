# Architecture Status

This file is the single source of truth for **architecture ownership and sealing
status**. Product-experience requirements and audit findings are tracked in
[`docs/superpowers/plans/2026-07-12-study-agent-consolidated-roadmap.md`](superpowers/plans/2026-07-12-study-agent-consolidated-roadmap.md).
Execution order is tracked in [`NEXT_PHASE_PLAN.md`](NEXT_PHASE_PLAN.md).

Updated: 2026-07-13  
Audited head: `7ab8c3d42495032288d5a1b06df6a03052a91fd0`

## Status vocabulary

- **sealed**: one authoritative owner, durable state, recovery path and regression
  coverage exist for the stated architectural boundary.
- **partial**: the production path is active, but one or more lifecycle,
  persistence, recovery or product-contract requirements remain.
- **transitional**: a usable compatibility path exists, but it is not the final
  owner or state machine.
- **not started**: requirements exist, but no production vertical slice owns them.

A sealed technical slice does not imply that every user-facing workflow around it
is complete. For example, Chat/Session storage is sealed while session titles,
summary states and full leave/restore semantics are still partial.

## Current vertical slices

| Vertical slice | Status | Authoritative owner / remaining boundary |
| --- | --- | --- |
| Chat/Session core | **sealed** | FastAPI services + SQLite + `chatController`; product transition semantics remain under G4/G15 |
| Pedagogy protocol | **partial** | protocol V2 integrated; learning-state presentation and goal lifecycle remain incomplete |
| PedagogyEvalRun | **sealed** | deterministic-first + structured semantic evaluation committed atomically with completed turns |
| Task intent contract (G11) | **partial** | minimal runtime classifier and task-aware pedagogy enforcement are active; explicit override, topic-change gate, goal lifecycle and thread-level contract remain |
| GroupThread | **sealed** | Group service/repository + `groupChatController` |
| NewsRun | **sealed** | News service/repository + `newsController` |
| ToolRun | **sealed** | Tool service/repository + `toolController` |
| MemoryTransaction | **sealed** | `MemoryRun` + hash-locked commit + `memoryController` |
| Learning closure | **transitional** | after-session preview can create memory candidates; formal `LearningClosureRun`, idempotent recovery and summary status do not exist yet |
| RAG/KnowledgeBase | **sealed** | version-safe runs + revisions + validated ingestion + pedagogy query planning |
| WebLookupRun | **sealed (base lookup)** | durable lookup service/controller exists; it is not yet a multi-step ResearchRun |
| ResearchRun (G10) | **not started** | source assessment, controlled expansion, stop reasons, retry/resume and follow-up reuse still need one server-owned owner |
| Fresh web query policy (G9) | **partial** | deterministic normalization, UTC date grounding, query variants and structured empty/unavailable semantics are active; full source ranking and research lifecycle remain |
| External data policy (G16) | **partial** | web off/ask/auto and cloud-context limits are enforced in chat preparation; attachment-level sensitivity and full outbound summaries remain |
| Evidence contract (G13) | **partial** | invalid local citations, duplicate labels, copy behavior and restored snapshots are fixed; unified selected-evidence/claim mapping is not complete |
| Scoped operation ownership | **partial** | ordinary session transitions cancel only chat operations; server-side research-stage cancellation and complete owner propagation remain |
| App entry | **sealed** | composition-only `App.tsx` |
| AppShell | **sealed** | layout-only component with no state, API or persistence |
| Workspace Runtime | **sealed** | controller construction, recovery, persistence and rendering have explicit owners |
| Compatibility API | **legacy shim** | frozen `src/api/__init__.py` attributes for old tests/clients |
| Streamlit | **legacy compatibility** | `app.py` and `src/ui/*`; not the primary architecture |

## Completed architecture execution order

1. **P0 — Web alignment:** gateway/reader boundaries, structured evidence,
   durable WebLookupRun, service/controller ownership.
2. **P1 — MemoryTransaction:** SQLite repository/service, `/memory-runs`,
   hash-locked commit, controller and display-only panel.
3. **P2 — RAG/KnowledgeBase:** durable query/upload/rebuild runs, controllers,
   document lifecycle and monotonic index versions.
4. **P3 — Shell convergence:** shared server query cache, settings/role/workflow
   controllers, composition-only `App.tsx`, layout-only `AppShell`,
   schema-versioned persistence, recovery and view binding.
5. **Pedagogy evaluation:** `PedagogyEvalRun` is attached to the real chat-turn
   completion transaction and blocks unsafe phase advancement.
6. **Experience-integrity minimum slice (2026-07-12):** committed-state restore,
   scoped chat cancellation, non-archiving session creation, citation filtering,
   pure-body copy, IME-safe Enter handling and decorative avatar semantics.
7. **Task/policy minimum slice (2026-07-12 to 2026-07-13):** canonical task
   contract enforcement, external-data controls and fresh-query normalization.

## Current correctness layer

The following commits form the latest audited product-correctness baseline:

- `b9154be` — evidence integrity, committed learning-state restoration, scoped
  chat cancellation, safe new-session semantics and message interaction fixes.
- `6fad996` — minimal G11 task contract active in routing, pedagogy evaluation,
  learning-state transitions and closure-button visibility.
- `0f927e9` — runtime web policy and cloud-context policy enforced in the real
  chat preparation path, with frontend settings and per-turn consent.
- `7ab8c3d` — deterministic fresh-query normalization, current-date context,
  structured empty/unavailable semantics and `gpt5.6sol` golden regressions.

These changes close several high-risk false-state paths, but they do **not** seal
G1–G17 as a whole.

## Pedagogy status

Pedagogy V2 is integrated but deliberately not sealed as a complete product
experience. Socratic progression requires a validated explanation rather than
keyword claims. Explicit mode intent overrides sticky routing; protocol payloads
are isolated and restored per mode; Feynman and Project own distinct phase
machines. Retrieval is private by default, and disclosure selects complete
evidence units. Turn completion and `ChatThread.learning_state` advance in one
SQLite transaction.

`PedagogyEvalRun` is sealed as a server-owned vertical slice. The live turn
pipeline evaluates learner claims deterministic-first, delegates only ambiguous
claims to a strict structured semantic adapter, and records deterministic and
semantic results, confidence, evidence references, versions and the final
decision in SQLite. Provider or parse failure becomes `needs_semantic_review`;
transfer, completion and delivery states cannot advance without an accepted
evidence-grounded result.

The remaining pedagogy-facing work is presentation and lifecycle work: remove the
heuristic mastery ring, show the latest committed evaluation, add explicit goal
lifecycle and build a structured recovery card.

## Next architecture slices

1. **G10 ResearchRun:** extend the existing WebLookup ownership instead of
   creating a competing research subsystem.
2. **G1 LearningClosureRun:** replace route-level after-session orchestration with
   an idempotent, recoverable application service and run repository.
3. **G12 stage events and cancellation propagation:** expose real preparation
   stages and carry cancellation through research/RAG/provider boundaries.
4. **G2/G3 closure semantics:** generate from committed teaching evidence, then
   persist summarized/completed state without automatic archive.
5. **G4/G6 session semantics and recovery card:** meaningful titles, task/status
   metadata and action-oriented restore.
6. **G5/G7/G8/G17 product convergence:** remove pseudo precision, simplify the
   dock/settings hierarchy and finish narrow-screen/accessibility behavior.

## Verification status

The audited commits contain backend/frontend regression tests for their changed
boundaries. The connected GitHub status endpoint returned no workflow run or
combined status for audited head `7ab8c3d`; therefore remote CI is **not claimed
as verified** in this document. Before the next release tag, run the complete
backend suite, frontend Vitest suite, production build and the manual P0 journey
listed in the consolidated roadmap.

## Compatibility policy

- New production imports from `src.api` are forbidden; use the owning module.
- Existing `src.api` attributes are frozen for older tests and clients.
- Compatibility endpoints require a migration note plus replacement coverage
  before removal.
- `app.py` and `src/ui/*` receive compatibility fixes only, not new features.
