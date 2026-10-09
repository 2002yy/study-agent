# Fallback Search-1 — reconnaissance and bounded fix plan

Worktree `D:/study-agent-validation/model-driven-research-entry`, branch
`codex/model-driven-research-entry`, base `731e9851` (clean). Read-only against
frozen A/B, Answer Reliability `c60a0ab1`, learning state and publication gates.
RP-1 stays NO-GO.

This is the required step 1 (reconcile concurrency, existing providers, and B's
real production path). The production change is deliberately **not** made yet:
it touches a 696-line recovery loop and should be validated against a live
provider, not blind.

## Actual production call path (verified)
`PersistentWebToolAgent(gateway=GeneralWebGateway(), research_service=...)`
→ `recover_public_research(self.gateway, ...)` in `src/web/research_recovery.py`.
So the B path uses **`GeneralWebGateway` + the recovery loop**, not
`ResearchProviderSearch`/`active_research_runtime`.

Provider chain (`src/web/tool_gateway.py`): `search_exact` → `_search_single`
(SearXNG → Bing RSS → DuckDuckGo HTML), multi-variant via `search_detailed`,
with `provider_errors`/`providers_attempted` audit.

## Existing machinery already present (do not rebuild)
- `src/web/tool_gateway.py`: multi-provider search, dedupe, per-call timeout,
  `provider_errors`, canonical read error codes.
- `src/web/research_recovery.py`:
  - `_rewrite` / `normalize_web_query` / `select_research_queries`: search-advice
    rewriting (keeps the immutable original question).
  - `assess_sources` (`src/web/source_assessment.py`): URL dedupe, title/snippet
    lexical match, `directness`.
  - `research_candidate_relevance` (semantic): filters top-5 selected candidates
    **before** reads; unrelated → `semantic_rejected_urls`.
  - `research_body_relevance` (semantic): post-read body relevance;
    `read_backed` vs `candidate_exhausted/no_related_body`.
- `src/web/research/candidate_ranking.py`
  (`answer_relevant/topic_only/off_target/unknown`, `rank_candidate_pool`) exists
  but is used by `active_research_runtime` (Standard/Deep), **not** by this
  Lookup/recovery path.

## Root cause of the junk reads (real funnel)
For the three samples the fallback (`Bing RSS`, SearXNG refused) matched the
prominent Chinese term (e.g. `比较`) and returned dictionary/tool pages; the
lexical `assess_sources` accepted them (title contains the term) and the
permissive `research_candidate_relevance` judge marked them related, so read
slots were spent on them; `research_body_relevance` then rejected the bodies →
`candidate_only`, 0 accepted evidence. So the failure is **candidate
quality/relevance for CJK**, not "non-empty treated as success" (that gate
already exists) and not planning/budget/read-eligibility.

## Proposed bounded fix (for approval before editing)
1. **Fallback query construction** (highest leverage, no new model): derive a
   compact engine query — name/version/time/conditions + a comparison/mechanism
   keyword — instead of the full sub-question; reuse `query_normalizer.py` and
   `_rewrite`. Record original↔actual query. This stops the fallback from
   matching the literal word `比较`.
2. **Candidate ordering by relevance**: order `selected` by the semantic
   `rq_ids` count before spending reads, so strongest candidates are read first
   (additive; keeps the existing judge, no second evaluator).
3. **Explicit classification** in the recovery summary: `relevant_candidates` /
   `off_target_candidates` / `unknown_candidates` (retrieval scheduling only, not
   support), so acceptance is auditable.
Constraints kept: ≤5 queries, reads/model budget, Evidence Gate, publication
authority, B planning prompt unchanged.

## Acceptance status
| item | status |
| --- | --- |
| fault awareness (SearXNG down vs no results) | verified (`WinError 10061` recorded) |
| candidate quality (relevant/off-target trackable) | **pending** — needs fix 3 |
| relevant body acquired | 0 (blocked) |
| per-target coverage | 0 accepted |
| query reuse | measured 0.0 |
| ≤5 queries | held |
| false VERIFIED | 0 |
| publication | RP-1 NO-GO |

## Next
`src/web/search_query_quality.py` now provides the pure, tested building blocks
(`optimize_search_query`, `order_candidates`, `classify_candidate`). The
production wiring into `research_recovery._recover_public_research` is **not yet
applied**: adding the helpers plus a `query_rewrite_map` to the 796-line loop
made mypy infer the candidate rows as `dict[str, str]` (4 new errors at the
existing `row["assessment"]` sites), so the wiring needs a dedicated, typed pass
rather than a blind edit. No production behaviour changed.

Remaining for Fallback Search-1B: wire the three helpers into the recovery loop,
record per-candidate classification + query_rewrite_map in the checkpoint, and
re-run energy/factory/history with SearXNG down.
