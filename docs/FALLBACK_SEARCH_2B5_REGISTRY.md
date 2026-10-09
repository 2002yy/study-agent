# B-Search-2B5 — known Feed registry + SSRF hardening: result

Base `a33f6c01`. No new model call, no budget change. RP-1 NO-GO.
Evidence: `reading-notebook-ui-evidence/model-driven-search-2b5/exp1.json`, `exp2.json`.
**Acceptance: `Registry-assisted Discovery PASS`** (never “open-web autonomous discovery”).

## Security hardening (SSRF) — fixed before production
The old check looked at `response.url` **after** the request had already been made.
Now:
- `host_resolves_public(host)` resolves DNS and requires **every** address to be a
  public (`ip.is_global`) IP — a public domain resolving to a private/loopback IP is
  rejected.
- `safe_fetch(url)` disables automatic redirects and validates **scheme + resolved IP
  of every hop BEFORE requesting it**; a redirect to a private target is rejected
  **without contacting it** (max 4 hops).
- `read_page` applies the same `host_resolves_public` guard before `gateway.read`.
- Tests prove no request is made to a private target:
  `test_safe_fetch_rejects_private_dns_without_requesting`,
  `test_safe_fetch_never_contacts_private_redirect_target`,
  `test_read_page_blocked_when_host_not_public`. 11 tests PASS; ruff PASS; mypy file Success.

## Registry (registry-assisted discovery)
`src/web/research/feed_registry.py`: `FeedSource` (source_id, topic, keywords, feed_url,
nature, operations, qualification, evidence) + `match_feeds(question)`. One verified
source so far: `python-official-blog` (nature `official_vendor_blog`, `qualified`).
Wired via `run_tool_agent(registry_sources=...)`: a matched feed URL is confirmed with
basis **`registry_seed`** (distinct from `initial_urls` / `search_result`) and offered
to the model as a reliable source — **non-forcing** (the registry never reads all
sources; the model still decides).

## Real validation
**Exp1 — Python update question → PASS.** `match_feeds` → `python-official-blog`;
agent: `feed` → **10 entries** → `read_page` `…/python-3150-final-is-here/` (**4379 ch**)
→ `read_page` `…/python-31022-31117/` (**6000 ch**) → `finish`. Two **official Python
blog articles** read and associated with the update question. stop=`finished`.

**Exp2 — irrelevant topic (Go rules) → correct non-use.** `match_feeds=[]`; the Python
feed was not offered and not used; the agent searched Go rules and read a confirmed Go
page (260 ch). It did **not** wrongly adopt the Python source.

**Exp4 — guessed URL** → still rejected (`pending_url_confirmation`).
**Exp3 — unreachable registry source** → **not run** (noted; no fabrication).

## Verdict
`Registry-assisted Discovery PASS`: the curated, verified RSS route now works
end-to-end from a natural-language question, with the SSRF boundary fixed and the
registry non-forcing. It is **not** open-web autonomous discovery (that stays blocked
by search quality) — the registry is an added reliable route, not a replacement for
search.

## Boundaries
No change to model/search/feed/read/round/time budgets, URL confirmation,
Evidence Gate, or publication authority; bodies stay exploratory. `main`, #208,
Shadow and frozen A/B untouched.
