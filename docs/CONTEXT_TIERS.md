# Context Tiers

The system selects which memory files to include in the LLM context based on the current performance mode. This balances response quality against token usage and latency.

## Tier Definitions

Defined in `src/memory.py` (`CONTEXT_FILE_GROUPS`):

| Tier | Files | Use Case |
|---|---|---|
| **fast** | `index.md`, `current_focus.md` | Quick lookup, simple Q&A |
| **light** | + `summary.md`, `learner_profile.md` | Default daily chat |
| **deep** | + `progress.md`, `project_context.md`, `task_board.md` | Complex reasoning, project review |
| **archive** | + `archive_summary.md`, `agent.md`, `system_detail.md` | Full context, session archive |

## Resolution

`context_mode` is derived from `performance_mode` in `RuntimeModes` (`src/mode_manager.py`):

- `fast` → `fast`
- `standard` → `light`
- `deep` → `deep`
- No direct UI path to `archive` — used programmatically for archival tasks

## Memory Files

Path: `memory/`

| File | Content |
|---|---|
| `index.md` | Learner name, preferred roles, brief background |
| `current_focus.md` | What the learner is currently working on |
| `summary.md` | Session summaries, key learnings |
| `learner_profile.md` | Learning style, strengths, weaknesses |
| `progress.md` | Version-tracked progress log |
| `project_context.md` | Project description, goals, constraints |
| `task_board.md` | Active tasks, backlog |
| `archive_summary.md` | Archived session records |
| `agent.md` | Agent self-configuration notes |
| `system_detail.md` | Technical system context |

## Caching

Memory files are LRU-cached with invalidation on file signature change (`src/memory.py:_read_text_file_cached`). Cache size: 64 entries.
