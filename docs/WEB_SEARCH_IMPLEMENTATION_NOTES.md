# Web Search Implementation Notes

## Problem addressed

The previous pipeline performed independent network work sequentially:

1. Search SearXNG.
2. Fetch each RSS source.
3. Resolve each candidate redirect.
4. Read each selected article.

With several unavailable sources, latency accumulated across every timeout and
retry. Google News HTML fallback could also select the first external `href`,
including a favicon or thumbnail, as if it were the article.

## Current design

```text
query
  -> concurrent candidate providers (SearXNG + configured RSS feeds)
  -> normalized candidates + provider relevance score
  -> pre-dedup while retaining internal sort metadata
  -> concurrent redirect resolution
  -> canonical URL dedup + domain policy
  -> concurrent reads for the selected article URLs
  -> local extraction -> optional Firecrawl -> optional Jina
  -> digest, discussion, and trace
```

The output order remains deterministic: concurrent tasks are consumed in the
configured provider/candidate order, then sorted by the existing policy.
Failures remain isolated per provider.

The built-in Bing fallback uses the standard Web Search RSS endpoint
(`/search?...&format=rss`). The former Bing News endpoint returned an HTML
search page in live verification and therefore could not be parsed as RSS.

## Open-source references

The implementation borrows design patterns, not copied source:

- [Vane (formerly Perplexica) SearXNG adapter](https://github.com/ItzCrazyKns/Vane/blob/master/src/lib/searxng.ts):
  explicit request timeout and normalized SearXNG result handling.
- [Vane search action](https://github.com/ItzCrazyKns/Vane/blob/master/src/lib/agents/search/researcher/actions/search/baseSearch.ts):
  concurrent independent searches, search-result ranking, deduplication, and a
  separate scrape phase.
- [Open WebUI SearXNG adapter](https://github.com/open-webui/open-webui/blob/main/backend/open_webui/retrieval/web/searxng.py):
  normalize provider output, retain SearXNG scores, sort by score, and apply URL
  filtering before downstream retrieval.
- [GPT Researcher retriever factory](https://github.com/assafelovic/gpt-researcher/blob/main/gpt_researcher/actions/retriever.py):
  provider selection behind a stable retriever contract.
- [GPT Researcher research workflow](https://github.com/assafelovic/gpt-researcher/blob/main/gpt_researcher/skills/researcher.py):
  deduplicate visited URLs and distinguish prefetched full text from snippets
  that still require scraping.

## Deliberate scope

Study Agent keeps its existing FastAPI `NewsRun` workflow and local-first reader
chain. It does not import a research-agent framework or add a mandatory paid
search API. SearXNG remains optional, and RSS remains a fail-soft fallback.
