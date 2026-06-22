# API Frontend Migration

This document is the contract map for migrating the Streamlit business baseline
to the React frontend. React should prefer these APIs over local fake state.

## Principles

- Backend owns business state, file writes, model calls, memory safety, and audit logs.
- React owns presentation, interaction, optimistic loading, and explicit confirmations.
- File-writing APIs must expose preview/commit or clear side-effect names.
- Long-running model flows should stream or expose staged APIs instead of one opaque button.

## Current API Surface

| Area | Endpoint | Status | Side effect | Frontend use |
| --- | --- | --- | --- | --- |
| Health | `GET /health` | Existing | Read-only | API status |
| Runtime | `GET /runtime/settings` | P0 implemented | Read-only | Hydrate role, mode, model, performance, memory settings |
| Runtime | `PATCH /runtime/settings` | P0 implemented | Writes `config/frontend_settings.yaml` and runtime mode state | Persist sidebar settings |
| Roles | `GET /roles` | P0 implemented | Read-only | Role selector metadata |
| Roles | `GET /roles/{role_id}` | P0 implemented | Read-only | Role prompt preview |
| Memory | `GET /memory` | P0 implemented | Read-only | Memory mode, safe mode, focus/progress/summary previews |
| RAG | `GET /rag/status` | Existing | Read-only | Knowledge base status |
| RAG | `POST /rag/upload` | Existing | Writes uploaded docs and index | Upload and index docs |
| RAG | `POST /rag/index` | Existing | Writes index | Rebuild index from paths |
| RAG | `POST /rag/query` | Existing | Read-only | Source inspector |
| Chat | `POST /chat` | Existing | Writes session logs | Non-streaming single chat fallback |
| Chat | `POST /chat/stream` | P0 planned/next | Writes session logs after completion | Streaming single chat |
| Memory | `POST /memory/preview` | Existing | Read-only preview | Generic memory write preview |
| Memory | `POST /memory/commit` | Existing | Writes memory files when allowed | Generic memory commit |
| Sessions | `GET /sessions` | Existing | Read-only | Session list |
| Sessions | `POST /sessions/{session_id}/flush` | Existing | Flushes current session log | Manual flush |
| Tools | `GET /tools` | Existing | Read-only | Tool registry |
| Tools | `POST /tools/{tool_name}/preview` | Existing | Read-only preview | Tool dry run |
| Tools | `POST /tools/{tool_name}/call` | Existing | Tool-dependent, audited | Confirmed tool execution |
| Workflows | `GET /workflows/runs` | Existing | Read-only | Workflow timeline |
| Workflows | `GET /workflows/runs/{run_id}` | Existing | Read-only | Workflow detail |
| Assets | `GET /assets/*` | Existing | Read-only | Role avatars and UI media |
| WeChat | `GET /wechat` | Implemented compatibility route | Read-only | Current group state |
| WeChat | `POST /wechat/reset` | Implemented compatibility route | Archives/clears group files | New group |
| WeChat | `POST /wechat/mark-read` | Implemented compatibility route | Clears unread file | Mark read |
| WeChat | `POST /wechat/opening` | Implemented compatibility route | Writes group opening | Generate group opening |
| WeChat | `POST /wechat/message` | Implemented compatibility route | Writes user/group messages | Non-streaming group reply |
| WeChat | `POST /wechat/search` | Implemented compatibility route | Read-only | Search group transcript |
| News | `POST /news/lookup` | Implemented compatibility route | Read-only network fetch | Search web/news for single chat context |
| News | `POST /news/runs` | Sealed | Creates and immediately returns a server-owned `NewsRun` ID | Start a recoverable news workflow |
| News | `POST /news/runs/{run_id}/search` | Sealed | Network fetch; persists results on the existing Run | Stage 1 search |
| News | `POST /news/runs/{run_id}/enrich` | Sealed | Reads article text when runtime allows | Stage 2 article enrichment |
| News | `POST /news/runs/{run_id}/digest` | Sealed | Model call; persists digest and sources | Stage 3 digest |
| News | `POST /news/runs/{run_id}/discuss` | Sealed | Model call and atomic Group bundle write | Stage 4 group discussion |
| News | `GET /news/runs/{run_id}` | Sealed | Read-only | Restore authoritative stage after refresh or failure |
| News | `GET /news/runs` | Sealed | Read-only | Recent NewsRun recovery |
| News | `/news/round`, `/news/search`, `/news/enrich`, `/news/digest`, `/news/discuss` | Retired (`410`) | None | Legacy clients must migrate to NewsRun IDs |

## Gaps To Close

| Priority | Endpoint | Purpose | Notes |
| --- | --- | --- | --- |
| P0 | `POST /chat/stream` | Stream single chat | SSE events: `route`, `rag`, `token`, `usage`, `done`, `error` |
| P0 | `POST /after-session/preview` | Generate after-session candidates | Should not write memory; can call LLM |
| P0 | `POST /after-session/commit` | Commit selected after-session updates | Must respect `safe_mode` and `memory_mode` |
| P0 | `GET /wechat/state` | Canonical WeChat state route | Alias/replace `GET /wechat` |
| P0 | `GET /wechat/thread` | Group thread only | Read-only |
| P0 | `GET /wechat/unread` | Unread messages only | Read-only |
| P0 | `POST /wechat/read` | Canonical mark-read route | Side effect: clears unread |
| P0 | `POST /wechat/messages` | Canonical non-streaming group reply | Side effect: writes group files |
| P0 | `POST /wechat/messages/stream` | Streaming group reply | SSE token stream plus final state |
| P0 | `POST /wechat/memory/preview` | Group memory candidates | Preview only |
| P0 | `POST /wechat/memory/commit` | Commit group memory candidates | Must respect memory safety |
| P1 | `GET /sessions/{session_id}` | Session detail | Read-only |
| P1 | `POST /sessions/{session_id}/archive` | Archive session | File move/write |
| P1 | `GET /stats` | Usage/study stats | Read-only |
| P1 | `POST /stats/reset` | Reset stats | Destructive write, needs confirmation |
| P1 | `GET /health/full` | Deep health check | Read-only, can inspect provider/config |
| P1 | `GET /rag/documents` | Indexed document list | Read-only |
| P1 | `DELETE /rag/documents/{document_id}` | Remove indexed doc | Destructive write, needs confirmation |
| P1 | `POST /rag/rebuild` | Rebuild index | Writes index |

## Streamlit Entrypoints To Migrate

| Streamlit file/function | Target API |
| --- | --- |
| `src/ui/sidebar.py` runtime controls | `/runtime/settings`, `/roles`, `/memory` |
| `src/ui/chat_panel.py` single chat | `/chat/stream` |
| `src/ui/after_session_panel.py` after-session flow | `/after-session/preview`, `/after-session/commit` |
| `src/ui/wechat_panel.py` group lifecycle and messages | `/wechat/state`, `/wechat/thread`, `/wechat/messages`, `/wechat/messages/stream` |
| `src/ui/wechat_news_panel.py` staged news round | `/news/runs`, then `/news/runs/{run_id}/*` |
| `src/ui/rag_panel.py` knowledge base controls | `/rag/*`, future `/rag/documents` |

## Confirmation Rules

- Read-only: no confirmation needed.
- Writes session/chat logs: allowed from normal chat actions.
- Writes memory files: require preview/commit or an explicit user confirmation in UI.
- Deletes/resets/archive actions: require explicit button intent and clear labels.
- Network article reads: respect `safe_mode` and runtime profile; surface skipped reasons.

## NewsRun Final Seal

- Creation and search are separate requests, so the client owns the real Run ID before any network work starts.
- Search failures keep the same Run at `created/failed`; retry reacquires the stage lease instead of creating an orphan Run.
- Later stages accept only the Run ID. The server owns items, digest, source block, discussion, warnings, and stage transitions.
- The React controller restores `GET /news/runs/{run_id}` after a known-Run stage failure and immediately stores automatic enrich results before digest.
- Discuss reserves `group_thread_id` on the NewsRun before generation and the atomic Group bundle write. A retry therefore cannot drift to a different GroupThread after a process interruption.
