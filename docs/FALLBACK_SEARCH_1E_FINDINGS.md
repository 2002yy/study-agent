# B-Search-1E — research search query construction (model-driven): result

Worktree `codex/model-driven-research-entry` @ `4817c505` + this slice. Read-only
against frozen A/B, Answer Reliability, learning state, publication gate.
RP-1 NO-GO. **Verdict: PARTIAL — query generation improved; still 0 accepted bodies.**

## What changed
- `model_driven_planning.PLANNING_PROMPT`: added a **query-only** instruction —
  `query` is search advice, not a restatement of `question`; lead with the concrete
  entity/model/mechanism/metric; keep version/year/conditions/negation; use the
  topic's language; avoid low-specificity lead words; never paste the question;
  each task object may contain only `question` and `query`. `question` semantics
  and scope unchanged.
- `research_recovery`: the reserved **official query no longer embeds the user
  question** — it reuses the model's entity-led proposal (or a compacted entity
  query) with a known official domain.
- `search_query_quality.optimize_search_query`: reduced to a **conservative
  safety net** (removes generic scaffolding only; no length cap, so a model number,
  year, condition or negation is never truncated).

## Real experiment (same Bing RSS, same budget)
Evidence: `reading-notebook-ui-evidence/model-driven-search-1e/`.

Query-generation quality (proven improved):
- energy: `空气源热泵 寒冷气候 安装 除霜 防冻` / `地源热泵 …` (was `air source…` English)
- history: `地租改正 1873 1876 1881 地租改正条例 地券` (led with the specific term)
- factory: `Factorio 2.0 train interrupts …` (kept version)
- official query: entity-led, no longer the raw question.

Search effect (mixed):
| case | result | reads | stop |
| --- | --- | --- | --- |
| history | **topic-relevant candidates** (`地租`, `地租理论`, 知乎「地租」) | 0 | CANDIDATE_EXHAUSTED |
| energy | still `地`/`空气` dictionary pages | 1 (junk) | BUDGET_EXHAUSTED |
| factory | still Factorio home / wiki home | 0 | CANDIDATE_EXHAUSTED |

**0 accepted bodies** (the goal was ≥1). So the query change alone did **not** meet
the exploratory threshold on the fallback engine.

## What this proves
1. **The model can produce entity-led queries** reliably (history query improved
   from `明治`食品 to `地租改正`-led and returned topic pages) — the earlier
   deterministic deletion could not do this.
2. **Query construction is now the smaller half**: history gets relevant
   candidates but **the system stops at `CANDIDATE_EXHAUSTED` without reading them**
   — a new, concrete next investigation (why weren't the `地租` pages read?).
3. energy/factory still fail because the **fallback engine returns home/dictionary
   pages** even with the right lead entity → engine needs the SearXNG/third-provider
   path.

## Verdict and next
**PARTIAL**: query generation is measurably better and correct; no relevant body
was obtained. Next, in order:
1. **history**: audit why topic-relevant candidates reach `CANDIDATE_EXHAUSTED`
   with 0 reads (candidate relevance judge / selection) — a bounded, offline step.
2. **energy/factory**: restore SearXNG for the same-query open/closed comparison.

Gates: 108 focused PASS, `ruff check .` PASS, mypy current 122 / baseline 128 NEW 0.
No change to B answer-target semantics, query/read/model budget, post-read
relevance, Evidence Gate, frozen A/B or publication authority.
