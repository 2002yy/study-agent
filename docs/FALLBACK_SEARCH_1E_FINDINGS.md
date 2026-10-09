# B-Search-1E — research search query construction: result

Worktree `codex/model-driven-research-entry` @ `1bb0192a` + this slice. Read-only
against frozen A/B, Answer Reliability, learning state, publication gate.
RP-1 NO-GO. **Verdict: PARTIAL — no relevant body obtained (0/3, unchanged).**

## What changed (correct and tested, but insufficient)
- `search_query_quality.optimize_search_query` now removes generic scaffolding
  inside continuous CJK (not only whitespace tokens), drops generic English
  tokens, and caps length (`MAX_QUERY_TOKENS=12`).
- `search_query_quality.build_authoritative_query`: the reserved official query
  no longer embeds the raw full question; it uses the compacted core terms.
- `research_recovery`: the `authoritative_domain` query uses the compacted topic;
  `select_research_queries` now breaks coverage ties by a deterministic
  specificity (version/date tokens + token count), not input order.
- `query_rewrite_map` records original/optimized/reason/rq per query.
- Tests: 98 focused PASS; `ruff` PASS; mypy current 122 / baseline 128 NEW 0.

## Paired test (same fallback provider) — the decisive result
Evidence: `model-driven-search-1c/paired.txt`. Old vs optimized queries on the
same Bing RSS:

| case | old query → top result | new query → top result | change |
| --- | --- | --- | --- |
| energy `air source heat pump…` | `air` dictionary | still `air` dictionary | none |
| energy official (full Q) | `比较` dictionary | `空气` pages | none useful |
| energy `ground source heat pump…` | `ground` dictionary | still `ground` dictionary | none |
| factory `Factorio 2.0 train interrupts…` | factorio.com home | same | none |
| history `明治 地租改正 1873…` | 明治(食品品牌) | same | none |

**The optimized queries returned essentially the same results.** The fallback
engine matches the **leading/dominant token** (`air`, `空气`, `比较`, `明治`) and
returns dictionary/home pages, regardless of the tail. Mechanical compaction trims
the tail and a few generic words but does **not** change the leading token, so it
cannot fix this.

## What this proves
- Query terms matter (the earlier manual `地租改正 1873` led with the specific
  term and returned topic pages), **but a purely mechanical compaction is not
  enough** — the fix must be **entity-led** (drop/replace the non-discriminative
  leading token, lead with the specific entity/metric).
- The fallback engine is **also genuinely shallow** for these topics (Factorio →
  only the home page even with the right leading entity).

## Verdict and next
**PARTIAL**: the query-planning changes are implemented, tested and remove real
defects (full-sentence official query, input-order tiebreak), but the goal
(≥1 real answering body from better queries) was **not** met (0/3).

Decision input:
- The promising direction is **entity-led query construction** — a semantic choice
  of the head term (e.g. lead `地租改正` not `明治`), which mechanical deletion
  cannot do. That is a query-planning change, not a budget/engine change.
- In parallel the fallback engine remains shallow → restore SearXNG for the
  same-query open/closed comparison before judging the engine.

No change to B answer-target planning prompt, query/read/model budget, post-read
relevance or the Evidence Gate.
