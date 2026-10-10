# M4-B — B-Search observation-only Shadow for Lookup and Deep

Status: **implemented on branch `feat/m4b-lookup-deep-shadow`; per-phase flags default
OFF; not merged**. Baseline main `cdc67e31a08eb058fa6ff0d1bb8c9c2ccea47dc9` (M4-A).

## What changed vs M4-A

M4-A wired one phase with a Standard-specific module. M4-B generalises the seam and
wires the other two research phases, without duplicating the contract:

- `src/application/research_shadow_seam.py` — the generic, phase-aware seam
  (`standard` / `lookup` / `deep`), one flag per phase.
- `src/application/standard_shadow_seam.py` — now a thin compatibility shim that
  re-exports the M4-A names (behaviour unchanged).
- `src/application/shadow_telemetry_sink.py` — owns the single process-wide telemetry
  (`shadow_telemetry()` / `close_shadow_telemetry()`, closed at interpreter exit);
  Standard and Deep share it, so flusher threads cannot multiply.

## Contract (unchanged from M4-A, now per phase)

| Rule | Implementation |
| --- | --- |
| Defaults OFF | `BSEARCH_STANDARD_SHADOW` / `BSEARCH_LOOKUP_SHADOW` / `BSEARCH_DEEP_SHADOW` are independent; unknown phases are never enabled |
| OFF keeps behaviour | the hook returns before touching telemetry, so no sink/thread is created |
| No authority | records are sanitised: `authoritative=False`, `evidence_completion="UNVERIFIED"`; `grants_evidence_authority()` stays False |
| Dead end | only telemetry consumes the result (`telemetry_only`); no branch may read it |
| Non-blocking + bounded | `submit_shadow_bounded` returns immediately, shared 2-worker pool + admission semaphore, failures swallowed |
| No sink → no spend | an enabled phase with no telemetry refuses to submit |
| `submitted` ≠ persisted | the sink is best-effort; persistence is observed at the sink |

## Wiring points

- **Standard** (M4-A): `StandardContinuationService.continue_pending`.
- **Deep**: `DeepContinuationService.continue_pending` — submitted after the deep child
  execution completes, with `query=child.query`.
- **Lookup**: `WebLookupService.execute` — submitted after the deep-mode early return
  (so it covers the Lookup phase only), with `query=run.query`.

## Tests

`tests/test_research_shadow_seam_phases.py` (8): independent phase flags; unknown phase
cannot submit; Lookup phase records sanitised telemetry; the Lookup hook is a no-op when
disabled and forwards `phase="lookup"` when enabled; hook failures are swallowed; the
Deep service provisions a sink only when its flag is on and its helper never raises; the
shared sink is one instance per process.

Existing M4-A tests still pass unchanged (the shim preserves the public names).

## Telemetry schema (explicit, not silent)

Records are versioned per phase (`PHASE_SCHEMA`):

| phase | `seam_version` | `phase` key |
| --- | --- | --- |
| standard | `standard-bsearch-shadow-seam-v1` | **absent** (M4-A shape preserved) |
| lookup / deep | `research-bsearch-shadow-seam-v1` | present |

The M4-A public return type (`StandardShadowResult`: `enabled`, `submitted`,
`decision_inputs`) is restored as a real dataclass — not an alias of the generic
result — so no constructor field is added under existing callers.

## Deep observation semantics

The Deep shadow is submitted **only** when this execution drove the child to a real
terminal (after the durable re-read). Consequences, each pinned by a test:

- a newly-terminal child is observed exactly once;
- a **deferred** run observes nothing;
- a **replay** of an already-terminal child observes nothing (no double-count on
  resumption or repeated calls).

## Verification

- Regression across Standard / Deep / Lookup / continuation / shadow / learner / reader
  suites: **857 passed, 1 skipped** (plus the M4-B closeout tests below).
- `ruff` clean; mypy baseline gate **122/128, NEW=0**.

## Boundaries

Production B OFF; RP-1 NO-GO; `assess_body` UNQUALIFIED; Evidence Gate, URL
confirmation, budgets and search sources unchanged; full text stays opt-in.
