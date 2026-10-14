# Research Approach — "研究开场 + 过程播报" contract

Status: **Slice A (backend contract) + Slice B (frontend rendering) implemented (PR #225);
plan projection + model generation still pending.**

## Purpose

Make the agent's intent legible: *user asks → agent states a specific research
direction → tools run → narration follows real progress → a verified answer is
published.*  This is a **communication** feature.  It does **not** claim to fix
the product's answer-completion rate.

## What the object is (and is not)

`ResearchApproach` (`schema = research-approach-v1`) is **display-only**.  It
carries **no evidence authority**:

- it is never written into the Evidence Gate;
- it never turns a research goal into `supported`;
- it never becomes a factual citation in the answer;
- it is never fed back to the fact verifier as evidence.

It lives in the research run's persisted `research_context["approach"]` (SQLite
`web_lookup_runs.research_context`), so it survives page refresh.  It is emitted
on the existing `research` SSE event as an **optional** `approach` field; legacy
clients that ignore it keep working.

## The strict plan contract is untouched

`standard-research-plan-v1` (`src/web/research/standard_plan.py`) enforces an
exact four-key envelope (`schema`, `query`, `handoff_sha256`, `gaps`).  Adding a
`summary` there would break `validate_plan`.  The approach is therefore a
**separate** object.

## Origins (order of preference)

| origin | meaning | cost |
| --- | --- | --- |
| `model_plan` | projected from a plan the model already produced | none |
| `model_generated` | one bounded completion produced the opening | counted |
| `direction_update` | mode upgrade / steering continuation | none extra |
| `fallback` | honest generic hint, degraded path | none |

`status ∈ {pending, ready, failed}`; `pending` is the creation-time seed (no
summary yet) — the UI shows the existing deterministic tool progress meanwhile.

## Guarantees

1. **Failure never blocks research.** `generate_approach_or_fallback` swallows
   timeouts, empty content, and invalid payloads and degrades to `fallback`.
2. **No budget breach.** The generator is a single bounded call (short timeout,
   small `max_tokens`) and reports whether it spent a call; callers must account
   it against the existing research model-call budget.
3. **Not an answer token stream.** The approach travels the `research` progress
   channel, never the buffered `token` channel, so unverified content can never
   leak into the published answer.
4. **Deterministic validation.** `validate_approach` rejects: wrong schema/enums,
   empty or oversized summaries (per-mode limits), filler openings
   ("让我看看"…), unverified completion claims in an initial opening, and exact
   duplicates of the previous summary.

## API (module `src/web/research/research_approach.py`)

- `seed_approach(mode, root_run_id, turn_id)` — creation-time pending seed.
- `project_from_plan(mode, summary, focus, …)` — preferred path.
- `generate_approach(completion, …)` / `generate_approach_or_fallback(…)`.
- `direction_update(previous, summary, mode=…)` — continue, never re-open.
- `fallback_approach(mode, …)`.
- `validate_approach(approach, previous=…, allow_progress_claims=…)`.
- `approach_event(approach, root_run_id, turn_id)` — wire payload.

## Wiring

- `WebLookupService.create()` and `create_follow_up()` seed `context["approach"]`
  (every run starts initialised).
- `chat_routes._research_progress()` emits `approach`; `root_run_id` is bound to
  the true lineage root for child runs (isolation keys on the current run id).

## Client isolation rules

- **Run isolation**: a new `run_id` never inherits another run's opening.
- **Session isolation**: switching/restoring a session clears local progress.
- **Ordering**: within one run, a stale (lower-`sequence`) approach never
  overwrites a newer one; `direction_update` advances the sequence.
- **Robustness**: a corrupted persisted approach only suppresses display; it can
  never raise into the progress or answer path.

## Pending (next slices)

- **Plan projection (deterministic, implemented + wired in the stacked slice):**
  `summarize_plan(mode, fields)` projects the plan's own unresolved field names
  into a short direction — **no extra call**, four-key envelope untouched,
  degrades to `fallback` when the plan has no usable fields.  Wired in
  `StandardExecutionRepository.save_research_plan`: on a saved plan the approach
  is persisted as `origin=model_plan, status=ready, sequence=1`; a projection
  failure never blocks the loop.
- **Bounded generation (implemented in the stacked slice, `approach_generation.py`):**
  `ApproachGenerationCoordinator` enforces the frozen contract — trigger
  priority (`model_plan` wins, zero extra calls), **budget permission before the
  request** with every real attempt counted, one generation per authorization
  (same `(run_id, operation_id)` cannot double-spend), identity/terminal/
  authoritative-origin checked writes (never `sequence` alone), no late
  overwrite after cancel/end/newer direction, and failure that never
  propagates.  The budget gate (`authorize`) is injected from the existing
  budget authority; this feature does not own the model-call ceiling.
  **Live binding:** `standard_execution_bindings(execution, clock=…,
  model_call_ceiling=…)` binds the coordinator to the Standard journal.
  `authorize` → `authorize_approach_attempt` (persisted reservation sharing the
  **existing** ceiling: `planner_calls + approach_generation_calls` must stay
  below `model_call_ceiling`; identity is verified first) and `write` →
  `record_approach` (**check + write in one transaction**).  A missing model
  callback degrades with **no reservation**.
  **Off-path execution:** `ApproachTaskScheduler` runs the attempt on a bounded
  application-owned pool, gated by `RESEARCH_APPROACH_GENERATION` (default off),
  never waiting for a display task; the Standard loop schedules after planning
  (`StandardResearchLoop(..., approach_scheduler=…)`), so a ready projection
  yields `not_needed` and zero extra calls.
  **Production wiring:** `StandardContinuationService` builds the scheduler per
  run (flag + model callback required), passes it to `StandardResearchLoop`, and
  shuts it down (`wait=False`) once research ends — never waiting for display.
  The queue is bounded (`max_pending`), not just concurrency.
  **Budget:** the ceiling is **supplied by the budget owner**
  (`approach_model_call_ceiling`, default `0` = no extra call); the feature does
  **not** invent a ceiling and does not raise planning's allowance.
  **Remaining:** Lookup/Deep run-kind adapters, and the real DeepSeek acceptance.
- **Field display:** `translate_field` maps known plan field names to natural
  labels (`release_date → 发布日期`); unknown names are shown unchanged, so a
  projection can never invent a research dimension.
- Only if plan data is insufficient **and** budget allows, wire the bounded
  DeepSeek generation (budget permission first, counted attempts; a late result
  must not overwrite a cancelled terminal state). Opening generation must **not**
  be a synchronous prerequisite for the main research.
- Real DeepSeek end-to-end acceptance (plain question, complex comparison, Go
  rules, mid-run added conditions) measuring opening **arrival time and quality**.

## Explicitly out of scope (frozen)

Lookup/Standard/Deep research quality & completion gates; M4-C5 Evidence Gate,
verifier, source eligibility; model-call ceiling / research budget / billing;
auto-upgrade policy; learning state, memory, answer & citation authority;
existing conversation role switching.  Production B stays OFF; RP-1 / M5 stay
NO-GO.
