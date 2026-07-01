# Architecture Status

This file is the single source of truth for migration status. Other planning
documents must link here instead of maintaining competing status tables.

Updated: 2026-07-01

Future work is ordered in [NEXT_PHASE_PLAN.md](NEXT_PHASE_PLAN.md). Planned
items are not implementation status.

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
| App entry | **sealed** | composition-only `App.tsx` |
| AppShell | **sealed** | six-line layout-only component with no state, API or persistence |
| Workspace Runtime | **sealed** | 134-line composition root; lifecycle, recovery, controllers and views have explicit owners |
| Compatibility API | **legacy shim** | frozen `src/api/__init__.py` attributes for old tests/clients |
| Streamlit | **legacy compatibility** | `app.py` and `src/ui/*`; not the primary architecture |

## Completed execution order

1. **P0 — Web alignment:** gateway/reader boundaries, structured evidence,
   durable WebLookupRun, service/controller ownership.
2. **P1 — MemoryTransaction:** SQLite repository/service, `/memory-runs`,
   hash-locked commit, controller and display-only panel.
3. **P2 — RAG/KnowledgeBase:** durable query/upload/rebuild runs, controllers,
   document lifecycle and monotonic index versions.
4. **P3 — Shell convergence (complete):** shared server query cache,
   settings/role/workflow controllers, composition-only `App.tsx`, layout-only
   `AppShell`, schema-versioned persistence, cross-feature coordination,
   recovery and view binding all have explicit owners.

`AppShell` is now genuinely layout-only rather than a renamed application
component. The remaining large composition root is explicitly named
`WorkspaceRuntime`. Sidebar, Inspector and GlobalNotices now live under
`frontend/src/layout`; feature-controller construction and cross-feature
coordination live in `useWorkspaceControllers`; restore/hydration/persistence
live in `useWorkspaceRecovery`; and feature rendering lives in `WorkspaceView`.
`WorkspaceRuntime` now only binds shared state to those four boundaries.

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

`PedagogyEvalRun` now defines the structured evaluation boundary: deterministic
result, optional semantic result, confidence, evidence references and final
decision. Its service returns `needs_semantic_review` when no provider can judge
an ambiguous claim. Wiring that service into the live turn pipeline and
persisting eval runs remain open, so Pedagogy stays **partial**.

## Compatibility policy

- New production imports from `src.api` are forbidden; use the owning module.
- Existing `src.api` attributes are frozen for older tests and clients.
- Compatibility endpoints are documented individually and require a migration
  note plus replacement coverage before removal.
- `app.py` and `src/ui/*` receive compatibility fixes only, not new features.
