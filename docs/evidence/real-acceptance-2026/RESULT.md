# Real-Model Acceptance Result — 2026-10-15

> **Verdict: `FAIL`** — A failed, B and C passed. Run stopped after one round.
> Executed head: `4cb28374ff88641696c97155ee1c161c708b088f` (clean tracked checkout).
> Harness: `frontend/playwright.real-acceptance.config.ts` +
> `frontend/e2e/real-acceptance.spec.ts` (real `src.api:app`, real DeepSeek, real search).
> Raw artefacts: `frontend/test-results/real-acceptance/` (SSE, request bodies, screenshots, `runtime/runtime.db`).

## 1. Result by scenario

| Scenario | Verdict | Evidence |
| --- | --- | --- |
| **A. six-capability end-to-end** | ❌ **FAIL** | The request correctly carried `attachment_ids:["att_ded03c4f…"]` and the turn completed, but (i) the research run **failed** and (ii) the message-level binding never persisted. See D1/D2. |
| **B. multimodal material research** | ✅ PASS | Vision read the screenshot (`击破特攻 62.5%`, `光锥：记忆中的模样（叠影 1）`) and the PDF text was quoted verbatim with source identity (`+37.3%` traces, `8% (S1) → 16% (S5)`). Values match ground truth. |
| **C. insufficient-evidence honesty** | ✅ PASS | Answered "联网研究失败，本回答未使用联网来源"; refused to fabricate a version-99 number and named the absence of sources. |

## 2. Defects found (diagnosed, not fixed)

### D1 — message-level binding is never persisted on the production path
- **Symptom**: `chat_turns.attachment_refs` is `[]` for all three turns, although `/chat/stream` carried `attachment_ids` and every attachment was `ready`.
- **Root cause**: the production service `ExternalDataPolicyChatService` creates its own `ChatTurn` (`src/application/policy_chat_service.py:353`) **without** `attachment_refs`. Only `src/application/chat_service.py` was updated for A-protocol.
- **Impact**: the new message-level material never reaches `research_context.attachments` (all runs show `attachments 0`); multimodal input therefore still works only through the pre-existing session-scoped retrieval path.
- **Scope**: one call site; the offline tests passed because they exercise `ChatService`, not the policy service.

### D2 — the real model's response aborts deep research instead of degrading
- **Symptom**: run `web_lookup_c7ea6a019` → `status=failed`, `stop_reason=chat_tool_loop_failed`,
  `error="SemanticRecovery blocked: ValueError: decision_fields"`.
- **Root cause**: `src/web/semantic_recovery.py:126` raises `ValueError("decision_fields")` when the
  provider's decision payload lacks the required fields; the run treats it as terminal failure.
- **Impact**: scenario A (and any real deep-research turn whose first decision payload is off-spec)
  produces a 52-character "no usable text" answer instead of a degraded-but-usable research turn.
- **Note**: this is exactly the kind of real-provider behaviour the offline scripted tests cannot produce.

## 3. Budget actually used

| Resource | Cap | Used |
| --- | --- | --- |
| Searches | 20 | **3** (1 per run; all returned candidates only) |
| Web reads | 30 | **0** (no candidate was promoted to a read) |
| Vision calls | 2 | **2** |
| Model calls | 24 | not precisely instrumented — no per-call ledger exists in the app (see `PRECHECK.md` §3); observed turns: 3 (A/B/C) plus one failed research run |
| Wall time | 300 s per scenario | A ≈ 2.5 min, B ≈ 1.5 min, C ≈ 1.5 min (suite total 5.5 min) |

No spend anomaly observed; this does **not** constitute a verified hard cap.

## 4. What the contract says now

- The real-model acceptance gate is **not passed**: A fails on two genuine defects.
- Per the frozen rules, failures are diagnosed narrowly and **not** tuned in the same round.
- B and C passing is real evidence for multimodal reading (vision + PDF) and evidence-honesty,
  but it does **not** unlock the PR/merge gate.
- The PR/merge gate stays closed until a corrected candidate re-runs A/B/C and all three pass.

## 5. Recommended next slice (needs operator approval — feature/bugfix work)

1. D1: pass `attachment_refs` into the `ChatTurn` created by `ExternalDataPolicyChatService`
   (mirror the `chat_service` change) and add a regression test on the **policy** path.
2. D2: make `semantic_recovery` degrade (bounded reason + partial research) instead of aborting the
   run when `decision_fields` are missing; keep the failure visible in the run record.
3. Re-run A/B/C once after both fixes, on the new exact head.

## 6. Fix status (2026-10-15, approved bounded bugfix)

| Item | Status | Change |
| --- | --- | --- |
| **D1** | ✅ fixed | `ExternalDataPolicyChatService.start_turn` now persists `attachment_refs` on the `ChatTurn` (the production path that was missed). |
| **R0** | ✅ fixed | `deep_requested` is forwarded from the chat services (`context_mode`/`performance_mode == "deep"`) and `PersistentWebToolAgent.resolve` gives an explicit deep selection a **real Deep run identity**, ahead of the heuristic/semantic default. |
| **D2** | ✅ fixed (controlled) | A malformed decision payload now degrades to the deterministic planning/reading chain **only** for a turn the router already authorised as external research, and **only** for payload-shape reasons (`decision_fields` / `decision_binding` / `query_binding`). Cancel, permission and security-validation failures still block, never guess a subject, and the original reason is recorded in `research_semantic_fallback.detail`. |

Regression: `tests/test_d1_r0_d2_fixes.py` exercises the **production** policy service and the
persistent agent (D1 policy path, R0 deep identity, D2 degrade + still-blocks). Adjacent impact set
green (131 passed, 1 skipped), `ruff` clean, `mypy` baseline NEW=0.

**A’s original cause is now removed, but the gate is still open**: 0 real web reads happened in the
failed round, so a re-run must also show real reading, source reuse, steering execution and a new
computation — not merely “no error”. A new round needs a fresh provider/budget confirmation
(§ PRECHECK.md; the ¥10 hard cap remains unverified).

## 7. Round 2 (after the D1/R0/D2 fixes and the spend cap) — 2026-10-15

Executed head: `a1112861` (spend cap live-verified at zero cost before the round).
Outcome: **A FAILED, B PASS, C PASS** — and the round surfaced the environment blocker.

| Surface | Round-2 evidence |
| --- | --- |
| SQLite | **D1 verified end-to-end**: A's turn carries `attachment_refs` (screenshot), B's carries screenshot + PDF, C's is empty; the runs' `research_context.attachments` are now 1 / 2 / 0 (previously all 0). |
| HTTP/SSE | A reached a **real Deep run** (`round 1/4` steps, attachment + planning + round) — **R0 verified**. |
| Search trace | 1 query per run; all three runs ended `stop_reason=source_reading_failed` with **0 reads**. |
| Computation | 0 computations (nothing was read, so no compute decision produced a result). |

### 7.1 Root cause of "0 real reads" — environment, not code

Every candidate read was rejected as `unsafe_or_empty_url`. Traced to the fail-closed reader:

```
resolve_public_ips('example.com')   -> ValueError('unsafe_target')
getaddrinfo('example.com')          -> 2606:4700:10::6814:179a (global),
                                       2606:4700:10::ac42:93f3 (global),
                                       198.18.0.110  (NOT global)
```

This host's DNS (TUN/fake-IP proxy) appends a `198.18.0.0/15` fake-IP next to the real answers, and
`src/web/safe_http.py` deliberately requires **every** resolved address to be global. The reader is
behaving as specified; the environment is incompatible with it. Consequently **no real page can be
read on this machine**, so A cannot pass regardless of D1/R0/D2.

### 7.2 Fix applied (configuration only, no code change)

`SAFE_HTTP_DOH_URL=https://dns.google/resolve` in the local (gitignored) `.env` — the supported DoH
escape hatch that resolves the real public IPs the transport will pin. Verified through the
production path:

```
resolve_public_ips('example.com')  -> ['104.20.23.154', '172.66.147.243']   host_resolves_public=True
_is_fetchable_article_url('https://baike.baidu.com/item/x') -> True
```

The cap stayed enforced during the round (`LLM_SPEND_CAP_CNY=10`; no spend-stop was hit).

**Status: A/B/C has not passed.** A corrected round (real reading, evidence reuse, mid-run steering,
new computation, same run identity) is required — and it is a **paid** round, so it needs the
operator's go-ahead beyond the one already used.

## 8. Round 3 (DoH configured; authorised corrected round) — 2026-10-15

Executed head: `73470267`. Zero-cost pre-flight first: `https://dns.google/resolve` DoH resolves
real public IPs and `safe_fetch_result()` returned real bodies (`example.com` 200/577 B,
`en.wikipedia.org/wiki/Honkai:_Star_Rail` 200/452 KB).

Playwright result: **3 passed (8.3 min)**. Substantive check, however, is **A = FAIL**:

| A condition | Result | Evidence |
| --- | --- | --- |
| 1. real page text read, sources traceable | ✅ | 5 successful read steps; `selected_sources` populated; run `stop_reason=sources_partially_read` |
| 2. original run not restarted | ✅ | one run per turn; supplements land on the **same** run |
| 2b. supplement actually executed | ❌ | steering entry `incorporated_in_round=2` but **`executed_in_round=None`** — accepted, never carried out |
| 3. evidence reuse + necessary re-check | ◐ | existing sources retained; **no re-check** happened (the steering task never searched) |
| 4. E2/S5 params trigger a new computation | ❌ | `deep.computations == []` — **no computation at all** |
| 5. chart/SQLite/SSE/search/computation consistent | n/a | not assessable without a computation |

B and C passed again (B: vision + PDF; C: honest refusal), but per the frozen rules they do **not**
substitute for A.

### 8.1 Root causes (production wiring gaps, not model behaviour)

**P1 — production Deep has no planner.** `get_web_lookup_service()` builds
`ClaimEngineDispatchWebLookupService(repository)` with `planner=None`. Therefore:
* `_deep_planner_plan` returns `None` → `_deep_default_plan` uses the **raw user sentence** as the
  query; DuckDuckGo returned unrelated pages (dictionary/OCS pages), so nothing relevant could be
  admitted;
* the `revise`-based **compute decision is unreachable** → `deep["computations"]` can never be
  populated on the Deep path, i.e. capability 6 (autonomous calculation + chart) is dead in
  production regardless of the compute tools being registered.

**P2 — no incremental steering budget policy is configured.** The round loop only extends past
`max_rounds` when an `incremental_budget` ledger exists; with no policy the run cannot gain a round,
so a mid-run supplement is recorded as incorporated (`inc=2`) but never executed (`exec=None`) —
capability 4's "keep researching and re-check" does not happen in production.

### 8.2 Budget used in this round

3 queries / 24 source reads / 2 vision calls; `LLM_SPEND_CAP_CNY=10` was active for the whole run
(one process, shared ledger) and **never tripped** (no `spend cap reached`, 0 error events). The cap
did not bind: worst-case reservation for the observed call count stayed well under ¥10.

**Verdict: A/B/C not passed; merge gate stays closed.** No re-run, no tuning. Fixing P1/P2 is
functional work and needs the operator's decision.

## 9. P1 / P1b / P2 fix status (2026-10-15, approved bounded slice)

| Item | Status | Change |
| --- | --- | --- |
| **P1** real Deep planner | ✅ wired | `src/web/research/deep_planner.py::ModelDeepPlanner` (model-driven `plan`/`revise`, strict JSON validation, bounded counts; **no hardcoded answers**), injected by the production factory `get_web_lookup_service()` (`WEB_DEEP_MODEL_PLANNER=0` opts out). All calls go through `src.llm_client`, so the ¥10 pre-request cap, timeouts and bounded retries apply. |
| **P1b** supplement context | ✅ wired | `revise` now receives a bounded, identity-only `context` (accepted steering incl. kind/rounds/attachment ids, attachment identity, existing computation versions). The call is signature-aware, so planners without `context` keep working. |
| **P2** incremental budget | ✅ configured | Explicit `initial/per_goal/limits` supplied **only** by the acceptance harness (kept out of `.env` so it cannot leak into the test suite); `incremental_budget.py` defaults are unchanged (no “unlimited by default”). |
| **Execution-state fix** | ✅ | A **recompute** supplement is marked `executed_in_round` only when its computation actually succeeds; the loop no longer exits on the model's `done` while an accepted supplement is still unexecuted; unexecuted work is reported (warning + `partial`), never as success. |

Offline production-path regression `tests/test_deep_planner_production.py` (production factory +
simulated model provider + scripted gateway + **real SQLite**): model planning produced focused
queries, real reads happened, the mid-run E1/S1 → E2/S5 supplement was accepted **and executed**,
the recompute produced a new computation (`superseded` + `succeeded`, rows from the new parameters),
the budget ledger recorded idempotent grants, and receipt/SQLite/narration agreed.
Negative controls green: malformed model output (honest, no fabrication), no compute proposed
(no computation), exhausted budget (supplement reported unexecuted), duplicate steering (idempotent).

Adjacent impact set: 260 passed / 1 skipped; `ruff` clean; `mypy` baseline NEW=0. Test hermeticity
added: a deployment `.env` can no longer change test behaviour (`WEB_RESEARCH_STEERING_BUDGET_POLICY`
and `WEB_DEEP_MODEL_PLANNER` are cleared per test).

**Still required**: a paid A/B/C round on the new head. Not authorised yet.

## 10. Round 4 (P1/P1b/P2 wired) — 2026-10-15

Executed head: `01e154c2`. Playwright: **3 passed (9.3 min)**. Substantive check: **A = FAIL again**,
but for a different and now precisely identified reason, and the P1/P1b/P2 fixes are all *functioning*.

### 10.1 What the fixes delivered (verified in the real run)

| Fix | Real-run evidence |
| --- | --- |
| P1 real planner | `planning（3 个子问题）`; the searches used **model-produced focused queries** (`流萤 击破特攻 伤害 对比 配置`, `流萤 机制 伤害 加成`) — not the raw user sentence |
| P1b supplement context | round 2 started with `（含用户转向）`; the planner produced follow-up sub-questions derived from the E2/S5 correction |
| P2 budget ledger | grants recorded and idempotent (`steering_09cf51d1… → recompute_…`), consumed counters persistent |
| honest execution state | the run recorded `steering: incorporated_in_round=2, executed_in_round=None` and logged `本轮时间预算不足，新增要求尚未执行；可排队到下一轮` — no fabricated success |

### 10.2 Root cause of the A failure: the acceptance policy's wall budget is too small

`deep.incremental_budget.consumed.wall_seconds = 198.8` against an authorised ceiling of
`initial 150 + grant 45 = 195`. Every search then short-circuited with
`检索预算不足，这个研究目标未完成。`, the run ended `partial`, and the supplement could not be executed.

Real network reading is simply slower than the wall budget I allocated in the acceptance policy
(reads alone accounted for ~3 minutes of the scenario). This is a **configuration sizing error in the
acceptance policy I wrote**, inside the frozen "300 s per scenario" cap — not a product defect and
not model tuning. Searches (2/20) and reads (6/30) were nowhere near their caps.

### 10.3 Verdict

* A: **FAIL** — not for missing capability, but because the supplement was starved of wall budget.
* B/C: passed (unchanged).
* The only required change is to re-size the acceptance policy's wall axis (e.g. initial 240 /
  per_goal 60 / limit 300) so it fits the frozen 300 s scenario cap.

**Stopped here**: per the frozen rules an A failure means keep the evidence and diagnose narrowly —
no automatic re-run and no tuning. The re-sizing decision belongs to the operator.

## 11. Zero-cost timing audit (before any further paid round) — 2026-10-15

Source: the saved round-4 run `web_lookup_c3750a1c…` (head `01e154c2`), read from SQLite; plus two
new offline regressions. **No model or paid call was made.**

### 11.1 Where the 198.8 s actually went

| offset | Δ | step |
| --- | --- | --- |
| 14:36:50 | — | attachment material ready |
| 14:36:55 | **+5.2 s** | model planning (3 sub-questions) |
| 14:38:09 | **+73.5 s** | read #1 succeeded |
| 14:38:41 | **+32.5 s** | read #2 succeeded |
| 14:39:34 | **+52.4 s** | search/assess + failed reads, then the budget stop |
| 14:39:34 | +0.0 s | gap analysis |
| 14:39:38 | **+4.5 s** | model `revise` (3 new sub-questions) |
| 14:39:38 | +0.0 s | **steering accepted (168 s into the run)** |
| 14:39:38 | +0.0 s | round 2 starts (with the user turn) |
| 14:40:06 | **+27.5 s** | read (round 2) |
| 14:40:09 | +3.1 s | `revise`, then *time budget insufficient — supplement not executed* |

| bucket | seconds | share |
| --- | --- | --- |
| successful page reads (3) | ≈133.5 | **67 %** |
| search + assess + 3 failed reads (`all_backends_failed` ×2, `unsafe_or_empty_url` ×1) | ≈52.4 | 26 % |
| all model calls (plan + revise ×2) | ≈12.8 | **6 %** |

Findings:
* **Model time is negligible (6 %); network reading dominates.** Raising the cap without fixing read
  cost will just move the wall.
* **≈44 s per successful read** — that is what makes a 300 s budget tight, not the number of rounds.
* The supplement arrived at **168 s**, i.e. *after* the initial 150 s had already been spent; the
  `min(per_goal, limits-initial)` formula then granted only 45 s.

### 11.2 Client timeout really does stop the paid work (verified, offline)

`tests/test_stream_disconnect_cancels_research.py` drives the real endpoint with a disconnected
request and asserts `cancel_owned_by_turn(<turn>)` is called during preparation (polled every 50 ms)
and no `done` event follows; a connected client never triggers it. **Boundary:** the branch requires
the request to carry `turn_id` — the frontend always generates one (confirmed in the captured body),
so a Playwright timeout does cancel the run. A brand-new turn with no `turn_id` keeps the older
no-cancel semantics.

### 11.3 Time-stop safety regression (offline)

`tests/test_deep_time_boundary.py`: a scripted slow gateway with a tiny wall/read budget shows the
run **returns instead of hanging**, **respects the authorized reads**, **keeps its plan/steps for a
resume**, records an accepted-but-unexecuted supplement **honestly**, and never fabricates a
computation.

### 11.4 Decision input (not a change)

* Do **not** silently relax the frozen 300 s.
* Candidate allocation (pending the operator): `initial 210 / per_goal 60 / limits 300` gives an
  actual grant of `min(60, 300-210)=60` (total 270) — unlike the earlier `240/60/270` suggestion,
  which could only grant 30.
* If a future round still exceeds 300 s, the choice is between (a) raising research throughput
  (source priority, per-page read timeout, evidence reuse) and (b) making Deep a **resumable,
  non-blocking task** with its own acceptance standard — not a larger number.
