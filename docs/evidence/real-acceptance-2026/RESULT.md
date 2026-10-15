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
