# Architecture Status

This file is the single source of truth for migration status. Other planning
documents must link here instead of maintaining competing status tables.

Updated: 2026-06-30

| Vertical slice | Status | Authoritative owner |
| --- | --- | --- |
| Chat/Session | **sealed** | FastAPI services + SQLite + `chatController` |
| GroupThread | **sealed** | Group service/repository + `groupChatController` |
| NewsRun | **sealed** | News service/repository + `newsController` |
| ToolRun | **sealed** | Tool service/repository + `toolController` |
| MemoryTransaction | **next** | Planned P1 vertical slice |
| RAG/KnowledgeBase | **pending** | Planned P2 vertical slices |
| WebLookupRun | **partial** | `WebLookupService` + `webLookupController`; durable run storage pending |
| AppShell | **partial** | Feature controllers exist; `App.tsx` remains orchestration-heavy |
| Compatibility API | **temporary** | `src/api/__init__.py` re-exports during migration |
| Streamlit | **legacy compatibility** | `app.py` and `src/ui/*`; not the primary architecture |

## Required execution order

1. **P0 — Web alignment:** WebSearchGateway, ArticleReader, evidence levels,
   deadlines, WebLookup service/controller, and removal of `src.api` reverse
   dependencies.
2. **P1 — MemoryTransaction:** SQLite schema, repository, service,
   `/memory-runs`, controller, preview-hash consistency, display-only panel.
3. **P2 — RAG/KnowledgeBase:** separate query/upload/rebuild state models,
   controllers, document lifecycle, index versioning.
4. **P3 — Shell convergence:** server query cache, settings/role/workflow
   controllers, reduce `App.tsx`, extract AppShell, retire compatibility exports,
   and decide final Streamlit removal.
