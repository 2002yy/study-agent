# B-Search-2A — real-retrieval comparison: availability result

Read-only experiment slice. Base `ad050c5f`. No prompt/budget/gate change.
RP-1 NO-GO. Evidence: `reading-notebook-ui-evidence/model-driven-search-2a/`.

## SearXNG availability (the decisive finding)
- Docker up; `study-agent-searxng` container up; JSON API `http://127.0.0.1:8080`
  returns HTTP 200.
- **But its engines are unresponsive from this host**
  (`searxng_health.txt`):
  - `brave` — Suspended: too many requests
  - `duckduckgo` — timeout / CAPTCHA
  - `google cse` — HTTP connection error / Suspended
  - `startpage` — Suspended / CAPTCHA
  - only `wikipedia` answered (1 hit for `python`; 0 for Factorio/weather/中文).
- So SearXNG returns **0–1 results** for real queries.

## Experiment A (Bing RSS vs SearXNG, same frozen queries) — INCONCLUSIVE
`experiment_a.txt/json`. With `WEB_ENABLE_SEARXNG` toggled, both arms returned
**identical** top-5 lists, because SearXNG returned ~0 and the gateway fell back to
Bing RSS in both. **No provider contrast is measurable.**

## Experiment B (fixed pipeline vs tool agent, both SearXNG) — DEFERRED
"Both use SearXNG" is meaningless while SearXNG yields ~0: both arms still fall
back to Bing RSS, so the strategy comparison cannot be isolated. Deferred until the
engine path actually returns results.

## Conclusion (per the frozen decision table)
This is the case **"SearXNG 仍然没有具体文章 → 优先检查搜索服务配置、实际使用的搜索引擎和结果解析"**. The blocker is **upstream search-engine access from this host** (rate-limit / CAPTCHA / block), not the code, the query construction, or the agent loop.

Refines the earlier attribution: the provider was not simply "down"; its engines are
**blocked/suspended**, and the only working fallback (Bing RSS) returns generic
home/dictionary pages. So "provider most visible bottleneck" stands, but the
provider's *engine access*, not the SearXNG process, is the target.

## Not done / next
- Pending (requested, not implemented because experiments could not run): the agent
  **URL-confirmation rule** — allow reads only for URLs confirmed by a prior search
  result/trusted index; out-of-band (model-guessed) URLs are recorded
  `pending_url_confirmation` and not fetched.
- Next bounded steps:
  1. Inspect `infra/searxng/settings.yml` enabled engines + result parsing; find an
     engine that actually answers from this host (or confirm the host is
     engine-blocked).
  2. Only if no engine works, evaluate a documented third provider — not before.
  3. Then re-run Experiment A and B with the same frozen queries/quotas.
- Do **not** change agent prompts, task grading, budget or the Evidence Gate.

Gates: no production code changed; evidence archived under `model-driven-search-2a/`.
