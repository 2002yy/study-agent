# B-Search-2B — URL confirmation + real read chain (part 1): result

No API key needed. Agent-side change + a human-URL read experiment. Base `5769a8b7`.
RP-1 NO-GO. Evidence: `reading-notebook-ui-evidence/model-driven-tool-agent-read-1/trace.json`.

## What changed (agent-side)
`src/web/research_tool_agent.py`: the tool agent now applies a **URL-confirmation
rule** — `read_page` is allowed only for a URL that appeared in a prior search
result, or was supplied up front via `initial_urls` (the human-provided case). A
model-guessed URL is recorded `pending_url_confirmation` and **not fetched**.
+2 tests (`test_read_requires_confirmed_url`, `test_initial_urls_are_readable_without_search`).

## Real read-chain experiment (factory question, seeded known URLs)
`initial_urls = (en.wikipedia.org/wiki/Factorio, www.factorio.com)`.

| round | action | outcome |
| --- | --- | --- |
| 0 | search `Factorio train interrupts scheduling official wiki` | 5 results |
| 1 | search again | `quota_exceeded` |
| 2 | `read_page https://wiki.factorio.com/Train_schedule` (guessed) | **`pending_url_confirmation`** (not from search) |
| 3 | `read_page https://wiki.factorio.com/Main_Page/zh` (from search) | **ok, body 188 chars** |
| 4 | search | `quota_exceeded` |

stop=`round_limit`, `publication_authority=false`.

## What is validated
- **URL confirmation works**: guessed `Train_schedule` → rejected; search-confirmed
  `Main_Page/zh` → read. The model reacted to the rejection and picked a confirmed
  URL (agent behaviour).
- **Real body read works**: 188 chars fetched and hashed.
- **Evidence isolation**: no authority granted; nothing upgraded.
- **Content association — NOT met here**: the confirmed/reachable URL was the wiki
  **home** (navigation), not an answer-bearing article. So the read *mechanism*
  works, but this run did not obtain a body that answers the sub-question.

## Limits (honest)
- URLs were **human-provided** → this validates the *back half* of the agent
  (confirm → read → react), **not search discovery**.
- The reachable confirmed URL happened to be a navigation page; per the criterion, a
  home/nav page **does not count** as success.

## Next
- Part 2 (real networked search) needs an **API key or an egress-normal environment**.
  Preferred: env-var injection so a free-trial key can be supplied locally /
  as a CI secret without committing it.
- Keep the replaceable tool registry (`platform_capabilities`) as the integration
  point; do not loosen the Evidence Gate to manufacture a success.
