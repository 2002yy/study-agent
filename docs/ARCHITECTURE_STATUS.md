# Architecture Status

This file is the single source of truth for migration status. Other planning
documents must link here instead of maintaining competing status tables.

Updated: 2026-07-01

| Vertical slice | Status | Authoritative owner |
| --- | --- | --- |
| Chat/Session | **sealed** | FastAPI services + SQLite + `chatController` |
| Pedagogy protocol | **sealed** | `PedagogyEngine` + per-turn plan + SQLite learning state |
| GroupThread | **sealed** | Group service/repository + `groupChatController` |
| NewsRun | **sealed** | News service/repository + `newsController` |
| ToolRun | **sealed** | Tool service/repository + `toolController` |
| MemoryTransaction | **sealed** | `MemoryRun` + hash-locked commit + `memoryController` |
| RAG/KnowledgeBase | **sealed** | durable query/upload/rebuild runs + KB document lifecycle |
| WebLookupRun | **sealed** | SQLite repository + `WebLookupService` + `webLookupController` |
| AppShell | **partial** | Feature controllers exist; `App.tsx` remains orchestration-heavy |
| Compatibility API | **temporary** | `src/api/__init__.py` re-exports during migration |
| Streamlit | **legacy compatibility** | `app.py` and `src/ui/*`; not the primary architecture |

## Required execution order

The Socratic-mode upgrade is complete: the UI label remains `苏格拉底`, while
the protocol is internally identified as `socratic_rediscovery`. Chat planning
now happens before evidence disclosure; `ChatThread.learning_state` owns the
cross-turn phase and `ChatTurn.pedagogy_snapshot` explains each move.

1. **P0 — Web alignment (complete):** WebSearchGateway, ArticleReader,
   evidence levels, deadlines, durable WebLookupRun, service/controller, and
   removal of `src.api` reverse dependencies.
2. **P1 — MemoryTransaction (complete):** SQLite repository/service,
   `/memory-runs`, controller, preview-hash consistency, display-only panel.
3. **P2 — RAG/KnowledgeBase (complete):** durable query/upload/rebuild runs,
   controllers, document lifecycle, deletion and monotonic index versioning.
4. **P3 — Shell convergence (next):** server query cache, settings/role/workflow
   controllers, reduce `App.tsx`, extract AppShell, retire compatibility exports,
   and decide final Streamlit removal.
