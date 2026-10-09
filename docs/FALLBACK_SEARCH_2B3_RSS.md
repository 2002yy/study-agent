# B-Search-2B3 — RSS discovery + real read/associate (agent-driven, no key)

Base `4f158b90`. No API key, no environment change. RP-1 NO-GO.
Evidence: `reading-notebook-ui-evidence/model-driven-search-2b3/trace.json`.

## What changed (agent-side)
`src/web/research_tool_agent.py`: added a bounded **`feed` tool** — the agent may
call `{"tool":"feed","url":"<rss/atom>"}`; the program fetches the feed, parses
RSS `<item>`/Atom `<entry>` (stdlib, no extra dependency), exposes the entry
title/link list, and **adds the entry links to the confirmed set** so they become
readable. The same **URL-confirmation rule** applies to `feed` (only URLs the agent
already has are fetchable). +2 tests (`parse_feed` RSS+Atom, feed confirmation).

## Real run
Question: “Find the official Python blog post about the latest Python release and
summarize it.” Provided feed: `blog.python.org/...rss`.

| round | action | outcome |
| --- | --- | --- |
| 0 | search `official Python blog latest release …` | junk (`Official` dictionary) |
| 1 | `feed https://pythoninsider.blogspot.com/feeds/posts/default` | **`pending_url_confirmation`** (guessed feed) |
| 2 | search `Python Software Foundation blog latest release` | python.org results |
| 3 | `read_page https://www.python.org/downloads/` (confirmed) | **ok, 6000 chars** |
| 4 | `read_page https://pythoninsider.blogspot.com/` | `pending_url_confirmation` |

Body content (R3): *“Active Python releases … Python 3.15.0 Oct. 9, 2026 …”* —
**directly answers “latest Python release”**. `stop=round_limit`,
`publication_authority=false`.

## Verdict
- **First real answer-relevant body obtained and associated** to the question
  (goal met at the *read/associate* level, which was the point of this slice).
- **URL-confirmation enforced**: the model's guessed feed/blogspot URLs were
  rejected; only the search-confirmed `python.org/downloads` was read.
- **RSS `feed` tool is implemented and unit-tested**, but the agent did **not**
  choose it here (it guessed a feed URL, then used `search`) — so “RSS discovery by
  the agent” is not yet exercised end-to-end. The successful discovery was
  `search → python.org`.

## Limits
- n=1; the working discovery was search, not the feed tool.
- The fallback provider still returned dictionary junk for the first query.

## Next
- Either force/observe the `feed` tool (e.g., a task whose only sensible source is
  a feed) or accept that `search → specific page → read → associate` is proven and
  move the same chain onto a keyed search API when available.
- No gate/budget change; the body stays exploratory (`publication_authority=false`).
