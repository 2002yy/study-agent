# README703

## 2026-06-03 Runtime Config And URL Resolution

This note records the designs worth migrating after reviewing Codex CLI-style
configuration/task structure and common URL handling patterns from urllib,
requests, feed readers, and URL normalizers.

### Migrated

- Runtime config is now schema-validated before it becomes runtime state.
- Invalid enum values, wrong types, unknown sections, unknown keys, missing keys,
  and YAML parse failures produce non-fatal warnings instead of silently changing
  behavior.
- `load_runtime_modes()` remains the compatibility API, while
  `load_runtime_config()` exposes the validated state, source, and warnings for
  diagnostics.
- URL resolution now has rich hop history through `RedirectHop` and
  `RedirectResolutionResult`, inspired by Requests' redirect history model.
- RSS news items now carry serializable `redirect_hops`, so source/debug UI can
  explain how a link moved from original RSS URL to final/canonical source.
- Unsafe redirect targets are recorded as blocked hops but are still refused as
  navigation targets.

### Kept Out For Now

- No full Codex-style thread protocol, app-server loop, or approval/sandbox
  system. The project does not need that complexity yet.
- No third-party schema framework for runtime state. A small in-project schema is
  enough and avoids adding another dependency boundary.
- No wholesale replacement of urllib with requests. The current urllib-based
  resolver keeps the existing SSRF posture while borrowing the useful history
  concept.
- No heavy feedparser migration yet. Existing feed parsing is still adequate for
  current RSS sources.

### Verification

- `python -m pytest tests/test_mode_manager_yaml.py tests/test_link_resolver.py tests/test_url_normalizer.py tests/test_news_redirect_dedup.py -q`
- `ruff check src tests`
- `python -m pytest -q`

## 2026-06-03 Runtime Profile And Task Events

### Migrated

- Added `RuntimeProfile` as the effective permission projection from
  `safe_mode`, `memory_mode`, `performance_mode`, and `route_mode`.
- Existing compatibility APIs now delegate to the profile:
  `RuntimeModes.context_mode`, `RuntimeModes.allow_llm_router`,
  `RuntimeModes.preferred_model`, and `is_memory_write_allowed()`.
- Added `TaskEvent` and `emit_task_event()` as a lightweight service-layer event
  model with `started`, `progress`, `item_completed`, `failed`, and `completed`
  events.
- `run_news_round()` now emits task events while preserving the old Streamlit
  `progress(str)` callback.
- `after_session` and the unified memory writer can optionally emit task events
  without changing their default return-value behavior.
- Safe mode now blocks article body network reads in `run_news_round()` through
  the centralized runtime profile and records a warning/event instead of
  silently reading.

### Still Deferred

- No app-server event loop or Codex-style thread protocol.
- No feedparser migration until the project adds more heterogeneous RSS/feed
  sources.

### Verification

- `ruff check src tests`
- `python -m pytest tests/test_architecture_flows.py tests/test_wechat_service.py tests/test_after_session.py tests/test_task_events.py -q`
- `python -m pytest -q`
