# B-Search-1 — fine-grained tasks into real search/read: funnel, saturation, attribution

Worktree `D:/study-agent-validation/model-driven-research-entry`, branch
`codex/model-driven-research-entry`, base `3c687b5f`. Read-only against the
frozen A/B, Answer Reliability `c60a0ab1`, learning state and publication gates.
RP-1 stays NO-GO.

## What changed
- `src/web/semantic_recovery.py`: `preferences()` now accepts a **list** (or
  string) for `excluded_page_types`. The model legitimately proposes a list, but
  the string-only gate raised `invalid_string`, which **rejected the whole plan**
  — that was the energy case's 0-plan/0-search/0-read (now 14 targets). Not the
  planning prompt, not a budget change. `constraints`/`constraints_delta`
  widened to `dict[str, Any]`.
- `tools/summarize_research_funnel.py` (new): read-only 6-stage funnel + 24-cap
  saturation/sharing analysis from existing trace + episode artifacts.
- `tests/test_semantic_recovery.py`: list/string `excluded_page_types` accepted.

## The three headline numbers (fresh run)
Evidence: `reading-notebook-ui-evidence/model-driven-search-1/` (`funnel.json`).

| case | independent targets | targets with an issued query (of the 5-query cap) | targets with real body evidence |
| --- | --- | --- | --- |
| energy | 14 | 5 | **0** |
| factory | 16 | 5 | **0** |
| history | 24 | 5 | **0** |

## Saturation / sharing
| case | raw proposals | unique targets | exact dups | 24-cap hit | unique query texts | queries serving >1 target | query reuse | targets without query (budget) | issued searches |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| energy | 14 | 14 | 0 | no | 14 | 0 | 0.0 | 9 | 4 |
| factory | 16 | 16 | 0 | no | 16 | 0 | 0.0 | 11 | 4 |
| history | 24 | 24 | 0 | yes | 24 | 0 | 0.0 | 19 | 2 |

Reading: B proposes one **distinct** query per target, so there is **no query
reuse**; the 5-query cap therefore covers exactly 5 targets and defers the rest.
No exact duplicates and no over-merge; the 24 cap is hit only for history.

## Full stage funnel
| case | questions | proposed | deferred (budget) | searches | candidates | reads attempted | reads ok | accepted | evidence |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| energy | 14 | 14 | 9 | 4 | 20 | 3 | 3 | 0 | candidate_only |
| history | 24 | 24 | 19 | 2 | 10 | 0 | 0 | 0 | candidate_only |
| factory | 16 | 16 | 11 | 4 | 20 | 3 | 3 | 0 | candidate_only |

All: `validation=accepted`, recovery `second_process_equal=true`,
`publication_authority=false`, `coverage_kind=relevance_only_not_support_or_adequacy`.

## Exact block (the point)
`provider_errors` on every case: `web_search:searxng:URLError ... WinError 10061`
(connection refused) — the local SearXNG at `127.0.0.1:8080` is down (Docker
Desktop daemon not running), so search falls back to a provider returning
dictionary/tool pages for these Chinese queries. Reads then succeed (trafilatura,
`ok=true`) on **irrelevant** pages → nothing accepted.

Attribution by stage:
- planning: passes (14/16/24); energy fixed.
- search: fires, returns candidates, but the provider is degraded.
- read eligibility: not the block — reads succeed.
- budget: not the block — queries capped/deferred as designed.

## The five questions
1. Sub-questions saved and restored? Yes — 14/16/24, `second_process_equal=true`.
2. Real search produces valid candidates? Searches fire and return 10-20 rows, but
   quality is junk because the provider is down/degraded.
3. At least one successful natural read + source chain? Reads succeed mechanically,
   but **0 accepted**; history attempted none.
4. One query/source for many targets without false support? A `web_search` carries
   multiple `rq_ids` and `question_coverage=[]` grants no support; but in practice
   B proposes no shared queries, so coverage is capped at 5.
5. Budget/eligibility/publication broken? No — within quotas, relevance-only,
   `publication_authority=false`.

## Limits
- Real retrieval-quality qualification is **blocked by the environment** (SearXNG
  down). This is a truthful failure attribution, not a retrieval-quality result.
- "Independent necessary targets" here = unique admitted sub-questions, not a
  semantic necessity judgement.

## Next
Bring the local SearXNG up (Docker) and re-run the same three samples to obtain
the first relevant candidate → read → per-target evidence chain; then decide the
deferred question of bounded 5+N incremental queries. Do not add budget or topic
rules until the provider block is cleared.
