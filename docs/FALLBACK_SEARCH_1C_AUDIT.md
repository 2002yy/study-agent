# B-Search-1C — offline zero-evidence attribution audit

Worktree `codex/model-driven-research-entry` @ `0f36aff1` (read-only). No model
calls, no budget change, no production edit, no gate change. RP-1 NO-GO.

Sources: `reading-notebook-ui-evidence/model-driven-search-1b/` and `-1/`
(energy/factory/history); raw extract in `model-driven-search-1c/audit.json|txt`.

## The key question
Were the 7 successfully-read pages genuinely worthless, or did Study Agent reject
valuable content? **Answer: genuinely worthless. 0/7 rejections were false.**

| read | url | content | post-read verdict |
| --- | --- | --- | --- |
| energy-1 | diffchecker.com/zh-Hans | text-diff tool marketing | `semantic_unrelated_body` (correct) |
| energy-2 | hanyuguoxue.com/cidian/… | "比较" dictionary entry | `semantic_unrelated_body` (correct) |
| energy-3 | bijiao.caixin.com | 财新《比较》economics journal | `semantic_unrelated_body` (correct) |
| energy-4 | iciba.com/word?w=ground | "ground" dictionary entry | `semantic_unrelated_body` (correct) |
| factory-1 | wiki.factorio.com/Main_Page/zh | Factorio wiki **home page** (navigation) | `requested_model_version_absent` (correct: no answer content) |
| factory-2 | hanyuguoxue.com/cidian/… | "比较" dictionary entry | `requested_model_version_absent` (correct) |
| factory-3 | diffchecker.com/zh-Hans | text-diff tool marketing | `requested_model_version_absent` (correct) |

history: 0 reads (all 5 candidates rejected pre-read).

## Cause categorisation (the four buckets)
1. **Search itself off-target — DOMINANT.** Every read page and essentially all 50
   candidates were dictionary/tool/homepage results: the Chinese "比较" queries
   returned the word's dictionary/tool pages; the *English* energy queries
   ("air source heat pump …") returned Chinese dictionary pages for `air`/`ground`;
   the Factorio queries returned the game home / wiki home / 游侠网, never the
   specific train-interrupt article.
2. **Relevant body wrongly rejected — NONE (0/7).** The post-read judge correctly
   rejected every junk body.
3. **Relevant body not bound to target — ONE real selection defect.** The Factorio
   wiki **home** was judged `relevant` pre-read (matched 2 rq_ids) and read, then
   rejected post-read; the read slot was spent on a navigation page because search
   returned the home, not the article. This is a read-target-selection defect, not a
   mis-binding of a good page.
4. **Insufficient / unknown — LARGE.** Most candidates were `unknown` (the
   relevance judge runs once and covers ≤5 candidates); history's 5 candidates were
   all `semantic_candidate_already_rejected`.

## Terminal states are three different things (not "search failed")
| case | stop | what it means |
| --- | --- | --- |
| energy | BUDGET_EXHAUSTED | read cap spent reading junk |
| factory | PROVIDER_EXHAUSTED | provider failures (incl. a `web_read` 403) |
| history | CANDIDATE_EXHAUSTED | all candidates rejected pre-read → 0 reads |

## Identified defects (minimal, testable)
1. **Search provider quality (primary, environment).** SearXNG down →
   `web_search:searxng:URLError WinError 10061`; the fallback returns generic
   dictionary/tool/home pages. Fix = restore SearXNG and, if needed, evaluate a
   third provider with a real API. Do **not** loosen the post-read judge or gate.
2. **Read-target selection (small).** When the top candidate is a known home/nav
   URL (`/`, `/Main_Page`, language root) and a specific article URL exists in the
   same result set, prefer the article and don't spend a read on the home. Evidence:
   factory read `wiki.factorio.com/Main_Page/zh`.
3. **Candidate coverage (observability, not a gate change).** The relevance judge
   runs once over ≤5 candidates; the rest are `unknown`. Record this explicitly.

## Not observed (not guessed)
- Per-candidate originating provider beyond the result `source` ("Bing RSS" for all
  observed); the 403 read target is not identified.
- Real SeAXNG-on results (needs Docker) — that is the separate open/closed
  comparison, to be run with the same frozen queries.

## Verdict
The zero-evidence is a **search-provider/selection** failure. The post-read
relevance judge and the evidence gate behaved **correctly**. Next fix the provider,
then read-target selection; not the gate.

## Correction (query-terms are co-primary) — after direct same-provider test
Challenged by the user, I re-tested on the **same** fallback provider with the
frozen long queries and short targeted queries for the same facet
(`model-driven-search-1c/query_compare.txt`):

| query | top results | reading |
| --- | --- | --- |
| history-long `明治 地租改正 1873 …` | 明治(食品品牌), 明治天皇 | junk |
| history-short `地租改正 1873` | `地租`, `地租理论` wiki + 知乎「地租」 | **topic-relevant** |
| energy-long-en / short-en `air source heat pump… defrost` | `air` dictionary pages | engine reduced to the token `air` |
| energy-short-zh `空气源热泵 低温 除霜` | `空气`, 空气成分, 空气污染 | still generic (engine weak) |
| factory-long / short `Factorio … train interrupts` | Factorio home / wiki home | no improvement |

Findings:
- The engine **does respond to the terms** (it returns token-matched pages) — so a
  blanket "the engine is broken" was an over-reach. The long queries are **reduced
  to a dominant token** (`air`, `比较`, `明治`), and the `authoritative_domain`
  query literally embeds the full Chinese question, which is why it matched `比较`.
- **Query terms materially change relevance** (history long→junk, short→topic).
- But short queries did **not** fix energy (still "空气") or factory (still home),
  so the fallback engine is **also** weak.

**Revised verdict: BOTH.** Query construction is a real, primary, fixable cause;
the weak fallback compounds it. The prior "provider dominant" label is retracted.

Revised fix order:
1. **Query construction** — short entity+facet terms; never embed the full question;
   drop generic lead words; keep version/time/conditions. (bounded, testable)
2. **Search provider** — restore SearXNG and compare on the same frozen queries;
   evaluate a third provider only if the fallback stays generic.
3. **Read-target selection** — prefer the specific article over a home/nav URL.
