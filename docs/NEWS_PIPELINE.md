# News Pipeline

Multi-source news aggregation pipeline: search → fetch → extract → digest → discuss → trace.

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
2. Dedup + sort + truncate (max 10 items)
    │
    ▼
3. Link resolution (top N = resolve_top_n, bounded)
    │
    ▼
4. Article text extraction (top 5 pages, max 5000 chars each)
   ├── trafilatura (primary)
   ├── readability-lxml (fallback)
   └── raw <p> text (last resort)
    │
    ▼
5. Digest generation (LLM-summarized)
    │
    ▼
6. Group discussion (4 roles discuss the news)
    │
    ▼
7. Source block written to chat transcript
```

## Stage Detail

### 1. RSS Fetch

`src/news/rss_fetcher.py` — parallel multi-source fetch:

- Google News: `https://news.google.com/rss/search?q={query}&hl=zh-CN`
- Bing News: `https://www.bing.com/news/search?q={query}&format=rss`
- RSSHub: Configurable domestic sources
- 600-second article cache per query

### 2. Dedup

Title normalization + set-based dedup. Per-query cache (10 min TTL).

### 3. Link Resolution

`src/news/link_resolver.py` — resolves Google News redirect URLs to actual article URLs. Only resolves top N items (configured via `resolve_top_n`).

### 4. Article Extraction

`src/news/article_fetcher.py` — layered extraction with SSRF protection:

- **Trafilatura**: Fast, accurate extraction for well-formed pages
- **Readability**: Better for complex layouts
- **Raw text**: `<p>` tag concatenation as last resort

Method label tracked per article for quality monitoring.

### 5. Digest

`src/news/digest.py` — LLM generates a structured digest with:

- Article coverage summary (which articles were used)
- Key points from each source
- Token-bounded by `news_digest_max_tokens(performance_mode)`

### 6. Discussion

`wechat_generator.py:generate_wechat_news_discussion()` — 4 characters discuss the digest:

- Bound by `news_discussion_max_tokens(performance_mode)`
- Each character references specific news points
- Group state synced after discussion

### 7. Source Tracing

After each news round, a source block is appended to the group chat transcript:

```
【联网检索】
查询：xxx
1. Title | Source | Date | Body status
   URL
```

This ensures all discussion claims are traceable to their sources.

## UI Flow

The entry page (`wechat_panel.py`) provides a 4-phase stepper:

1. **Search** — Enter query, configure max articles
2. **Fetch articles** — Read page text (optional)
3. **Generate digest** — LLM summary
4. **Discuss in group** — 4-role news discussion

Each phase is a separate button enabling incremental progress visibility.
