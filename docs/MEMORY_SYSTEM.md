# Memory System

## Overview

File-based long-term memory using Markdown files, managed through a truth hierarchy. No vector store or external database — designed for zero-infrastructure local operation.

## Truth Hierarchy

```
config/runtime_state.yaml  (authoritative)
       │
       ▼
memory/internal_state.md   (human-readable view, synced)
memory/interaction_settings.md
chat/wechat_state.md
```

`mode_manager.py` syncs views from YAML on read. Any write goes through `_write_runtime_state()` which updates YAML, then propagates to view files.

## File Layout

```
memory/
├── index.md                Learner identity, preferences
├── current_focus.md        Active learning focus
├── summary.md              Session summaries
├── learner_profile.md      Learning style, strengths
├── progress.md             Versioned progress
├── project_context.md      Project description
├── task_board.md           Task tracking
├── archive_summary.md      Archived history
├── agent.md                Agent notes
├── system_detail.md        Technical context
├── internal_state.md       Runtime state view (synced)
├── interaction_settings.md Interaction state view (synced)
└── pending_updates/
    ├── wechat_memory_candidates.md    LLM-extracted candidates
    └── wechat_memory_candidates.json  Structured candidate data
```

## Memory Operations

### Reading

`memory.py:_read_text_file_cached(path, signature) → str`

- LRU-cached (64 entries), invalidated on file signature change
- Context-mode selection via `CONTEXT_FILE_GROUPS` (see CONTEXT_TIERS.md)
- `extract_core_section()` keeps the first core lines for lightweight reads

### Writing

All writes go through `memory_writer.py` → `safe_writer.py`:

1. **Preview**: Generate update suggestions → user reviews
2. **Confirm**: User selects which updates to apply
3. **Write**: `safe_write_text()` with atomic temp-file + retry + backup
4. **Flush**: Updated context available on next memory bundle refresh

### Group Chat Memory Extraction

`wechat_memory.py` extracts memory candidates from group chat discussions:

- Triggered by configurable `memory_capture_mode` (manual/auto)
- LLM extracts structured candidates from chat history
- Results stored as Markdown + JSON in `memory/pending_updates/`
- Candidates reviewed before committing to main memory files
