# Study Agent Next-Phase Plan

This document is the execution source of truth after Architecture V2 and
Workspace Runtime convergence. Architecture ownership is recorded in
[`ARCHITECTURE_STATUS.md`](ARCHITECTURE_STATUS.md); detailed product requirements
and audit findings are recorded in
[`superpowers/plans/2026-07-12-study-agent-consolidated-roadmap.md`](superpowers/plans/2026-07-12-study-agent-consolidated-roadmap.md).

An item is complete only when production code, regression tests, documentation
and the relevant end-to-end acceptance journey agree.

Updated: 2026-07-13  
Audited implementation head: `7ab8c3d42495032288d5a1b06df6a03052a91fd0`

## Current position

The infrastructure-focused architecture migration is substantially complete:
Chat/Session, GroupThread, NewsRun, ToolRun, MemoryRun, RAG/KnowledgeBase,
WebLookupRun and Workspace Runtime have authoritative owners. PedagogyEvalRun is
also sealed.

The current work is no longer another infrastructure migration. It is a
**product-correctness and learning-closure program**:

1. prevent temporary tasks from polluting durable learning state;
2. make web research date-aware, evidence-safe and recoverable;
3. turn after-session generation into a formal recoverable run;
4. complete session, summary and restore semantics;
5. remove pseudo precision and control-panel-heavy UI exposure.

## Progress through 2026-07-13

### Completed infrastructure gates

- Chroma replacement removes stale chunk IDs.
- SQLite owns active/staging RAG index versions and expected-version leases.
- Required vector-stage failure preserves the old active index and records
  `partial_success`.
- Stable document identity is separated from content revision identity.
- Upload validation covers batch/file limits, supported types, PDF signatures,
  DOCX structure and archive expansion limits before persistence.
- Retrieval query planning can use objective, unresolved gap, protocol and input.
- `local_hash` is marked as deterministic test/fallback retrieval.
- `PedagogyEvalRun` is committed atomically with completed turns and committed
  learning state.
- BM25, RRF hybrid fusion, duplicate suppression, source diversity, metadata
  filters, explicit embedding profiles, optional local reranking and common
  Recall/MRR/nDCG evaluation are implemented.

### Completed minimum product-correctness slice

- Invalid/empty local evidence is filtered; restored turns retain route/RAG
  snapshots; copied answers contain only message body.
- New session creation no longer archives the previous thread.
- Session transitions invalidate only the chat operation instead of calling a
  global `cancelAll()`.
- Restored UI state prefers committed learning state and completed turns.
- Enter sends, Shift+Enter inserts a line break, and IME composition does not
  submit prematurely.
- Minimal G11 task contracts classify research, learning, explain-back, project,
  conversation and quick-answer paths before pedagogy transition.
- Temporary research/quick-answer/conversation paths do not advance durable
  learning state.
- Runtime web policy supports off/ask/auto; cloud context can be limited to the
  current question, recent chat or local evidence.
- Deterministic fresh-query normalization records current UTC date, preserves raw
  spelling, generates compact model-name variants and distinguishes empty from
  unavailable search results.
- Golden regressions cover the `gpt5.6sol` failure mode without hard-coding a
  product-existence answer.

### Transitional completion only

- `/sessions/{session_id}/after-session/preview` and the UI “整理学习” action can
  generate memory candidates and open the memory drawer.
- This is usable, but it is **not** G1 completion: there is no persisted
  `LearningClosureRun`, source hash, resumable state machine or summary-status
  transition yet.

## Product roadmap status

| Goal | Status | What remains |
| --- | --- | --- |
| G9 fresh web reliability | **partial** | source assessment/ranking, controlled time-window expansion, final-answer evidence gate and live E2E validation |
| G10 ResearchRun | **not started** | server-owned state machine, attempts, selected/rejected sources, stop reason, resume/retry and follow-up reuse |
| G11 task contract | **partial** | explicit user override, topic-change gate, goal lifecycle and thread-level contract persistence |
| G13 evidence integrity | **partial** | unified selected `EvidenceRef`, web/local counts and claim-source mapping |
| G15 session truth | **partial** | summarized status, leave gates, recovery of partial research/preview/upload and full status migration |
| G16 external-data policy | **partial** | attachment sensitivity, outbound summary, provider display and first-use explanation |
| G17 interaction/accessibility | **partial** | first-use task entry, structured restore card, focus trap/return and actionable global errors |
| G1 LearningClosureRun | **not started** | formal service/repository/state machine/idempotency/recovery |
| G2 structured closure input | **not started** | committed state + PedagogyEvalRun evidence + prompt budget + candidate provenance |
| G3 true close/summary state | **not started** | summarized status, repeat prevention and post-commit continue/archive choices |
| G4 semantic session navigation | **not started** | title, preview, task/status metadata, editing, search and grouping |
| G5 learning display de-precision | **partial** | remove heuristic mastery ring and show committed evaluation state |
| G6 recovery card | **not started** | action-oriented restore from learning/research/project truth |
| G7/G8 UI convergence | **partial** | four-item dock, basic/advanced settings and complete narrow-screen reachability |
| G12 preparation stages/cancel | **partial** | structured server events, provider/research cancellation propagation and budget/stop metadata |
| G14 import/source scope | **partial** | per-file UI stages, temporary-vs-durable scope and retry/cleanup semantics |

## Execution order

### Gate A — Close the P0 audit with reproducible journeys

Before starting a large new feature, run and record these journeys against the
real application path:

1. `联网看看gpt5.6sol`: no injected stale year, no unsupported “不存在”, no
   `未命名 0.00`, and empty/provider failure remain uncertainty states.
2. Temporary research inside an active learning thread: committed objective,
   phase, confirmed points and gap remain unchanged.
3. New/switch session during chat generation: only chat is cancelled; upload,
   memory preview and independent lookup state remain.
4. Web policy off/ask/auto and cloud-context scope: actual outbound context
   matches settings.
5. Refresh after completed, interrupted and failed turns: the top strip displays
   committed truth and the evidence count is stable.

This gate may produce small G9/G13/G15/G16/G17 fixes. Do not start ResearchRun
with known P0 regressions.

### Slice B — G10 ResearchRun

Extend the existing WebLookup ownership; do not create a second competing lookup
system.

1. Define run schema and states:
   `created -> normalizing -> searching -> assessing -> expanding -> reading ->
   synthesizing -> completed | partial | failed | cancelled`.
2. Persist raw/canonical query, date/time range, attempts, selected/rejected
   sources, provider states, stop reason and answer confidence.
3. Add deterministic source assessment and bounded planner decisions.
4. Reuse completed attempts on retry and follow-up questions.
5. Emit real phase events and expose compact/default plus advanced evidence views.
6. Add fixed fixtures for first-query empty, later-query success, provider timeout,
   direct evidence stop and refresh/resume.

### Slice C — G1 LearningClosureRun

1. Add `LearningClosureService`, repository and SQLite migration.
2. Persist source thread/version/last completed turn, committed learning snapshot,
   generated result, MemoryRun reference, status and error.
3. Use a source hash for idempotent preview reuse.
4. Support retry/cancel without duplicate model cost.
5. Keep MemoryRun preview/confirm as the write boundary.
6. Reject learning-summary generation for ineligible task contracts.

### Slice D — G12 stage events and cancellation propagation

1. Standardize routing/evaluating/retrieving/normalizing/searching/reading/
   composing/streaming/saving events.
2. Carry cancellation to ResearchService, RAG and provider adapters where
   supported.
3. Persist partial results and stop reasons.
4. Enforce query/read/time/token/cost budgets.

### Slice E — G2 + G3 learning closure semantics

1. Build closure input from committed learning state and final PedagogyEvalRun
   decisions; raw chat is budgeted fallback context.
2. Attach candidate provenance/confidence and mark inferred learner-profile items
   pending.
3. Persist `summary_status`; prevent duplicate closure for unchanged thread
   versions.
4. After commit, offer continue current / archive and create new; never auto-archive.

### Slice F — G4 + G6 session and recovery semantics

1. Add meaningful title, task intent, preview, phase/gap and summary status.
2. Allow manual title editing without later automatic overwrite.
3. Add search/grouping by status, time and task.
4. Replace raw Markdown home blocks with a committed learning/research/project
   recovery card and explicit next actions.

### Slice G — Product convergence

- G5: remove the heuristic mastery ring; show validated/pending/reteach/review.
- G7: reduce primary dock to upload/session/closure/more and split settings into
  basic/advanced/expression.
- G8: verify all primary actions and labels on narrow, non-hover screens.
- G17: complete first-use entry, drawer focus management and actionable errors.
- G14: finish temporary attachment and per-file import semantics.

## RAG continuation plan

### Phase 2 — Retrieval quality (mostly complete)

- [x] Production multilingual embedding profile.
- [x] BM25 sparse retrieval.
- [x] Reciprocal-rank fusion.
- [x] Optional reranker with latency/cost budgets.
- [x] Duplicate suppression, source diversity and metadata filters.
- [x] Candidate count and latency for lexical/vector/backend/reranker stages.
- [x] Common lexical/dense/hybrid/reranked evaluation corpus.
- [ ] Expand the corpus before adding an external reranker provider.

### Phase 3 — Ingestion and KnowledgeBase domain

- [ ] Separate Parser, DocumentNormalizer, StructuralChunker, MetadataExtractor
  and index writers.
- [ ] Add heading/list/table/page-aware structure and localized parser failures.
- [ ] Add optional Docling/MinerU and demand-triggered OCR profiles.
- [ ] Add parent/child chunks, section paths and token budgets.
- [ ] Add chunk preview and parser diagnostics.
- [ ] Complete explicit domain types for KnowledgeBase, revisions, chunks,
  versions, ingestion/retrieval runs and profiles.

This phase follows the product-correctness slices unless a real ingestion defect
blocks them.

## Remaining platform phases

### API/product completion

- [~] after-session preview exists as a transitional path; replace with G1/G2/G3.
- [ ] `/stats` and `/stats/reset` with destructive confirmation.
- [ ] `/health/full` for provider, parser and index diagnostics.

### Learner Model

Start only after closure and evaluation evidence are stable. Minimum entities:
`ConceptMastery`, `Misconception`, `LearningEvidence`, `LearningEvent`. Every
mastery change must cite committed evaluation/evidence; low-confidence judgments
must not become durable mastery.

### Evaluation expansion

Keep retrieval Recall/MRR/nDCG and add evidence precision, citation correctness,
context answerability, faithfulness, duplicate/source-diversity metrics,
retrieval/rerank latency, embedding cost and stale-index consistency. Maintain
representative corpora for networking, Java backend, Python/RAG, papers and
project documentation.

### Legacy retirement

1. Remove production dependencies on the `src.api` compatibility shim after old
   clients/tests migrate.
2. Remove Streamlit after closure and remaining diagnostics are available in the
   React/FastAPI application.
3. Update README, architecture, migration and testing docs in the same change.

### Optional advanced retrieval

Concept Graph/GraphRAG remains optional and downstream of stable chunk-RAG
quality and evidence gates. It may add a cross-document retrieval path, never
replace traceable base retrieval.

## Verification required for every slice

- Targeted backend and frontend tests first.
- Complete backend test suite.
- Complete frontend Vitest suite.
- Production Vite build.
- Schema migration and rollback/compatibility checks when persistence changes.
- Manual desktop and narrow-screen journey.
- Evidence/restore comparison before and after refresh.
- Update this plan, `ARCHITECTURE_STATUS.md` and the consolidated roadmap in the
  same change.

The connected GitHub status API returned no workflow run for audited head
`7ab8c3d`; remote CI must be explicitly re-checked before claiming a release gate
has passed.
