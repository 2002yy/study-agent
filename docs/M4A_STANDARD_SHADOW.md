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

- `tests/test_standard_shadow_seam.py`: 9 passed (flag default OFF; OFF never runs
  the observer; ON records only non-authoritative telemetry; a lying runner cannot
  grant authority; a `finished` + `supported` trace still yields a non-authoritative
  record; only an explicit audited grant could pass and the seam never emits one;
  runner failure swallowed; saturation rejects without blocking and returns its
  tokens; the continuation helper never raises).
- Standard/continuation/shadow/learner regression: **331 passed**.
- `ruff` clean; mypy baseline gate **122/128, NEW=0**.

### Paired shadow probe (real observer, flag ON)

Two frozen questions submitted through `observe_shadow_for_standard` with the real
B-Search runner and a `BestEffortTelemetry` sink:

| case | submit_ms | submitted | stop_reason | evidence_completion | authoritative | grants_authority | bodies |
| --- | --- | --- | --- | --- | --- | --- | --- |
| minecraft | **0.0** | true | round_limit | UNVERIFIED | false | false | 1 |
| k8s | **0.0** | true | round_limit | UNVERIFIED | false | false | 0 |

Reading: submission is genuinely non-blocking (0.0 ms — the main chain never waits),
the observations completed later in the background (≈13 s / ≈16 s within the shadow's
own bounded budget), and **no record gained evidence authority even though one read a
real article body**. This is the M4-A property under test: observable, bounded, and
non-authoritative.


## Telemetry wiring (real path)

`StandardContinuationService` obtains a **durable** sink by itself when the flag is
on: `_default_shadow_telemetry()` wraps `JsonlShadowSink` (append-only JSONL at
`BSEARCH_STANDARD_SHADOW_LOG` or `artifacts/shadow/bsearch_standard.jsonl`). With the
flag off, nothing is created. The seam additionally **refuses to submit** when no sink
is present, so an enabled flag can never burn model/network budget on a run whose
result would be discarded. The sink is best-effort: it drops on failure and never
raises into research.

### Resource lifecycle

`BestEffortTelemetry` starts one flusher thread per instance, so the service reuses a
single **process-wide** instance (`_shared_shadow_telemetry`, created lazily, closed at
interpreter exit). Verified locally: with the flag ON, 25 service constructions would
create **25** flusher threads if each owned one; with the shared instance they create
**1**, and `_close_shared_shadow_telemetry()` returns the count to baseline. In
production the chat-service factory is `lru_cache(maxsize=1)`, so the service is already
a singleton — the shared instance is belt-and-braces for other call sites and tests.

`submitted=True` means the work was **admitted to the bounded worker**, not that a
record was persisted. The sink is best-effort (permissions, full disk) and drops on
failure; persistence must be observed at the sink, never inferred from this flag.

## Evaluation validity

`tools/m3_battery.py` refuses invalid runs: a missing env file or model credentials
prints `{"run_status":"INVALID_RUN","reason":...}` and exits 2 **before** executing
anything, so a 0-search no-op can never be mistaken for a legitimate result. Covered by
`tests/test_m3_battery_precheck.py`.

## Done / remaining

**Done**: same-run full-text capture (`capture_full_text`, default **off**); durable
telemetry wiring; non-authoritative records with the `grants_evidence_authority` choke
point; the `INVALID_RUN` guard; the same-run full-text re-audit of the high-risk trio
(Redis / Minecraft / K8s); the real **OFF/ON pairing** of the whole Standard path
(result and bindings identical modulo per-parent identity hashes, ON adds no meaningful
latency, the persisted observation stays non-authoritative); and the telemetry resource
lifecycle check (one shared flusher per process, closed at interpreter exit).

**Remaining**: M4-B (Lookup/Deep shadow) and M5 (limited enablement). Full text stays
opt-in and is never written to production telemetry by default.

Boundaries held: production B OFF; RP-1 NO-GO; `assess_body` UNQUALIFIED; no search
source added; URL confirmation not weakened; default budgets unchanged.

## Same-run full-text re-audit of the high-risk trio (2026-10-10)

Re-ran Redis / Minecraft / K8s at the enhanced budget **with `capture_full_text=True`**,
so the audit reads the text that run actually saw — never a later re-fetch. The
`6000`-char bodies are the reader's *visible* cap, i.e. the honest boundary of what the
agent could use.

| case | sub-goal | verdict | same-run basis |
| --- | --- | --- | --- |
| K8s | 三者区别 | **SUPPORTED** | kubernetes.io: startup / liveness / readiness explicitly distinguished |
| K8s | 误用后果 | **SUPPORTED** | "…重启不健康的容器，或者停止向尚未就绪的容器发送流量" |
| Minecraft | 信号作用 | **SUPPORTED** | "…用于加强、延迟、锁存红石信号以及阻止信号倒流" |
| Minecraft | 延迟档位 | **PARTIAL** | page explains the repeater has 档位; the numeric 1–4 tick mapping is not in the read text |
| Redis | 单线程原因 | **MISSING** | no single-threading explanation in either saved body |
| Redis | 瓶颈 | **MISSING** | only persistence keys in an install guide |

Findings: (a) the system's own `explored` status **over-claimed** for Redis — the
same-run full text supports neither sub-goal; (b) those gaps are now evidence-backed
rather than inferred; (c) Minecraft/K8s earn a verdict only through an explicit
independent audit like this one — the shadow seam still emits `UNVERIFIED` and
`grants_evidence_authority()` stays False.

