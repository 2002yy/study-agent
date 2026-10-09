# B-Search-2 — controlled research tool agent (first prototype): result

Worktree `codex/model-driven-research-entry` @ `a25d7587` + this slice. Read-only
against frozen A/B, Answer Reliability, learning state, publication gate.
RP-1 NO-GO. **Verdict: PARTIAL — the agent loop works and is observably agentic,
but 0 real bodies were obtained.**

## What was built
- `src/web/research_tool_agent.py`: a bounded model→tool loop. The model returns
  one action per round — `search` / `read_page` / `finish`; the **program**
  validates it (`_public_url` for reads), enforces search/read quotas and the
  deadline, executes, and returns the real result (results or body/error) so the
  model decides again. Every round records the action, its reason, the result and
  the remaining budget. Bodies are **exploratory**: `publication_authority=False`.
- `tools/run_research_tool_agent.py`: runs the three natural cases.
- `tests/test_research_tool_agent.py`: action validation, private-URL rejection,
  unknown-tool rejection, quota enforcement, failed-read recording, bad-action
  recovery.

Boundaries held: tools limited to search/read_page/finish; existing quotas reused
(4 searches / 3 reads); no new search provider, no calculator, no code execution;
no budget reset; Evidence Gate, post-read verification and publication unchanged.

## Real run (same Bing RSS, same quotas)
Evidence: `reading-notebook-ui-evidence/model-driven-tool-agent-1/`.

| case | stop | rounds | searches | reads | real bodies |
| --- | --- | --- | --- | --- | --- |
| energy | finished | 6 | 4 | 0 | 0 |
| history | finished | 6 | 4 | 0 | 0 |
| factory | round_limit | 6 | 4 | 2 | 0 (both 404) |

## What the run proves (agent behaviour)
- **The model acted as an agent.** history refined the query 4 times with explicit
  reasons (`地租改正 明治初期…` → `地租改正 明治6年 地価 3%…` → `明治政府 地租改正 1873…`),
  observed that the engine kept returning generic 地租理论 / 明治食品 pages, and
  **finished honestly** instead of reading junk. energy did the same.
- **The model chose specific pages to read.** factory picked
  `wiki.factorio.com/Train_schedule` ("likely documents interrupts") — good
  reasoning — but the URL 404'd; it retried `/zh` (404) then re-searched.
- **It did not over-read.** energy/history read nothing because nothing on offer
  was worth reading (the earlier pipeline would have spent read slots on junk).

## Why 0 real bodies (the wall)
1. **Search provider.** Bing RSS (SearXNG down) returns home/dictionary pages and
   **never surfaced the specific article** for any of the three topics, so the
   model had nothing valid to read or had to guess URLs.
2. **Model URL guessing.** When the engine returned no article link, the model
   guessed `.../Train_schedule` → 404. A real search result would have fixed this.

So the fixed pipeline vs tool-agent difference is **not** the loop quality: the
agent loop is functional and better-behaved; the shared blocker is the provider.

## Verdict and next
**PARTIAL**: the first-version success criterion (search → model select → successful
real-body read → continue) was **not** met because no real body was available. The
loop is proven runnable and agentic.

Next, in order:
1. Restore SearXNG and re-run the **same** three cases with the **same** queries and
   quotas to compare provider on/off (fixed pipeline vs agent).
2. Only then evaluate whether the agent beats the pipeline on valid-body coverage.
3. Phase 2 (not now): calculator and restricted code tools on the same tool surface.

Separately recorded, not changed here: history is classified **LOOKUP (2 queries)**;
do not change task grading and agent policy in the same experiment.

Gates: new tests 14 PASS; focused suites PASS; `ruff check .` PASS; mypy current
122 / baseline 128 NEW 0.
