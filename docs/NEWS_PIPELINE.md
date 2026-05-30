# News Pipeline

Multi-source news aggregation pipeline: search providers → resolve → canonicalize → domain policy → dedup → reader backends → digest → discuss → trace.

## Pipeline Stages

```text
User query
    │
    ▼
1. Multi-source search/fetch
   ├── Optional SearXNG JSON provider (disabled by default)
   ├── Google News RSS
   ├── Bing News RSS
   └── RSSHub (domestic Chinese sources)
    │
    ▼
2. Pre-dedup + sort candidate pool
   └── Keep a modest over-fetch window for redirect/canonical dedup
    │
    ▼
3. Link resolution + URL metadata
   ├── Generic redirect params: url/u/q/target/redirect_url
   ├── Google News redirect HTML extraction
   └── URL metadata: resolved_link/canonical_url/domain/resolution_status
    │
    ▼
4. Domain policy scoring/filtering
   ├── Tech intent prefers docs/GitHub/StackOverflow/official sources
   ├── Unknown domains are kept in soft mode
   └── Login/account/auth pages are hard-blocked before article fetching
    │
    ▼
5. Canonical URL dedup + truncate
   └── Dedup by canonical_url first, then title fallback
    │
    ▼
6. Article reader backends (top 5 pages, max 5000 chars each)
   ├── Local reader: trafilatura
   ├── Local reader: readability-lxml
   ├── Local reader: raw <p>/HTMLParser
   ├── Optional Firecrawl-compatible fallback (disabled by default)
   └── Optional Jina Reader fallback (disabled by default)
    │
    ▼
7. Digest generation (LLM-summarized)
    │
    ▼
8. Group discussion (4 roles discuss the news)
    │
    ▼
9. Source block written to chat transcript
```

## Stage Detail

### 1. Multi-source Search/Fetch

`src/news/rss_fetcher.py` builds a candidate pool from multiple sources:

- Optional SearXNG JSON provider
- Google News: `https://news.google.com/rss/search?q={query}&hl=zh-CN`
- Bing News: `https://www.bing.com/news/search?q={query}&format=rss`
- RSSHub: Configurable domestic sources
- 600-second article cache per query

SearXNG is opt-in and fail-soft:

```bash
NEWS_ENABLE_SEARXNG=true
SEARXNG_BASE_URL=http://127.0.0.1:8080
```

Behavior:

- If SearXNG is disabled, no SearXNG request is sent.
- If `SEARXNG_BASE_URL` is missing or unsafe, SearXNG returns no items.
- If the instance disables JSON output, returns non-JSON, 403, or times out, the pipeline silently falls back to RSS.
- SearXNG results are normalized into the same news item schema and then enter the same redirect/canonical/domain-policy/dedup flow.

### 2. Pre-dedup

Title normalization + raw-link/title pre-dedup keeps a candidate pool before redirect resolution. The pool is intentionally larger than the final max item count, because multiple search-engine URLs may point to the same final article.

### 3. Link Resolution + URL Metadata

`src/news/link_resolver.py` resolves redirect URLs and delegates pure URL normalization to `src/news/url_normalizer.py`.

Each news item should carry:

```python
{
    "link": "original search/RSS URL",
    "resolved_link": "real final URL when available",
    "canonical_url": "normalized URL used for dedup/cache",
    "domain": "resolved hostname",
    "resolution_status": "resolved|original|unsafe|timeout|error|pending",
}
```

Resolution supports:

- Generic redirect parameters such as `url`, `u`, `q`, `target`, `target_url`, `redirect_url`, `articleUrl`, `canonicalUrl`
- Existing Google News redirect extraction
- Fail-soft fallback to original URL metadata

### 4. Domain Policy

`src/news/domain_policy.py` provides query-aware soft scoring and hard blocking.

Policy behavior:

- Technical queries prefer official/project sources such as GitHub, Stack Overflow, Python docs, Godot docs, Microsoft docs, arXiv, and Hugging Face.
- General/news queries may prefer direct publisher domains when available.
- Unknown domains are not removed in soft mode.
- Login/account/auth/OAuth pages are hard-blocked and do not enter article fetching.

Each item can carry:

```python
{
    "domain_policy": {
        "intent": "tech|general",
        "score": 35,
        "blocked": False,
        "reasons": ["prefer-tech-domain"],
    }
}
```

### 5. Canonical URL Dedup

After link resolution and domain policy annotation, items are deduplicated by `canonical_url`. If no canonical URL is available, normalized title is used as a fallback.

Canonicalization removes common tracking parameters such as `utm_*`, `fbclid`, `gclid`, `spm`, `ref`, and `ref_src`, then sorts the remaining query parameters. Meaningful query parameters are preserved.

### 6. Article Reader Backends

`src/news/article_fetcher.py` handles safe network fetching and reader backend orchestration. Reader implementations live under `src/news/readers/`:

- `base.py`: shared `ReaderResult`
- `local_reader.py`: local `trafilatura → readability-lxml → HTMLParser` extraction
- `firecrawl_reader.py`: optional self-hosted Firecrawl-compatible fallback
- `jina_reader.py`: optional hosted Jina Reader fallback

Default behavior remains local-first and local-only.

Firecrawl-compatible fallback is disabled unless explicitly enabled:

```bash
NEWS_ENABLE_FIRECRAWL_READER=true
FIRECRAWL_BASE_URL=http://127.0.0.1:3002
# FIRECRAWL_API_KEY=optional
```

Jina Reader is disabled unless explicitly enabled:

```bash
NEWS_ENABLE_JINA_READER=true
```

Fallback order:

```text
local reader
→ Firecrawl-compatible reader, if enabled
→ Jina Reader, if enabled
```

Important boundaries:

- Firecrawl/Jina fallback is only attempted after local extraction fails.
- Firecrawl/Jina fallback is never called by default.
- Unsafe or non-public HTTP(S) URLs are rejected before hosted reader calls.
- Reader output still obeys max character budgets.
- Domain policy gate still applies before article reading; hard-blocked pages get `域名策略过滤，未读取正文`.

Method label tracked per article for quality monitoring:

- `本地 trafilatura`
- `本地 readability-lxml`
- `本地 HTMLParser`
- `Firecrawl`
- `Jina Reader`

### 7. Digest

`src/news/digest.py` — LLM generates a structured digest with:

- Article coverage summary (which articles were used)
- Key points from each source
- URL resolution status and real-domain metadata where available
- Token-bounded by `news_digest_max_tokens(performance_mode)`

### 8. Discussion

`wechat_generator.py:generate_wechat_news_discussion()` — 4 characters discuss the digest:

- Bound by `news_discussion_max_tokens(performance_mode)`
- Each character references specific news points
- Group state synced after discussion

### 9. Source Tracing

After each news round, a source block is appended to the group chat transcript:

```text
【联网检索】
查询：xxx
1. Title
   来源：Source｜Date｜Body status
   域名：example.com｜解析：resolved
   原始链接：news.google.com
   真实链接：example.com
```

This ensures all discussion claims are traceable to their sources and makes redirect/canonical dedup behavior visible during debugging.

## Setup Guide

Detailed setup instructions are in:

```text
docs/WEB_SEARCH_SETUP.md
```

## UI Flow

The entry page (`wechat_panel.py`) provides a 4-phase stepper:

1. **Search** — Enter query, configure max articles
2. **Fetch articles** — Read page text (optional)
3. **Generate digest** — LLM summary
4. **Discuss in group** — 4-role news discussion

Each phase is a separate button enabling incremental progress visibility.

## Roadmap

- v0.7.0: Redirect resolver + canonical URL dedup
- v0.7.1: Domain policy scoring/filtering
- v0.7.2: Reader backend interface + optional Jina fallback
- v0.7.3: Optional SearXNG provider
- v0.7.4: Optional self-hosted Firecrawl adapter
