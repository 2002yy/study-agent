# B-Search-1F — history `CANDIDATE_EXHAUSTED` offline attribution

Read-only. No production change, no CI. Base `e09f7c83`. RP-1 NO-GO.
Evidence: `reading-notebook-ui-evidence/model-driven-search-1e/history-trace.json`.

## Decision path (per candidate)
history ran on the **LOOKUP budget** (`hard_seconds=30, queries=2, reads=3`),
because the question (`明治初期地租改正的时间线、计税方式…`) matched neither the
standard comparison trigger nor a named version, so `recovery_budget` returned
LOOKUP. Both query slots were used; 3 read slots stayed free.

| # | query | candidate URL | title | relevance judgement | disposition | scheduling | remaining | final |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `地租改正 1873 1876 1881 …` | baike/地租/1741513 | 地租 | judged (research_candidate_relevance) | filtered `semantic_candidate_already_rejected` | not dispatched | reads 3/3 free | not read |
| 2 | same | baike/地租理论/7265624 | 地租理论 | judged | filtered `semantic_candidate_already_rejected` | not dispatched | reads 3/3 free | not read |
| 3 | same | zhuanlan.zhihu.com/p/16769609995 | 第十一章 地租 | judged | filtered `semantic_candidate_already_rejected` | not dispatched | reads 3/3 free | not read |
| 4 | same | zhihu.com/question/41871536 | 地租…问题 | judged | filtered `semantic_candidate_already_rejected` | not dispatched | reads 3/3 free | not read |
| 5 | same | zhuanlan.zhihu.com/p/632382393 | 地租 | judged | filtered `semantic_candidate_already_rejected` | not dispatched | reads 3/3 free | not read |
| — | `… official documentation` (phase 2) | same 5 URLs | — | not re-judged (`research_candidate_relevance` already ran) | filtered `semantic_candidate_already_rejected` | not dispatched | — | not read |

Terminal: `CANDIDATE_EXHAUSTED`, reads 0, `target_coverage required=0`.

## The four questions
1. **Which candidates entered judgement?** All 5, once (phase 1). Phase 2 returned
   the identical 5 URLs and skipped them (`semantic_candidate_already_rejected`).
   Judged=5, filtered=5, deferred=0, unknown(not judged)=0.
2. **Why weren't 地租/地租理论 read?** `research_candidate_relevance` rejected all
   five on **title+snippet only** (no body was read). Whether that was correct
   (topic-adjacent but no 1873 地租改正 evidence) or over-strict (a 知乎 article may
   hold the answer) is **NOT determinable** from the records: the per-candidate
   relevance decision/reason is not persisted, and no body was read.
3. **Was any qualified candidate unscheduled?** No. Rejection happened **before**
   scheduling; 0 reads with **3 read slots free** → it was **not** budget, order,
   timeout or termination.
4. **Is `CANDIDATE_EXHAUSTED` correct?** Mechanically yes (every candidate was
   filtered). Semantically **undetermined** — do not call it a false rejection.

## Attribution (per the frozen table)
- Not "qualified candidate unscheduled" (Q3 = no).
- **Cannot conclude "valuable candidate wrongly rejected"** — the evidence is
  insufficient (judge reason not persisted; no body read).
- ⇒ **"records insufficient to judge"**: add diagnostics (persist each candidate's
  relevance decision and reason), do **not** loosen the judge or force a read.
- Secondary real finding: history was classified **LOOKUP (2 queries)** despite
  being a multi-facet research question — a separate budget-mode issue.

## Next
1. Persist per-candidate `research_candidate_relevance` decision + reason (and,
   where possible, the title/snippet it judged) so the next run can distinguish
   correct-strict vs wrong rejection. Bounded, no gate/budget change.
2. Only then decide: tighten/loosen the relevance judgement, or move to the
   search-provider (SearXNG) comparison.
