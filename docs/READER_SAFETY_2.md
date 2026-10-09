# Reader-Safety-2 — wire the article reader onto the safe transport (PARTIAL)

Base `eb068a70`. RP-1 NO-GO. **Verdict: PARTIAL** — the structured transport
prerequisite landed; the article reader itself is **not yet wired**.

## Done — structured transport (`src/web/safe_http.py`)
Added `safe_fetch_result(url, …)` over the same rules (per-hop scheme/port/IP check
BEFORE connect, IP-pinned connection, TLS SNI, one absolute deadline, hop/byte
bounds). It returns a reader-ready dict:
`{requested_url, redirect_chain, final_url, status, headers, content_type,
content_encoding, raw(bytes), text, truncated}` and **raises `ValueError`
(fail-closed)** on security refusal / network error / bad status / limit — the
caller must not route a refusal into a weaker fallback.
- `http_get_raw(...)` returns raw bytes + truncation flag; `http_get_pinned` is now a
  thin string wrapper → **the Feed `safe_fetch` path is unchanged (no regression)**.
- Tests: 18 PASS (structured result, truncation flag, private-target-blocked-without-
  request); `ruff` PASS; mypy file Success.

## Not done (still blocked)
`src/news/article_fetcher.py` (497 lines) already has a `_SafeRedirectHandler` +
`_check_dns_target_safe`, but the latter documents a **pre-check → `urlopen` race**
and the Firecrawl/Jina fallbacks can **bypass** a refusal. Wiring its HTTP layer
(`_fetch_html_payload` / `_fetch_text_payload`) onto `safe_fetch_result` while
preserving gzip decode, charset handling, HTML/author extraction and the
`ArticleReadResult` semantics, **plus** fail-closed gating of the fallbacks and the
cache — is the remaining work and was **not** performed in this slice.

## Safety coverage matrix (separate per entry)
| entry | status |
| --- | --- |
| Feed `safe_fetch` (RSS/agent) | **PASS** |
| shared transport `safe_fetch_result` (structured) | **PASS** (prereq for the reader) |
| general article reader `article_fetcher` | **BLOCKED** |
| `gateway.read` (production) | **BLOCKED** |
| official metadata reader | **UNAUDITED** (independent entry) |
| GitHub reader | **UNAUDITED** (independent entry) |
| Firecrawl/Jina fallback | **BLOCKED** (may bypass refusal) |

## Boundaries
No model/call budget, Evidence Gate, publication, main, #208 or Shadow change. B
production wiring still not enabled. Only the Feed entry keeps its existing
qualification; nothing new is unblocked.

## Next
Wire `_fetch_html_payload`/`_fetch_text_payload` through `safe_fetch_result`, gate
Firecrawl/Jina so a security refusal never falls back, ensure the cache cannot skip
safety admission, then re-run the reader regression + a real public-article read and
update the matrix — only then unblock the general article reader.
