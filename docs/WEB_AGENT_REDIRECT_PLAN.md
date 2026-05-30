# Web Agent Redirect Resolution Plan

Status: planning only; no business code has been changed by this document.

Scope version: v0.7.x planning track

## 1. Background

Study Agent already has a news/web pipeline:

```text
RSS/Search fetch -> dedup/sort -> link resolution -> article extraction -> digest -> group discussion -> source trace
```

The current implementation has a useful base, but the redirect/link handling should be upgraded before adding more search providers or reader services.

Current observations:

- `docs/NEWS_PIPELINE.md` documents a 7-stage pipeline from RSS fetch to source-traced group discussion.
- `src/news/link_resolver.py` mainly targets Google News redirect links.
- `src/news/rss_fetcher.py` currently deduplicates early by raw link/title, then resolves only the top N links.
- `src/news/article_fetcher.py` already has DNS/IP validation and safe redirect handling for SSRF defense.

This plan keeps the existing architecture and improves the link-quality layer instead of replacing the whole news module.

## 2. Goal

Build a safer and more useful web-agent link pipeline:

```text
Search/RSS item
  -> redirect resolution
  -> URL canonicalization
  -> domain policy scoring/filtering
  -> canonical URL deduplication
  -> reader backend selection
  -> article extraction
  -> digest/discussion/source trace
```

The core idea: the Agent should reason over real URLs and real domains, not over search-engine redirect URLs.

## 3. Non-goals and safety boundaries

This project must not become a paywall/login/captcha bypass tool.

Out of scope:

- No login bypass.
- No paid-content/paywall bypass.
- No captcha solving or anti-bot evasion.
- No credential injection into third-party sites.
- No scraping of private/internal network targets.
- No background crawler that recursively follows arbitrary links without user intent.

Security requirements:

- Keep HTTP(S)-only URL fetching.
- Keep DNS/IP checks against private, loopback, link-local, multicast, reserved, and unspecified IP targets.
- Validate every redirect hop before following it.
- Keep max redirect depth and timeout bounds.
- Keep max bytes and max chars per article.
- Preserve source trace for auditability.

## 4. Open-source/free-first tool policy

Priority order:

1. Existing local extraction stack: `trafilatura`, `readability-lxml`, raw paragraph fallback.
2. Local custom redirect resolver and URL canonicalizer.
3. Optional SearXNG provider, preferably self-hosted or explicitly configured.
4. Optional Jina Reader fallback, disabled by default because it is an external hosted service even though it is free to use.
5. Optional self-hosted Firecrawl adapter only; no Firecrawl Cloud API dependency by default.
6. Paid search APIs are not part of the default plan.

Tool decisions:

| Tool | Decision | Reason |
|---|---|---|
| Local `trafilatura` / `readability-lxml` | Keep as default | Already installed, local, free, testable |
| SearXNG | Optional search provider | Open-source metasearch; JSON may be disabled on public instances, so require configurable base URL |
| Jina Reader | Optional reader fallback | Useful URL-to-Markdown service; external hosted call, so disabled by default |
| Firecrawl | Self-hosted adapter only | Strong crawler/Markdown tool, but cloud service is not a default dependency |
| Tavily | Not default | Paid/credit-based service despite useful include/exclude domain API |
| Exa | Not default | Has free tier but paid beyond quota; do not rely on it |
| Google Custom Search API | Not default | Not aligned with free/open-source-first constraint |

Reference links for future maintainers:

- Jina Reader: https://github.com/jina-ai/reader
- SearXNG Search API: https://docs.searxng.org/dev/search_api.html
- Firecrawl: https://github.com/firecrawl/firecrawl
- Firecrawl self-hosting: https://docs.firecrawl.dev/contributing/self-host
- Tavily Search API: https://docs.tavily.com/documentation/api-reference/endpoint/search
- Exa pricing: https://exa.ai/pricing

## 5. Requirements

### R1. Redirect resolution

The system should resolve common redirect links into real article URLs.

Must support:

- Google News RSS links.
- Bing News links where final URL can be obtained by normal redirects or known query parameters.
- Generic redirect query parameters such as `url`, `u`, `q`, `target`, `target_url`, `redirect_url`, `articleUrl`, `canonicalUrl`.
- Normal HTTP 301/302 redirects with safe hop validation.

Must not:

- Follow unsafe schemes.
- Follow internal/private network targets.
- Exceed bounded redirect depth.
- Treat a failed resolution as a hard pipeline failure.

Failure behavior:

- Return original URL with a `resolution_status` such as `original`, `resolved`, `unsafe`, `timeout`, `error`.
- Never crash the whole news search flow due to one bad link.

### R2. URL canonicalization

The system should normalize URLs to improve deduplication and caching.

Canonicalization should:

- Lowercase scheme and hostname.
- Remove fragment.
- Remove common tracking parameters: `utm_*`, `fbclid`, `gclid`, `yclid`, `mc_cid`, `mc_eid`, `spm`, `from`, `ref`, `ref_src`.
- Sort remaining query parameters.
- Normalize empty path to `/`.
- Keep meaningful query parameters, because some sites use them as content IDs.

### R3. Domain policy

The system should be able to score or filter URLs after the real domain is known.

Policy modes:

- `off`: no domain policy.
- `soft`: score and reorder, but do not delete unknown domains.
- `strict`: remove blocklisted domains and require allowlist for specific search modes.

Default mode: `soft`.

Recommended domain groups:

- `prefer_tech_domains`: `github.com`, `stackoverflow.com`, `docs.python.org`, `pytorch.org`, `godotengine.org`, `readthedocs.io`, `microsoft.com`, `developer.mozilla.org`, `arxiv.org`.
- `prefer_official_domains`: official project/vendor docs for technical queries.
- `block_domains`: user-configurable; default should be conservative.
- `penalty_patterns`: login pages, account pages, tracking-heavy URLs, obvious aggregator mirrors.

The policy must be query-aware:

- Technical/coding queries: prefer official docs, GitHub, Stack Overflow, package docs.
- News/current-event queries: prefer original publisher/source over repost aggregators.
- General learning queries: prefer readable, stable, source-traceable pages.

### R4. Post-resolution deduplication

Deduplication should happen after canonical URL generation.

Dedup order:

1. Deduplicate by canonical URL.
2. Then deduplicate by normalized title if canonical URL is unavailable.
3. Preserve source trace fields so the user can see original link and resolved link.

Required item fields after this stage:

```python
{
    "link": "original search/RSS URL",
    "resolved_link": "real final URL if available",
    "canonical_url": "normalized URL used for dedup/cache",
    "domain": "resolved hostname",
    "resolution_status": "resolved|original|unsafe|timeout|error",
}
```

### R5. Reader backend selection

Reader selection should be layered and bounded.

Default order:

1. Local reader: trafilatura.
2. Local reader: readability-lxml.
3. Local reader: raw paragraph text.
4. Optional Jina Reader fallback when explicitly enabled.
5. Optional self-hosted Firecrawl adapter when explicitly configured.

Reader outputs should always be truncated by existing article budgets.

Recommended method labels:

- `local_trafilatura`
- `local_readability`
- `local_raw_p`
- `jina_reader`
- `firecrawl_self_hosted`
- `unavailable`

### R6. Source trace and UI explainability

The source block should show enough information to debug web results without overwhelming the user.

Recommended trace format:

```text
【联网检索】
查询：...
1. Title | Source | Date | 正文已读｜local_trafilatura
   原始链接：...
   真实链接：...
   域名：...
   状态：resolved / canonical-dedup / filtered
```

UI should eventually expose only a few user-facing switches:

- Resolve real URLs.
- Prefer trusted domains.
- Enable Jina Reader fallback.
- Enable self-hosted SearXNG provider.

Do not expose every low-level URL policy option in the main UI.

## 6. Proposed modules

```text
src/news/
  url_normalizer.py        # parse redirect params, canonicalize URLs, extract domain
  domain_policy.py         # score/filter by real domain and query intent
  link_resolver.py         # keep existing Google News support; delegate generic logic
  rss_fetcher.py           # call resolve/canonicalize/dedup after fetch
  article_fetcher.py       # keep local reader and SSRF guard; later add reader backends
  readers/
    __init__.py
    local_reader.py        # wrapper over existing extraction stack
    jina_reader.py         # optional hosted fallback, disabled by default
    firecrawl_reader.py    # optional self-hosted adapter only
  search_sources/
    __init__.py
    searxng_source.py      # optional configured search provider
```

Do not create all modules at once. Add them phase by phase.

## 7. Configuration design

Target configuration shape:

```yaml
news:
  resolve_redirects: true
  resolve_top_n: 10
  max_redirect_depth: 5
  url_timeout_seconds: 5

  dedup:
    enabled: true
    key: canonical_url

  domain_policy:
    enabled: true
    mode: soft
    prefer_tech_domains:
      - github.com
      - stackoverflow.com
      - docs.python.org
      - pytorch.org
      - godotengine.org
      - readthedocs.io
      - developer.mozilla.org
      - arxiv.org
    block_domains: []
    penalty_patterns:
      - login
      - account
      - signin

  reader:
    backend_order:
      - local
      - jina_optional
      - firecrawl_self_hosted_optional
    enable_jina_fallback: false
    enable_firecrawl_self_hosted: false
    firecrawl_base_url: ""

  search_sources:
    enable_searxng: false
    searxng_base_url: ""
```

Initial implementation can keep constants in code if config plumbing is too large, but the final target should be configurable.

## 8. Implementation phases

### Phase 0 — Planning document

Deliverable:

- `docs/WEB_AGENT_REDIRECT_PLAN.md`

No code changes.

Acceptance:

- Requirements, non-goals, safety boundaries, module split, tests, and version roadmap are explicit.

### Phase 1 — URL normalizer and canonical dedup

Deliverables:

- Add `src/news/url_normalizer.py`.
- Extend `src/news/link_resolver.py` to return/attach canonical metadata.
- Change `src/news/rss_fetcher.py` so post-resolution dedup uses `canonical_url`.
- Update source trace fields.
- Add unit tests.

Acceptance:

- Two different redirect URLs pointing to the same final article are fetched once.
- Tracking-only URL differences collapse to one canonical URL.
- Unsafe/private targets are rejected.
- Failed resolution falls back safely.

### Phase 2 — Domain policy scoring/filtering

Deliverables:

- Add `src/news/domain_policy.py`.
- Integrate domain scoring into item sorting and article-fetch candidate selection.
- Add domain policy tests.

Acceptance:

- Technical queries prefer official docs/GitHub/Stack Overflow-like domains.
- Unknown domains are not deleted in soft mode.
- Blocklisted domains do not enter article fetching.

### Phase 3 — Reader backend interface and optional Jina fallback

Deliverables:

- Add `src/news/readers/` abstraction.
- Keep local reader as default.
- Add Jina fallback behind explicit config flag.
- Add tests ensuring Jina is disabled by default.

Acceptance:

- Existing local extraction behavior remains unchanged by default.
- Enabling Jina only affects failed local extraction cases.
- Reader output still obeys max bytes/max chars/token budgets.

### Phase 4 — Optional SearXNG provider

Deliverables:

- Add `src/news/search_sources/searxng_source.py`.
- Support `SEARXNG_BASE_URL` or config value.
- Keep RSS providers as fallback.

Acceptance:

- No SearXNG config means no behavior change.
- Configured SearXNG can return normalized item dicts.
- 403/disabled JSON on public instances fails gracefully.

### Phase 5 — Optional self-hosted Firecrawl adapter

Deliverables:

- Add Firecrawl adapter only for self-hosted base URL.
- Do not add Firecrawl Cloud API key requirement.

Acceptance:

- Empty base URL means Firecrawl is disabled.
- Local/self-hosted endpoint can return Markdown into the same reader-result shape.

## 9. Test plan

Recommended tests:

```text
tests/test_url_normalizer.py
  - extract real URL from url/u/q/target/redirect_url params
  - strip tracking params
  - preserve meaningful query params
  - canonical URL equality for tracking-only differences
  - reject file://, ftp://, localhost, private IPs

tests/test_link_resolver.py
  - Google News HTML extraction still works
  - generic redirect param extraction works
  - redirect depth limit works via monkeypatch
  - timeout/error returns original URL with error status

tests/test_news_redirect_dedup.py
  - two search results with same final canonical URL dedup to one item
  - source trace keeps original and resolved URLs

tests/test_domain_policy.py
  - tech query prefers official/project domains
  - blocklist filters before article fetching
  - soft mode keeps unknown domains but lowers score

tests/test_reader_backends.py
  - local reader remains default
  - Jina fallback disabled by default
  - Firecrawl adapter requires explicit self-hosted base URL
  - reader output is truncated to budget
```

CI gates should remain:

```bash
ruff check .
pytest
python tools/package_project_helper.py
```

## 10. Performance constraints

The feature should reduce unnecessary web work, not increase it.

Limits:

- Only resolve top N candidates, configurable.
- Cache by canonical URL, not raw redirect URL.
- Keep article cache TTL and max size.
- Avoid repeated reader calls for duplicate canonical URLs.
- Never perform unbounded recursive crawling.

Expected improvement:

- Fewer duplicate article fetches.
- Better article selection.
- Cleaner source trace.
- More predictable token cost.

## 11. Version roadmap

```text
v0.7.0  Redirect resolver + canonical URL dedup
v0.7.1  Domain policy scoring/filtering
v0.7.2  Reader backend interface + optional Jina fallback
v0.7.3  Optional SearXNG provider
v0.7.4  Optional self-hosted Firecrawl adapter
```

Implementation rule:

- One phase per PR/commit group.
- Each phase must include tests.
- Do not add paid API dependency unless a later requirement explicitly changes this plan.
- Update `docs/NEWS_PIPELINE.md` after each code phase.

## 12. First code step after this document

Start with Phase 1 only.

Suggested first patch:

1. Add `src/news/url_normalizer.py`.
2. Add tests for canonicalization and redirect-param extraction.
3. Wire canonical URL into `fetch_news_items()` after current `resolve_news_link()`.
4. Move dedup after resolution for resolved top N.
5. Preserve backward compatibility for existing item fields.

Do not add Jina, SearXNG, or Firecrawl in the first patch.
