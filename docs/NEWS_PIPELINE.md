# News Pipeline

Multi-source news aggregation pipeline: search → resolve → canonicalize → dedup → extract → digest → discuss → trace.

## Pipeline Stages

```
User query
    │
    ▼
1. Multi-source RSS fetch
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
4. Canonical URL dedup + truncate
   └── Dedup by canonical_url first, then title fallback
    │
    ▼
5. Article text extraction (top 5 pages, max 5000 chars each)
   ├── trafilatura (primary)
   ├── readability-lxml (fallback)
   └── raw <p> text (last resort)
    │
    ▼
6. Digest generation (LLM-summarized)
    │
    ▼
7. Group discussion (4 roles discuss the news)
    │
    ▼
8. Source block written to chat transcript
```

## Stage Detail

### 1. RSS Fetch

`src/news/rss_fetcher.py` — parallel multi-source fetch:

- Google News: `https://news.google.com/rss/search?q={query}&hl=zh-CN`
- Bing News: `https://www.bing.com/news/search?q={query}&format=rss`
- RSSHub: Configurable domestic sources
- 600-second article cache per query

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

### 4. Canonical URL Dedup

After link resolution, items are deduplicated by `canonical_url`. If no canonical URL is available, normalized title is used as a fallback.

Canonicalization removes common tracking parameters such as `utm_*`, `fbclid`, `gclid`, `spm`, `ref`, and `ref_src`, then sorts the remaining query parameters. Meaningful query parameters are preserved.

### 5. Article Extraction

`src/news/article_fetcher.py` — layered extraction with SSRF protection:

- **Trafilatura**: Fast, accurate extraction for well-formed pages
- **Readability**: Better for complex layouts
- **Raw text**: `<p>` tag concatenation as last resort

Method label tracked per article for quality monitoring.

### 6. Digest

`src/news/digest.py` — LLM generates a structured digest with:

- Article coverage summary (which articles were used)
- Key points from each source
- URL resolution status and real-domain metadata where available
- Token-bounded by `news_digest_max_tokens(performance_mode)`

### 7. Discussion

`wechat_generator.py:generate_wechat_news_discussion()` — 4 characters discuss the digest:

- Bound by `news_discussion_max_tokens(performance_mode)`
- Each character references specific news points
- Group state synced after discussion

### 8. Source Tracing

After each news round, a source block is appended to the group chat transcript:

```
【联网检索】
查询：xxx
1. Title
   来源：Source｜Date｜Body status
   域名：example.com｜解析：resolved
   原始链接：news.google.com
   真实链接：example.com
```

This ensures all discussion claims are traceable to their sources and makes redirect/canonical dedup behavior visible during debugging.

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
