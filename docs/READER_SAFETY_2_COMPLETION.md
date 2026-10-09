# Reader-Safety-2 Completion — article reader on the safe transport

Base `5ee870b5`. RP-1 NO-GO. Evidence:
`reading-notebook-ui-evidence/reader-safety-2/reader_e2e.json`.

## Transport migration
`src/news/article_fetcher._fetch_html_payload` / `_fetch_text_payload` now fetch via
`src.web.safe_http.safe_fetch_result` (per-hop scheme/port/IP validation before
connect, IP-pinned connection, TLS SNI, shared absolute deadline, hop/byte bounds).
Preserved: content-type gating, `_decompress_transport_payload` (gzip), charset
decode, `read_html_locally` extraction, `ArticleReadResult` semantics and the final
URL. `Request`-based `urlopen` path removed.

## Fail-closed refusals + fallback
`safe_http` now exposes `SafeFetchRefusal` (security: scheme/port/target/DNS/redirect/
deadline/oversize) vs `SafeFetchError` (ordinary network/status). The reader
**re-raises `SafeFetchRefusal`**, and `fetch_article_read_result` catches it **before**
the broad handler and returns `reason="security_refused:<reason>"` **without ever
calling Firecrawl/Jina**. Refusals are **not cached**.

## Truncation is a failure
`safe_fetch_result` raises `SafeFetchRefusal("response_too_large")` when the body
exceeds `max_bytes` (the earlier `truncated=True` returned as success is fixed); the
reader also re-checks after decompression. A truncated body is never reported `ok`.

## Verification
- New tests `tests/test_reader_safety.py`: refusal fail-closed (fallback not called),
  truncation → failure, normal read keeps extraction.
- Reader regression `test_news_reader_transport / reader_backends / firecrawl_reader /
  reader_hint_routing / multimodal_reader / reader_task_request / reader_safety`:
  **83 passed, 1 skipped**. `ruff` PASS; mypy current 122 / baseline 128 NEW 0.
- **Real end-to-end through `fetch_article_read_result`**:
  | url | ok | method | final_url | chars |
  | --- | --- | --- | --- | --- |
  | `blog.python.org/…/python-3150-final-is-here/` | **true** | local_trafilatura | same | **4000** (text: “Python 3.15.0 is now available …”) |
  | `http://127.0.0.1/x` | false | — | — | reason `unsafe_or_empty_url` |
  | `http://10.0.0.1/` | false | — | — | reason `unsafe_or_empty_url` |

## Safety matrix (per entry)
| entry | status |
| --- | --- |
| General article reader (`fetch_article_read_result`) | **PASS** (safe transport, fail-closed, truncation=failure, fallback gated) |
| Feed `safe_fetch` | **PASS** |
| `GeneralWebGateway.read` overall | **PARTIAL** — its general-article branch is now safe, but the official-metadata and GitHub branches are unaudited |
| Official metadata reader | **UNAUDITED** |
| GitHub reader | **UNAUDITED** |
| Firecrawl/Jina fallback | **gated for security** (never reached on a refusal); **UNAUDITED** as readers for ordinary failures |

## Boundaries
No model/call/network budget change; Evidence Gate, publication, main, #208, Shadow
untouched. B production wiring not enabled.

## Next
Feed-entry **semantic selection** (choose the entry that actually answers the
sub-question, not the first one) — no more infra slices first.
