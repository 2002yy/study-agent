# Architecture Status

This file is the single source of truth for migration status. Other planning
documents must link here instead of maintaining competing status tables.

Updated: 2026-07-01

| Vertical slice | Status | Authoritative owner |
| --- | --- | --- |
| Chat/Session | **sealed** | FastAPI services + SQLite + `chatController` |
| Pedagogy protocol | **partial** | protocol V2 integrated; semantic understanding evaluation remains |
| GroupThread | **sealed** | Group service/repository + `groupChatController` |
| NewsRun | **sealed** | News service/repository + `newsController` |
| ToolRun | **sealed** | Tool service/repository + `toolController` |
| MemoryTransaction | **sealed** | `MemoryRun` + hash-locked commit + `memoryController` |
| RAG/KnowledgeBase | **sealed** | durable query/upload/rebuild runs + KB document lifecycle |
| WebLookupRun | **sealed** | SQLite repository + `WebLookupService` + `webLookupController` |
| AppShell | **sealed** | composition-only `App.tsx`; `AppShell` + feature controllers |
| Compatibility API | **legacy shim** | frozen `src/api/__init__.py` attributes for old tests/clients |
| Streamlit | **legacy compatibility** | `app.py` and `src/ui/*`; not the primary architecture |

## Completed execution order

1. **P0 — Web alignment:** gateway/reader boundaries, structured evidence,
   durable WebLookupRun, service/controller ownership.
2. **P1 — MemoryTransaction:** SQLite repository/service, `/memory-runs`,
   hash-locked commit, controller and display-only panel.
3. **P2 — RAG/KnowledgeBase:** durable query/upload/rebuild runs, controllers,
   document lifecycle and monotonic index versions.
4. **P3 — Shell convergence:** shared server query cache,
   settings/role/workflow controllers, composition-only `App.tsx`, extracted
   `AppShell`, frozen compatibility shim and explicit Streamlit legacy status.

## Pedagogy status

Pedagogy V2 is integrated but deliberately not sealed. Socratic progression
requires a validated explanation rather than keyword claims. Explicit mode
intent overrides sticky routing; protocol payloads are isolated and restored
per mode; Feynman and Project own distinct phase machines. Retrieval is private
by default, and disclosure selects complete evidence units. Turn completion and
`ChatThread.learning_state` advance in one SQLite transaction.

The remaining gap is model-backed semantic evaluation plus broader
golden-dialogue coverage. The deterministic evaluator currently catches known
wrong conclusions and unsupported understanding claims, but it is not a
general-purpose judge of conceptual correctness.

## Compatibility policy

- New production imports from `src.api` are forbidden; use the owning module.
- Existing `src.api` attributes are frozen for older tests and clients.
- Compatibility endpoints are documented individually and require a migration
  note plus replacement coverage before removal.
- `app.py` and `src/ui/*` receive compatibility fixes only, not new features.
