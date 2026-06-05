# Performance

## Caching

| Cache | Location | TTL | Invalidation |
|---|---|---|---|
| Memory file reads | `memory.py:_read_text_file_cached` | LRU-64 | File signature change |
| Runtime modes | `mode_manager.py:load_runtime_modes` | 30s `@st.cache_data` | Time + write |
| Article text | `article_fetcher.py:_ARTICLE_CACHE` | 1800s | Time + LRU-32 |
| RSS results | `rss_fetcher.py:_CACHE` | 600s per query | Time |
| LLM client | `llm_client.py:_client_signature` | Session | Config change |

## Fragment Rerun Strategy

`app.py` splits the UI into `@st.fragment` boundaries:

- Sidebar settings changes → `st.rerun()` (full page) to refresh all panels
- Status bar → isolated fragment, updates independently
- Chat panel → isolated fragment, user messages only rerun here
- After-session panel → isolated fragment

This prevents unnecessary re-renders of the entire page on every interaction.

## Performance Budget

The main user-facing LLM paths have `max_tokens` bounds via `src/performance_budget.py`. Three tiers:

- **fast**: Low token consumption, shorter conversations (700 chat, 16 history lines)
- **standard**: Balanced (1100 chat, 28 history lines)  
- **deep**: Full context (1600 chat, 40 history lines)

Covered paths include single chat, WeChat opening/reply/news discussion, and news digest generation. Some auxiliary calls still rely on `llm_client.py` task defaults or environment/global defaults rather than `performance_budget.py` directly, so this is not yet a strict "every LLM call" guarantee.

## Batch Flush

`src/session_logger.py` buffers session entries and flushes in batches:

| Mode | Flush interval (entries) |
|---|---|
| fast | 4 |
| standard | 2 |
| deep | 2 |

Each flush uses `safe_write_text` for atomicity. Stale session warning at 2 hours.

## Diff Algorithm

Memory update diffing uses set-based operations (O(n)) rather than line-by-line comparison (O(n×m)), computed from `file_signature()` hashes.
