# Fallback Search-1B-2 — wiring, real fallback run and verdict

Worktree `D:/study-agent-validation/model-driven-research-entry`, branch
`codex/model-driven-research-entry`, base `91f878f2`. Read-only against frozen
A/B, Answer Reliability `c60a0ab1`, learning state and publication gates.
RP-1 stays NO-GO. **Verdict: PARTIAL** (wiring PASS, research effect still 0).

## Phase 1 — B call chain (confirmed)
- `PersistentWebToolAgent.resolve` planned branch builds `ResearchSemanticSession`
  and calls `recover_public_research(..., semantic_session=session, query_plan=plan)`
  (`persistent_web_agent.py:554-558`). So the semantic relevance judge **does
  run** in the B path (`research_candidate_relevance` once per run;
  `research_body_relevance` post-read). Line 239 is a different, non-planned
  branch (no `semantic_session`).
- Type fix: the 4 mypy errors came from my new `for row in query_plan:` binding
  the function-scoped `row` to `dict[str, str]` before the existing loops.
  Renamed to `plan_row`; `mypy` now `Success` on the file with **no `type: ignore`
  and no cast**.

## Phase 2 — wiring
`research_recovery._recover_public_research` now uses
`optimize_search_query` (search advice), `order_candidates` (composite ordering),
`classify_candidate`; records `query_rewrite_map` and `candidate_classification`
in the checkpoint (`candidate_dispositions`/`target_coverage` already present).
`WebToolTrace.to_dict` exposes it as the trace `recovery` field.

## Phase 3 — real fallback run (SearXNG down)
Evidence: `reading-notebook-ui-evidence/model-driven-search-1b/`.

| case | searches | candidates | reads ok | accepted | off_target filtered | unknown | stop |
| --- | --- | --- | --- | --- | --- | --- | --- |
| energy | 4 | 20 | 4 | 0 | 1 | 9 (read_cap) | BUDGET_EXHAUSTED |
| factory | 4 | 20 | 3 | 0 | 5 (3 semantic + 2 homepage) | 0 | PROVIDER_EXHAUSTED |
| history | 2 | 10 | 0 | 0 | 5 (semantic) | 0 | CANDIDATE_EXHAUSTED |

- `query_rewrite_map`: all `reason=unchanged` — the plan queries are already
  compact Latin/keyword, so CJK generic-word removal is a **no-op** on these
  samples.
- `candidate_classification`: recorded per candidate; `relevance` is
  `relevant`/`unknown` where the judge covered the candidate, and explicit
  off_target is filtered (not read).
- Provider: every case records `web_search:searxng:URLError ... WinError 10061`.
- Accepted evidence is still 0: the relevance machinery runs and filters some
  candidates, but the read bodies were not accepted.

## Verdict and honest limits
**PARTIAL**: production behaviour changed and is now observable (checkpoint,
classification, ordering, query-rewrite map in the B trace), `mypy`/`ruff` clean,
focused suites green (86 + 53). But **no relevant body was obtained** in any of
the three samples, so Fallback Search-1B-2 does **not** claim improved fallback
search quality. This is the environment/provider block, not a planning, budget or
read-eligibility failure.

Per the decision tree: search candidates are partly filtered, but no relevant
body → next look at post-read relevance / evidence binding, or a more reliable
third search provider; do not add rules or budget blindly.

Gates: focused 139 PASS, `ruff check .` PASS, `mypy` current 122 / baseline 128 NEW 0.
