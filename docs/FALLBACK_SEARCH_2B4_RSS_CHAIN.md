# B-Search-2B4 — RSS discovery chain end-to-end: result

Base `693fb376`. No API key, no new provider. RP-1 NO-GO.
Evidence: `reading-notebook-ui-evidence/model-driven-search-2b4/exp1.json`, `exp2.json`.

## Safety change (required before production)
`src/web/research_tool_agent.py` `feed`: after `urlopen`, the **final** URL (after
redirects) is re-validated with `_public_url`; a redirect onto a private/loopback
target is rejected (`feed_redirect_not_public`). +1 test
(`test_feed_rejects_private_redirect`). 9 tests PASS; ruff PASS; mypy file Success.

## Experiment 1 — known feed URL (via `initial_urls`) → **PASS**
Feed `https://blog.python.org/feeds/posts/default?alt=rss`:

| round | action | result |
| --- | --- | --- |
| 0 | **feed** (provided) | **ok, 10 entries** (incl. `…/2026/10/python-3150-final-is-here/`) |
| 1 | **read_page** the entry | **ok, 4379 chars** |
| 2 | finish | — |

stop=`finished`. The read body is the **official Python blog post about Python
3.15.0 final** — the article the question asked for. **The RSS toolchain
(feed → entry discovery → article read) works end-to-end.**

## Experiment 2 — autonomous feed discovery (no `initial_urls`) → **FAIL (honest)**
| round | action | result |
| --- | --- | --- |
| 0 | feed `pythoninsider.blogspot.com/feeds/posts/default` (guessed) | `pending_url_confirmation` |
| 1–2 | search | junk (`Official` dictionary) / python.org pages |
| 3 | feed `feeds.feedburner.com/PythonInsider` (guessed) | `pending_url_confirmation` |
| 4 | search | python.org pages |
| 5 | feed `www.python.org/blogs/rss/` (guessed) | `pending_url_confirmation` |

stop=`round_limit`, searches=3, **reads=0**. The fallback search **never returned a
real feed URL**, so the agent had no confirmed feed to read; its plausible guesses
were correctly rejected by the URL-confirmation rule.

## Verdict
- **RSS toolchain = PASS** (known feed: feed→entries→article read, answer-relevant
  body). Redirect safety added.
- **Autonomous RSS discovery = blocked by search quality**: the provider surfaces
  homepages/dictionary pages, not feed URLs, so the agent cannot discover a feed on
  its own. This is a **search-provider** block, not an RSS-toolchain block.

## Next
- Either a small **known-feed registry** (per-topic curated feeds) to make discovery
  reliable without a search API, or the **keyed search API** (to surface feed/article
  URLs). Do not loosen URL confirmation or the gate.

## Boundaries
No change to budgets, URL confirmation, Evidence Gate, or publication authority;
bodies stay exploratory. `main`, #208 and the frozen branches untouched.
