# DeepSeek independent Search/Fetch — disabled integration candidate

## Scope and official source

- Independent endpoints: `POST /v1/tools/search` and `POST /v1/tools/fetch` at
  `https://api.deepseek.com`. These do not call an LLM.
- Reference: https://api-docs.deepseek.com/zh-cn/guides/search/
- Published price on 2026-11-17: ¥5 / 1,000 successful searches and ¥5 /
  1,000 successful fetches. Recheck before any live experiment.
- `GeneralWebGateway` stays the sole production entrypoint. Ordinary
  `fallback` inserts DeepSeek after SearXNG **only when enabled**, and a new
  `deepseek_first` strategy is available for a controlled A/B run. `merge`,
  `ddg_first` and the existing browser/community routes are unaffected.
- Search only discovers candidates; results must pass the existing `web_read`
  evidence path. Fetch, when enabled, runs only after the existing article
  reader fails and before its shared read deadline expires.

## Safety and activation boundary

All four settings default to **false/zero**:

```dotenv
WEB_DEEPSEEK_SEARCH_ENABLED=false
WEB_DEEPSEEK_SEARCH_MAX_REQUESTS=0
WEB_DEEPSEEK_FETCH_ENABLED=false
WEB_DEEPSEEK_FETCH_MAX_REQUESTS=0
```

Each paid provider requires the existing `DEEPSEEK_API_KEY`, its enabled flag,
and a positive `_MAX_REQUESTS`. The caps are atomic per process and count
attempted requests, including failures. They are **not durable**, not shared
between workers, and reset on restart. They do not replace the experiment's
shared persistent cost ledger. **Do not turn these flags on for a live
multi-worker deployment until a shared durable spending cap and explicit
authorization have been established.**

An explicitly authorized test may select `WEB_SEARCH_STRATEGY=deepseek_first`.
This preference alone never activates billable requests. Outgoing requests
use a fixed HTTPS endpoint, and errors never include the API key or raw server
response. Candidate URLs and Fetch targets must pass public-HTTP URL checks;
downstream webpage reading retains its existing safety checks.

## Verification boundary and next test

- Offline tests: disabled/no-cap do not reach network; Search schema and
  response mapping; capped calls; HTTP 402 diagnostic without leaking details;
  empty/malformed results; private URL rejection; default fallback unchanged;
  new provider failure falls back to Bing RSS; Fetch only after a failed
  ordinary read, and only if enabled.
- No paid search, model, latency or coverage experiment was performed. There
  is no empirical claim that DeepSeek finds more Chinese community evidence.
- Next (separately authorized): fixed-query SearXNG / DeepSeek Search /
  authenticated-browser comparison, with successful *full-text reading*,
  distinct useful source contribution, latency, provider outcomes and actual
  billed request count measured independently. Only then change routing.
