# Research Approach — "研究开场 + 过程播报" contract

Status: **Slice A (backend contract) implemented; frontend + model-generation wiring pending.**

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

## Wiring (Slice A)

- `WebLookupService.create()` seeds `context["approach"]`.
- `chat_routes._research_progress()` emits `approach` (run identity bound at
  emit time).

## Pending (Slice B and beyond)

- Project a ready summary from the Standard planner plan when it is saved.
- Wire the bounded model generation (with budget accounting) at research start.
- Frontend: `ChatResearchProgress.approach` type, controller dedupe/recovery by
  `(run, turn, sequence)`, `AnswerProgress` rendering, `ChatPanel` placement,
  copy = answer only, cancel shows stopped (not "completed"), session isolation.
- Real DeepSeek latency calibration for the "~1s deterministic / few-seconds
  meaningful" targets.

## Explicitly out of scope (frozen)

Lookup/Standard/Deep research quality & completion gates; M4-C5 Evidence Gate,
verifier, source eligibility; model-call ceiling / research budget / billing;
auto-upgrade policy; learning state, memory, answer & citation authority;
existing conversation role switching.  Production B stays OFF; RP-1 / M5 stay
NO-GO.
