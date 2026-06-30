# Web Search Setup Guide

This guide explains how to configure the news/web-search pipeline used by Study Agent.

The safe default is local-first and RSS-first:

```env
NEWS_ENABLE_SEARXNG=false
NEWS_ENABLE_JINA_READER=false
NEWS_ENABLE_FIRECRAWL_READER=false
```

## 1. Current Pipeline

```text
User query
→ optional SearXNG search source
→ Google News RSS / Bing News RSS / RSSHub fallback
→ redirect resolution
→ canonical URL dedup
→ domain policy scoring/filtering
→ local reader extraction
→ optional Firecrawl fallback
→ optional Jina fallback
→ digest
→ group discussion
→ source trace
```

## 2. Recommended Configurations

### A. Most stable default

Use this first if you only want the existing behavior:

```env
NEWS_ENABLE_SEARXNG=false
NEWS_ENABLE_JINA_READER=false
NEWS_ENABLE_FIRECRAWL_READER=false
```

This uses RSS feeds and local article extraction only.

### B. Better search candidates with local SearXNG

Use this when you have a working local SearXNG instance:

```env
NEWS_ENABLE_SEARXNG=true
SEARXNG_BASE_URL=http://127.0.0.1:8080
NEWS_SEARXNG_CATEGORIES=news
NEWS_SOURCE_TIMEOUT_SECONDS=8
NEWS_SOURCE_MAX_ATTEMPTS=2
NEWS_ENABLE_JINA_READER=false
NEWS_ENABLE_FIRECRAWL_READER=false
```

SearXNG is used as an extra candidate source. If it returns 403, HTML, non-JSON, or times out, the pipeline falls back to RSS.

`NEWS_SEARXNG_CATEGORIES` is forwarded to SearXNG and defaults to `news`.
Search providers, redirect resolution, and selected article reads run concurrently.
`NEWS_SOURCE_TIMEOUT_SECONDS` is clamped to 1-30 seconds and
`NEWS_SOURCE_MAX_ATTEMPTS` is clamped to 1-3 attempts.

### C. Local/self-hosted extraction fallback with Firecrawl-compatible API

Use this when local trafilatura/readability extraction often fails and you have a self-hosted Firecrawl-compatible server:

```env
NEWS_ENABLE_SEARXNG=true
SEARXNG_BASE_URL=http://127.0.0.1:8080
NEWS_ENABLE_FIRECRAWL_READER=true
FIRECRAWL_BASE_URL=http://127.0.0.1:3002
# FIRECRAWL_API_KEY=your_optional_key
NEWS_ENABLE_JINA_READER=false
```

Firecrawl fallback is attempted only after local extraction fails.

### D. Hosted Jina fallback

Use this only if you accept sending public article URLs to hosted Jina Reader:

```env
NEWS_ENABLE_JINA_READER=true
```

Jina fallback is attempted only after local extraction fails and, if enabled, after Firecrawl fallback fails.

## 3. Quick SearXNG Check

Start SearXNG, then open:

```text
http://127.0.0.1:8080/search?q=python&format=json
```

Expected result: JSON containing a `results` array.

If you get 403 or HTML, JSON output is disabled on that instance. The app will still work because it falls back to RSS.

## 4. Quick Firecrawl-compatible Check

The adapter assumes a Firecrawl-compatible scrape endpoint:

```text
POST {FIRECRAWL_BASE_URL}/v1/scrape
```

With a body similar to:

```json
{
  "url": "https://example.com/article",
  "formats": ["markdown"],
  "onlyMainContent": true
}
```

The adapter reads `data.markdown`, `markdown`, `data.content`, or `content` from the JSON response.

## 5. Safety Boundaries

- SearXNG is disabled unless `NEWS_ENABLE_SEARXNG=true`.
- Firecrawl is disabled unless `NEWS_ENABLE_FIRECRAWL_READER=true`.
- Jina is disabled unless `NEWS_ENABLE_JINA_READER=true`.
- Article target URLs must be public HTTP(S) URLs.
- `file://`, localhost, loopback, private IP, and unsafe targets are rejected before hosted reader calls.
- Login/account/auth pages are filtered by domain policy before article reading.

## 6. Test Commands

```bash
ruff check src/ tests/
pytest tests/test_url_normalizer.py tests/test_news_redirect_dedup.py tests/test_domain_policy.py -v
pytest tests/test_reader_backends.py tests/test_searxng_source.py tests/test_firecrawl_reader.py -v
pytest tests/ -v
```

## 7. Suggested Validation Queries

Use these to compare source quality:

```text
python urllib.parse redirect
Godot 4 export error
OpenAI API docs
LiteCDNet remote sensing change detection
```

Check the source block for:

- `来源：SearXNG/...` if SearXNG is enabled and working.
- `正文已读｜本地 trafilatura` or similar if local extraction works.
- `正文已读｜Firecrawl` if Firecrawl fallback was used.
- `正文已读｜Jina Reader` if Jina fallback was used.
