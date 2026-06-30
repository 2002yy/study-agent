# Architecture

> Historical Streamlit architecture reference. The primary runtime is now
> React + FastAPI; current migration truth lives in
> [ARCHITECTURE_STATUS.md](ARCHITECTURE_STATUS.md).

```
┌─────────────────────────────────────────────────────────────┐
│                     Streamlit Runtime                        │
│  app.py — entry point, fragment orchestration               │
├─────────────────────────────────────────────────────────────┤
│  src/ui/                                                     │
│  ├── sidebar.py           Settings, modes, export           │
│  ├── status_bar.py        Status cards, stats, perf         │
│  ├── chat_panel.py        Single-chat UI                    │
│  ├── wechat_panel.py      Group-chat UI + news phases       │
│  ├── after_session_panel.py  Post-session review            │
│  ├── session_state.py     init / refresh helpers            │
│  └── theme.py             Catppuccin dark theme             │
├─────────────────────────────────────────────────────────────┤
│  src/                                                       │
│  ├── llm_client.py        Chat / stream, auto-reconnect     │
│  ├── llm_router.py        LLM-based routing (JSON mode)     │
│  ├── context_builder.py   System prompt assembly            │
│  ├── config.py            Multi-provider config             │
│  ├── router.py            Route resolution                  │
│  ├── mode_manager.py      Runtime modes, YAML truth        │
│  ├── performance_budget.py  Max-tokens by mode              │
│  ├── role_manager.py      Role loading                      │
│  ├── model_stats.py       Usage tracking                    │
│  │                                                          │
│  ├── memory.py            File-based memory with LRU cache  │
│  ├── memory_writer.py     Structured memory updates         │
│  ├── memory_tools.py      Read/write tool functions         │
│  │                                                          │
│  ├── wechat_format.py     Text formatting, role parsing     │
│  ├── wechat_state.py      Group state I/O                   │
│  ├── wechat_generator.py  LLM generation (opening/reply/    │
│  │                         discussion)                      │
│  ├── wechat_prompt.py     Prompt template loading           │
│  ├── wechat_memory.py     Memory candidate extraction       │
│  ├── wechat_service.py    High-level orchestration          │
│  │                                                          │
│  ├── session_logger.py    Session persistence, batch flush  │
│  ├── safe_writer.py       Atomic writes, retry, backup      │
│  ├── health_check.py      Read-only health probes           │
│  └── news/                News pipeline (see NEWS_PIPELINE) │
├─────────────────────────────────────────────────────────────┤
│  config/runtime_state.yaml  — Single source of truth        │
│  memory/                    — Markdown memory files          │
│  chat/                      — Group chat transcripts        │
│  roles/                     — Role definitions              │
│  templates/                 — Prompt templates              │
└─────────────────────────────────────────────────────────────┘
```

## Layers

| Layer | Responsibility |
|---|---|
| **UI** | Streamlit fragments, user interaction, display |
| **Orchestration** | wechat_service.py ties news + memory + generation |
| **LLM** | Client, routing, context assembly, budget control |
| **Memory** | File-based, tiered context groups, safe writer |
| **News** | RSS fetch → article extraction → digest → discussion |
| **State** | YAML truth → Markdown views, synced at runtime |

## Fragment Model

`app.py` uses `@st.fragment` to isolate re-renders:

- `render_sidebar_fragment` — settings, state toggles, actions
- `render_status_fragment` — status cards, stats line
- `render_single_main_fragment` — chat UI
- `render_after_session_fragment` — post-session review

Global-affecting sidebar actions use `st.rerun()` (full page) to refresh all fragments.
