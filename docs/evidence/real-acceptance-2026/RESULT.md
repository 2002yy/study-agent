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

1. D1: pass `attachment_refs` into the `ChatTurn` created by `ExternalDataChataService`
   (mirror the `chat_service` change) and add a regression test on the **policy** path.
2. D2: make `semantic_recovery` degrade (bounded reason + partial research) instead of aborting the
   run when `decision_fields` are missing; keep the failure visible in the run record.
3. Re-run A/B/C once after both fixes, on the new exact head.
