# M4-A — B-Search observation-only Shadow (Standard research path)

Status: **implemented on branch `feat/m4a-standard-shadow`; flag defaults OFF; not
merged**. Baseline main `31cf79937cce96b52778bd504d4a0c19fc2a883e`.

## Why

M3 (cross-topic qualification, `eval/bsearch-m3`) returned **3/21 SUPPORTED**
sub-goals, so research output is **not** authorised. But the run also showed the
execution chain works (search → follow → read → honest stop) and that failures can
be layered. M4-A therefore wires B-Search as a **read-only shadow** of Standard so
its incremental value can be measured without letting it influence any answer.

## Contract (frozen)

| Rule | Implementation |
| --- | --- |
| Shadow defaults OFF | `BSEARCH_STANDARD_SHADOW` unset → `observe_shadow_for_standard` returns disabled and never calls the observer |
| Flag OFF keeps behaviour | the continuation path is unchanged; the seam call is a no-op |
| Flag ON may not change answers | the seam's result is a dead end: only telemetry consumes it (`telemetry_only`); the Standard `result`, bindings, artifact, Evidence Gate, memory and learner state cannot read it |
| Shadow cannot grant evidence | records are sanitised: `authoritative=False` and `evidence_completion="UNVERIFIED"` are pinned for **any** runner |
| Shadow cannot slow or break the chain | `submit_shadow_bounded` returns immediately (no caller wait), uses the shared 2-worker pool + admission semaphore (reject on saturation), and every failure is swallowed |
| Limits preserved | SSRF, URL confirmation, Reader caps and budgets are untouched |

## Two independent fields (from the M3 review)

`stop_reason` (why execution ended) and `evidence_completion` (whether the evidence
suffices) are recorded **separately**. `round_limit` is a legitimate stop reason and
is **not** rewritten to `finished_incomplete`. Under the shadow seam,
`evidence_completion` is always `UNVERIFIED` because a shadow run has no independent
full-text audit; a later full-text re-audit — never a re-fetch standing in for the
same run — is required to raise it.

## Wiring point

`src/application/standard_continuation.py::StandardContinuationService.continue_pending`
— after the Standard result exists and the handoff query is known, before the
artifact is finalised:

```python
self._observe_standard_shadow(query=query, handoff=terminal.get("handoff"))
```

Optional constructor injection: `shadow_telemetry` (`BestEffortTelemetry`) and
`shadow_runner` (test double). Both default to `None` (inert / real observer).

## Files

- `src/application/standard_shadow_seam.py` (new)
- `src/application/shadow_isolation.py` (+`submit_shadow_bounded`)
- `src/application/standard_continuation.py` (optional, inert-by-default seam call)
- `tests/test_standard_shadow_seam.py` (new, 7 tests)

## Verification

- `tests/test_standard_shadow_seam.py`: 7 passed (flag default OFF; OFF never runs
  the observer; ON records only non-authoritative telemetry; a lying runner cannot
  grant authority; runner failure swallowed; saturation rejects without blocking;
  the continuation helper never raises).
- Standard/continuation/shadow/learner regression: **322 passed**.
- `ruff` clean; mypy baseline gate **122/128, NEW=0**.

## Not done / next

- **P0 instrument**: the M3 battery must fail loudly (`INVALID_RUN`) when
  `STUDY_AGENT_ENV`/model credentials are missing (currently a silent 0-search
  no-op) and must persist full body text + excerpt offsets for independent audit.
- **P0 evidence authority**: ensure `finished`/`explored` can never be consumed as
  evidence anywhere outside telemetry.
- **Paired M4-A run**: frozen M3 sample + a few new Standard tasks, OFF vs ON, with
  Redis/Minecraft/K8s reported as UNVERIFIED unless same-run full bodies exist.
- M4-B (Lookup/Deep shadow) and M5 (limited enablement) remain gated.

Boundaries held: production B OFF; RP-1 NO-GO; `assess_body` UNQUALIFIED; no search
source added; URL confirmation not weakened; default budgets unchanged.
