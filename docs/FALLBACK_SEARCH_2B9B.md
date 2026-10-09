# B-Search-2B9-B — cross-topic source discovery (Phase 1 diagnosis)

## 2B9-F — DNS latency + strict DoH semantics + follow deadline (PARTIAL)
- **DoH cache**: per `(DoH endpoint, host)`, short TTL (`SAFE_HTTP_DOH_CACHE_TTL`, default 120s),
  cap 128, cleared on overflow; **only fully-validated public IPs are cached** (failures/unsafe
  answers never cached). `get_dns_stats()` exposes queries / cache_hits / doh_failures.
- **A/AAAA strictness**: a failed DoH request for EITHER type now raises `dns_failed` — one type's
  success cannot mask the other's failure.
- **`follow`** now passes the shared absolute `deadline`.
- **Prompt**: prefer reading a specific article URL a search already returned; only `follow` a hub
  page when no suitable specific article was returned (generic; no hardcoded site).
- Tests: `tests/test_safe_http_doh.py` (+ cache-hit, one-type-failure) → **49 PASS**; ruff + mypy clean.

**Real validation** (`SEARXNG_ENGINES=google` + `SAFE_HTTP_DOH_URL=https://dns.google/resolve`).
Effective engine = **searxng (google)** for all tasks (Bing not used when searxng is non-empty):
| task | elapsed | reads | outcome |
|---|---|---|---|
| factorio | 36.2s | none | recall ok, but model followed wiki home → **no read** |
| go_rules | 60.2s | cosumi (fail), **weiqigo home 399 chars** | read a **home page**, not the rule article |
| python_reference | 35.2s | final post 4379 chars ✅ | finished |

**Verdict PARTIAL.** Time now **< 90s** for all (cache fixed the 129s) and safety regressions pass;
Python reads. But **Factorio/Go still do not autonomously read a *topical* specific article** (Go read
a 399-char home; Factorio read nothing) — the specific URLs were returned by search but not chosen.
`assess_body` false positive stays UNQUALIFIED.

## 2B9-E — trusted DoH resolver (check == connect), no CIDR whitelist
`SAFE_HTTP_DOH_URL` (e.g. `https://dns.google/resolve`): `resolve_public_ips()` now resolves via DoH,
**fails closed** on DoH failure, and rejects any non-global answer (so fake-IP `198.18.0.0/15` is
**never whitelisted**). `host_resolves_public()` delegates to it; `article_fetcher._check_dns_target_safe`
delegates to the same — so all three check sites and the pinned connection (`http_get_raw`, SNI=host)
use the **same verified public IPs**; each redirect re-resolves via `safe_fetch`. Tests:
`tests/test_safe_http_doh.py` (real IPs accepted; fake-IP rejected; mixed rejected; DoH failure
fails closed); suite **47 PASS**; ruff + mypy baseline clean.

**Real validation** (`SAFE_HTTP_DOH_URL=https://dns.google/resolve`, `SEARXNG_ENGINES=google`):
- **Python: read SUCCEEDED** → `blog.python.org/2026/10/python-3150-final-is-here/` (the fake-IP block
  is lifted for a real public host). ✅
- Factorio / Go: recall now returns specifics, but the model chose `follow` on the wiki/portal home and
  **ran out of rounds** → no specific article read. DoH also adds latency (elapsed 62s/129s vs ~10s).

**Verdict PARTIAL.** The DNS/SSRF conflict is fixed and demonstrated (a real read now succeeds); the
Factorio/Go *arrival* is still not demonstrated (model path + latency), and `assess_body` keeps its
known false positive (UNQUALIFIED). Next: reduce DoH cost (cache per run) and steer the model to read a
returned specific URL rather than following a hub home.

## 2B9-D update — SearXNG actually fixable; new blocker = fake-IP DNS vs SSRF guard
**SearXNG root cause fully isolated (was NOT the network):** `engines=google` → 20 results;
adding `language=zh-CN` → **0**; `language=en` → 20. The adapter **hardcoded `language="zh-CN"`**
(`search_searxng` never passed a language), which zeroed Google. Fix: language is now env-driven
(`SEARXNG_LANGUAGE`, default `auto` → param omitted) and `SEARXNG_ENGINES` can pin working engines.
With `SEARXNG_ENGINES=google` the adapter returns **specific** pages: Factorio →
`factorio.com/blog/post/fff-395`, reddit `train_interrupts_how`; Go → `zh.wikipedia.org/劫_(围棋)`,
`baike.baidu.com/打劫`; Python → `python.org/downloads/release/python-3150/`,
`docs.python.org/3/whatsnew/3.15.html`. (Default engine set brave/ddg/startpage/wikipedia is
CAPTCHA/timeout; the earlier "egress blocked" host probe was transient — host and container both GET
google/wikipedia 200 now.)

**New blocker (precise):** real hosts resolve to a **fake-IP `198.18.0.0/15`** (transparent proxy)
plus bogus `2001::1` → `host_resolves_public()` returns **False for every real host** (wiki.factorio.com
`198.18.0.71`, zh.wikipedia.org `198.18.0.68`, python.org `198.18.0.101`, reddit `198.18.0.93`) →
`read_page`/`follow` are rejected `blocked_unsafe_target`, and model-guessed URLs are
`pending_url_confirmation`. So arrival is now blocked at the **SSRF guard vs fake-IP DNS** layer, not
recall.

**Tests:** `tests/test_searxng_source.py` (language/engines URL) + `tests/test_tavily_source.py`;
an autouse fixture makes the agent tests DNS-independent (this environment's fake-IP was breaking
`example.org`). Focused suite green.

**Verdict PARTIAL.** Recall is now fixed at the adapter; the remaining blocker is safety-vs-fake-IP.
**Next:** decide how the SSRF guard should treat the local proxy's fake-IP range (e.g. resolve via a
trusted resolver, or allow a configured loopback/proxy CIDR) — a safety-sensitive change, not done here.

## 2B9-D — real search source: SearXNG root cause + opt-in Tavily (PARTIAL, key needed)
**Phase 1 — SearXNG root cause (exact):** `SEARXNG_BASE_URL=http://127.0.0.1:8080`, enabled,
loopback allowed. `GET /search?format=json` → **HTTP 200, `application/json`, valid JSON** with
`n_results: 0` and **`unresponsive_engines`**: `brave: timeout`, `duckduckgo: CAPTCHA`,
`google cse: HTTP connection error`, `startpage: Suspended: CAPTCHA`. → **the service and JSON output
work; every upstream engine it proxies is blocked/CAPTCHA'd.** Not the adapter, not the parsers —
an external engine problem on the local instance.

**Phase 2 — opt-in Tavily provider:** `src/news/search_sources/tavily_source.py` (OFF by default;
key only from `TAVILY_API_KEY`; `POST https://api.tavily.com/search` with `search_depth=basic`,
`max_results≤5`, `include_answer=false`, `include_raw_content=false` — the existing Reader still
fetches bodies; call count and last error are explicitly countable; a missing key fails
diagnosably as `missing_api_key` and never alters Agent budgets). Wired into `_search_single` as a
provider tried before Bing. Unit tests: 4 new (disabled-without-key, disabled-unless-flag, parse +
call-count, failure diagnosable); suite **39 PASS**; ruff + mypy baseline clean.

**Phase 3 — real validation: BLOCKED.** No `TAVILY_API_KEY` is present (the contract requires the
user to create it; it must not be committed), so the new provider cannot be exercised yet.
Factorio / Go specific-article arrival therefore remains **not achieved**.

**Verdict PARTIAL.** Root cause is fixed as a *fact*; the new recall source is implemented but
**unvalidated pending the API key**. Supply `TAVILY_API_KEY` (and set `WEB_ENABLE_TAVILY=true`)
to run the Factorio/Go/Python comparison.

## 2B9-C — per-provider recall diagnosis (external blockage confirmed; PARTIAL)
`tools/eval_2b9c_providers.py`, raw `model-driven-search-2b9c/providers.json`.

| query | SearXNG | Bing RSS | DuckDuckGo |
|---|---|---|---|
| Factorio (en) | **0** | 5 — `factorio.com/`, `wiki Main_Page/zh`, `ali213`, `download`, `3dmgame` | timeout (`URLError`) |
| 围棋 提子/打劫 | **0** | 5 — `weiqigo`,`19x19`,`cosumi`,`metool`,`go-master` | timeout |
| Python 3.15.0 | **0** | 5 — `python.org/`,`/downloads`,`pythonlang.cn`,`runoob`,`liaoxuefeng` | timeout |
| Factorio (zh) | **0** | 5 — **different**: `zhidao.baidu`, `zhihu` | timeout |

**Findings (reproducible):**
- `searxng_enabled()==True` but **SearXNG returns 0 for every query** — unusable.
- The generic homepages come from **Bing RSS** (the exact duplicate set), **not** SearXNG.
- **DuckDuckGo times out** for every query.
- Results **do** depend on the query (en vs zh differ) → the earlier "identical Top-5" came from the
  agent issuing near-duplicate queries, not a query-insensitive backend.
- Code audit: `_search_single` is an **early-return cascade** (SearXNG → Bing → DDG; later providers
  skipped once one is non-empty). Here it did **not** cause the generic set: SearXNG was empty, Bing
  was the first non-empty — so the cascade is **not** the confirmed defect.

**Conclusion:** **no available provider surfaces the specific Factorio mechanism / Go rules article**
→ **external recall blockage**, recorded with facts. Per contract, **no code fix is manufactured**
(no hardcoded URLs, no prompt tricks).

**`follow` narrow gaps (recorded, not fixed — recall is the mainline):** (1) its `safe_fetch_result`
call does **not** pass the shared absolute `deadline`; (2) HTML encoding / post-redirect final-URL
handling is not fully qualified; (3) link selection stops at the **first 5 in document order**
without relevance ranking, so the earlier result only proves "the first 5 were nav links", not "the
page has no link to the article".

**Also:** log `search×4` = four model **search actions**; with `max_searches=3` the 4th was a
**quota rejection**, not a provider request (provider attempts are counted separately).

## Phase 2+3 — bounded `follow` implemented; real arrival NOT achieved (PARTIAL)
`follow` was added (confirmed page only; raw HTML via `safe_fetch_result`; true `<a href>`
extraction; same-origin only; ≤5 links; relative-URL resolved; dedup; provenance recorded; costs
1 round + 1 read; the model must still `read_page`). Unit test passes (35 total). Real validation
(`tools/eval_2b9b_validate.py`, raw `validate.json`):

| task | tools | follow links | specific article read |
|---|---|---|---|
| factorio | search×4, read_page, **follow** | `wiki.factorio.com/`, `Main_Page/cs`, `/da`, `/de`, `Main_Page` — **all language/nav variants** | **none** |
| go_rules | search×4, read_page×2 | (no follow) | **none** |
| python_reference | feed, read_page, finish | — | correct final post ✅ |

**Decisive finding (as the contract warned):** the Factorio **wiki home is a language portal** — its
same-origin links are language variants/navigation, **not** the train-interrupt article. So `follow`
did not create the missing arrival; search still never returns the specific entry, and the hub page
itself does not lead to it in one hop. **Remember `gateway.read` returns extracted text without
`href`; we used real HTML, yet there was simply no target link on the home page.**

## Verdict
**PARTIAL.** `follow` is implemented and safe-tested, but **Factorio/Go each still read 0 specific
relevant pages** → no arrival PASS. Failing layer = **real search recall quality** + hub-page link
structure (home-as-portal), not the agent's tool set. Next: address genuine search recall
(provider mix / query specificity / language-vs-content pages) rather than adding more tools.


Real `deepseek-flash`, live, `tools/eval_2b9b_diag.py` (wraps `search_exact`/`read`). Raw: `diag.json`.

## Where "arrival" fails (exact)
### Factorio (train interrupts vs fixed schedule) — **RECALL**
- q1 `Factorio 2.0 train interrupts vs schedules when not to use` → Top-5 all generic:
  `factorio.com/`, `wiki.factorio.com/Main_Page/zh`, `ali213.net/zt/factorio/`, `factorio.com/download`,
  `3dmgame.com/games/factorio/` — **no mechanism article**.
- q2 (Chinese) → **identical Top-5**.
- q3 `site:wiki.factorio.com train interrupts` → **0 results**.
- Read: `wiki.factorio.com/Main_Page/zh` (a homepage), read OK but it is a landing page.
- → the specific entry **never entered Top-5**; the model cannot choose what was never returned.

### Go rules (提子 / 打劫) — **RECALL + READER**
- 3 queries (incl. one naming 维基百科) → Top-5 **identical every time**:
  `weiqigo.com`, `19x19.com`, `cosumi.net`, `metool.online/zh/games/go/`, `go-master.cn` — all
  server/homepages, **no rule article**.
- Read of `metool.online/zh/games/go/` → **`security_refused:response_too_large`** (exact reader
  branch + reason).

### Python 3.15.0 (control) — passes via feed seed; 1 read, `finished` ✅

## Diagnosis
- **Dominant failure = recall**: `search_exact` returns homepages/listicles; `site:` returns nothing.
  The backend also returned the **same Top-5 across different queries** → the search service looks
  query-insensitive/degraded right now (recorded as a real failure, not faked).
- **Secondary = reader**: one oversized page refused with `response_too_large`.
- The model's query refinement (mechanism terms, `site:`) did not lift specificity.

## Proposed generic fix (NOT hardcoded)
Bounded, evidence-preserving **in-page link following**: from a discovered relevant hub page
(e.g. a wiki), follow a small number of same-site links toward a specific article, reusing the
existing URL-safety + admission gate, with the link source recorded; and prefer specific entries
over homepages. No `site:`-only reliance; no per-topic rules.

## Verdict
**PARTIAL** — Phase 1 (diagnosis with exact locations) done; Phase 2 (generic discovery improvement)
and Phase 3 (paired real validation) **not done**. Do not claim arrival PASS.
