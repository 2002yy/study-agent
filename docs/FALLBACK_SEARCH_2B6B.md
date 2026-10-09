# B-Search-2B6-B — Feed toolchain safety + source qualification

Base `809c4974`. RP-1 NO-GO. 13 tests PASS; ruff PASS; mypy current 122 / baseline
128 NEW 0.

## 1. `gateway.read` connection safety — inspected, block kept
`GeneralWebGateway.read` → `fetch_article_read_result(...)`, a full article reader
that **follows its own redirects** (`result.final_url`). Reusing it safely (per-hop
IP validation) is a **reader-backend rewrite** and is out of this bounded slice.
Action per the contract: **keep the production block**, add **defense in depth** —
after a read, the reported `final_url` is re-checked with `_public_url`; a non-public
final URL flips the read to `ok=False` (`reader_final_url_not_public`). Residual
pre-connection risk inside the reader is recorded as an open item.

## 2. Redirect chain cannot renew the budget
`safe_fetch(..., deadline=...)` takes **one absolute monotonic deadline shared by all
hops**; each hop's timeout is `min(timeout, deadline-now)` and a hop past the deadline
raises `deadline_exhausted` — no per-hop full-budget renewal.

## 3. Auditable source chain
`run_tool_agent` now returns `source_chain`: for every successful read,
`{"basis", "feed_url", "entry_url", "read_url"}`. `basis` distinguishes
`registry_seed` / `initial_urls` / `search_result` / `feed_entry`; `feed_url` records
the parent feed for entries. A registry source never grants factual authority.

## 4. Exp3 — failure behaviour (`empty` vs `unavailable`)
`feed` now records `feed_status`:
- `ok` — entries found; `empty` — valid feed with no items; `unavailable` — fetch
  failed or **invalid XML** (`invalid_feed_xml`). No fabricated entries, no extra
  hidden budget. Tests: empty feed → `empty`; malformed XML → `unavailable`;
  unreachable → `unavailable`.

## Verdict
Safety + audit **PARTIAL**: redirect-budget and failure states fixed; the
**pre-connection safety inside the shared reader** remains open and the production
block is retained (do not wire production until a dedicated reader-safety slice).

## Next
`B-Search-2B7`: scalable source directory (OPML import → dedup/classify → index →
Top-K recall → on-demand verify), with four **independent** facts (catalog / feed
qualification / article read / evidence) — never one linear state.
