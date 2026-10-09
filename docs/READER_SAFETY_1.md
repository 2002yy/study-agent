# Reader-Safety-1 — unified article-reader connection/redirect safety

Base `acea34e7`. Infrastructure slice; **does not wire B into production**. RP-1 NO-GO.
Evidence: `src/web/safe_http.py`; tests; read probe.

## Phase 1 — read-path audit
`GeneralWebGateway.read` fans out to three branches:
- **official metadata reader** (`read_official_metadata`) — known domains only;
- **GitHub reader** (`github_reader`); **general article reader**
  (`fetch_article_read_result` → DNS pre-check → HTTP → HTML extract → optional
  Firecrawl/Jina fallback).
`src/news/article_fetcher._check_dns_target_safe` itself documents a **pre-check →
`urlopen` race** (DNS can change between check and connect). Fallback readers
(Firecrawl/Jina) can change the network path and must not bypass a safety refusal.

## Phase 2 — fix: one reusable constrained transport
New `src/web/safe_http.py` (single implementation, reused by the feed/agent path):
- `resolve_public_ips(host)` — resolve once, require **every** address global;
- `http_get_pinned(url, host, ip)` — connect **to the validated IP** (no
  re-resolution), keep Host + TLS SNI/cert (`server_hostname=host`);
- `safe_fetch(url, …, deadline=…)` — validate scheme + port + resolved IP of
  **every hop BEFORE connecting**; one **absolute deadline** across hops; bounded
  hops and bytes; a private hop is **never contacted**.
`research_tool_agent` now **imports** these (local duplicate removed) — no two
divergent safety logics.

## Phase 3 — tests + real read
Tests 13 PASS; ruff PASS; mypy current 122 / baseline 128 NEW 0.
Real read probe (safe path):
| url | result |
| --- | --- |
| `https://blog.python.org/2026/10/python-3150-final-is-here/` | **ok, 67,568 chars** |
| `http://127.0.0.1/x` | blocked `unsafe_target` |
| `http://10.0.0.1/` | blocked `unsafe_target` |
| `https://example.org/feed` | blocked `http_404` (public, not a safety block) |

## Phase 4 — safety coverage matrix
| case | result |
| --- | --- |
| public HTTPS read via safe path | **PASS** |
| loopback / private IPv4 / IPv6 literal | **PASS** (never contacted) |
| abnormal port | **PASS** (`unsafe_port`) |
| redirect to private target | **PASS** (target not contacted) |
| shared deadline across hops | **PASS** (`deadline_exhausted`) |
| fallback bypass of a refusal | **N/A here** (safe path has no fallback) |
| `gateway.read` (production article reader) | **BLOCKED** |

## Verdict
The **shared constrained transport PASS**. It is the required safety primitive.
The **production article Reader (`gateway.read`) remains BLOCKED**: it is not yet
wired to this transport and its `_check_dns_target_safe` race + fallback readers are
unfixed. **Directory article URLs must not enter the production Reader** until a
dedicated slice wires it through `safe_http` and guards/removes the weaker
fallbacks.

## Boundaries
No model/network budget change; no Evidence Gate / publication / main / #208 /
Shadow change. This does not authorize production B wiring.
