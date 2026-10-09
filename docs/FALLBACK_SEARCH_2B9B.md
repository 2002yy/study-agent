# B-Search-2B9-B — cross-topic source discovery (Phase 1 diagnosis)

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
