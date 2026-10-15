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
| Paid provider | DeepSeek official, only paid provider | `LLM_PROVIDER_PROFILE=deepseek` (local `.env`, gitignored) → resolved profile **`deepseek`**, base `https://api.deepseek.com/v1` | ✅ (2026-10-15 updated) |
| Model availability | flash model configured | `DEEPSEEK_MODEL_FLASH_NAME=deepseek-flash`, `DEEPSEEK_MODEL_PRO_NAME=deepseek-v4-pro`; `get_provider_settings()` resolves cleanly | ✅ (2026-10-15 updated) |
| API key | usable DeepSeek key | `DEEPSEEK_API_KEY` present (len 35) from the machine env, authenticates against the provider; `settings.api_key` populated | ✅ |
| Vision switch | `attachment_vision_enabled=true` | `config/frontend_settings.yaml` (gitignored) sets it **true**; `vision_model_name()` = `deepseek-flash` | ✅ (2026-10-15 updated) |
| Account balance | available | `https://api.deepseek.com/user/balance` → `is_available: true`, **CNY 17.40** (granted 6.44 + topped-up 10.96) | ✅ |
| Hard ¥10 cap | verifiable **before** the request | No program-side spend cap exists anywhere in `src/`; provider-side balance **¥17.40 > ¥10**, so it does not bound spend to ¥10 | ❌ **OPEN — operator ruling required** |

### 1.1 Unified-DeepSeek configuration applied (local, gitignored)

`.env` (from `.env.example` naming; key intentionally absent, it comes from the machine env):

```
LLM_PROVIDER_PROFILE=deepseek
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_MODEL_FLASH_NAME=deepseek-flash
DEEPSEEK_MODEL_PRO_NAME=deepseek-v4-pro
DEEPSEEK_MODEL_VISION_NAME=deepseek-flash   # retired vision name routes here; pinned explicitly
DEFAULT_MODEL_PROFILE=flash
```

`config/frontend_settings.yaml`: `attachment_vision_enabled: true`.

Verified by resolving the real settings objects (no network, no model call):
`profile=deepseek base=https://api.deepseek.com/v1 flash=deepseek-flash pro=deepseek-v4-pro
key_present=True vision_switch=True vision_model=deepseek-flash`.

Both files are `.gitignore`d, so the branch stays clean and neither config is committed.

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

1. ~~**Provider profile**~~ — **DONE (2026-10-15)**: unified to DeepSeek via the local,
   gitignored `.env` (see §1.1). No code change.
2. ~~**Vision**~~ — **DONE (2026-10-15)**: `DEEPSEEK_MODEL_VISION_NAME=deepseek-flash`
   plus `attachment_vision_enabled: true` in the local, gitignored frontend settings.
3. **The ¥10 hard cap — still open.** Choose one:
   - (a) hold the DeepSeek balance at ≤ ¥10 (not by topping up — topping up is forbidden);
   - (b) accept the current **¥17.40** as the effective hard cap (exceeds the approved ¥10);
   - (c) authorise a program-side pre-request model-call/spend cap — currently a
     feature change, which the "stop feature development" decision forbids.

Everything else is satisfied. Only item 3 keeps this pack at `NOT_YET_RUN`.
