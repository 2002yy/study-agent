# Provider & Cost Pre-check — 2026-10-15

> **Verdict: STOP at `NOT_YET_RUN`.** The A/B/C acceptance was **not** run.
> No model, vision or search call was made. No top-up, no provider switch.

Executing head (would-be): `06e96286d98d76c38018ff972460f42528479723`
(`codex/conversation-continuous-p0p1`, 20 commits ahead of `335fc9b7`).

The frozen scoring criteria in `scenarios.json` / `README.md` were **not**
changed; only the candidate pointer was advanced from `6050fa3a` to
`06e96286` (this pre-check commit) so the run cannot target a stale head.

## 1. Findings

| Required item | Contract | Actual (evidence) | Verdict |
| --- | --- | --- | --- |
| Paid provider | DeepSeek official, only paid provider | `LLM_PROVIDER_PROFILE` unset → resolved profile **`openai`** (`_normalize_provider_profile` default) | ❌ |
| Model availability | flash model configured | `MODEL_FLASH_NAME` / `DEEPSEEK_MODEL_FLASH_NAME` unset → `get_provider_settings()` raises `RuntimeError: OPENAI_API_KEY is missing.` | ❌ (app cannot call any model) |
| API key | usable DeepSeek key | `DEEPSEEK_API_KEY` present (len 35), authenticates against the provider — **but is unused** under the active `openai` profile | ◐ |
| Vision switch | `attachment_vision_enabled=true` | `config/frontend_settings.yaml` absent → default **`False`** (vision OFF) | ❌ |
| Account balance | available | `https://api.deepseek.com/user/balance` → `is_available: true`, **CNY 17.40** (granted 6.44 + topped-up 10.96) | ✅ |
| Hard ¥10 cap | verifiable **before** the request | No program-side spend cap exists anywhere in `src/`; provider-side balance **¥17.40 > ¥10**, so it does not bound spend to ¥10 | ❌ |

## 2. Evidence (reproducible, zero model calls)

```
# provider profile / settings (no secrets printed)
LLM_PROVIDER_PROFILE = unset            -> resolved profile: openai
OPENAI_API_KEY        = unset           -> get_provider_settings() raises
MODEL_FLASH_NAME      = unset              "OPENAI_API_KEY is missing."
DEEPSEEK_API_KEY      = SET (len 35)

# balance (free endpoint, key never echoed)
GET https://api.deepseek.com/user/balance
{"is_available": true, "balance_infos": [{"currency":"CNY","total_balance":"17.40",
 "granted_balance":"6.44","topped_up_balance":"10.96"}]}
```

## 3. Why this blocks the run

The contract states: if the program cannot reliably block an over-budget call
**before** it is made, a provider-side balance limit or another verifiable hard
limit must provide the cap — post-hoc accounting is not acceptable.

- Program side: **no** spend/model-call cap exists (nothing to enable).
- Provider side: the prepaid balance (¥17.40) exceeds the approved ¥10, so it is
  not a ¥10 hard limit.
- Therefore a verifiable ¥10 hard cap is **not** available, and the run is
  stopped rather than executed under an unverifiable budget.

## 4. What the operator must decide or provide

1. **Provider profile** — set the DeepSeek profile and model IDs (env only, no
   code change). Exact names the code reads:
   `LLM_PROVIDER_PROFILE=deepseek`, `DEEPSEEK_MODEL_FLASH_NAME`, `DEEPSEEK_MODEL_PRO_NAME`.
2. **Vision** — per the approved plan, `DEEPSEEK_MODEL_VISION_NAME=deepseek-flash`
   (env only) **and** enable the frontend switch
   (`config/frontend_settings.yaml` → `attachment_vision_enabled: true`).
3. **The ¥10 hard cap** — choose one:
   - (a) hold the DeepSeek balance at ≤ ¥10 (not by topping up — topping up is forbidden);
   - (b) accept the current **¥17.40** as the effective hard cap (exceeds the approved ¥10);
   - (c) authorise a program-side pre-request model-call/spend cap — currently a
     feature change, which the "stop feature development" decision forbids.

Until (1), (2) and (3) are satisfied, this pack stays `NOT_YET_RUN`.
