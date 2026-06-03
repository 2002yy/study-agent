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

## Open-Source URL And Feed Migration Backlog

References reviewed:

- Python `urllib.parse` docs: URL parsing is practical but not validating; code
  with security implications should verify scheme, host, path, and other parsed
  components before trusting them.
- Requests docs: `Response.history` keeps redirect responses from oldest to
  newest, which is a useful mental model for explainable redirect debugging.
- feedparser docs: malformed feeds are surfaced through `bozo` and
  `bozo_exception` instead of being silently treated as normal input.
- `url-normalize`: mature URL normalization covers IDN handling, lowercasing,
  path dot-segment cleanup, default-port handling, percent-encoding rules, and
  configurable query parameter filtering.

### Worth Migrating Soon

- Migrated: add defensive URL character checks before trusting urllib parse results:
  reject control characters, embedded whitespace, backslashes, invalid ports,
  malformed IPv6 brackets, and parser-confusing hosts.
- Migrated: extend `RedirectHop` with `location` and `reason`, not just
  `url/status/source`. This makes UI/debug output explain whether a hop came
  from `Location`, query unwrapping, Google News HTML extraction, unsafe target
  blocking, or resolver exceptions.
- Migrated: record HTTP redirect response details closer to Requests history:
  status code, original request URL, `Location` target, final URL, and blocked
  reason.
- Migrated: normalize canonical URLs more aggressively but safely:
  remove default ports, deduplicate identical query key/value pairs, normalize
  empty paths to `/`, keep fragments stripped, and keep only meaningful query
  params after tracking-param removal.
- Migrated: add URL-normalizer tests for ambiguous inputs:
  whitespace/control chars, backslash hosts, invalid ports, credentials,
  localhost/private IP literals, duplicate query params, default ports, and
  tracking params.
- Migrated: add feed parse diagnostics inspired by feedparser `bozo`:
  keep per-feed warning/error metadata so the UI can say which feed failed and
  why, even when other feeds still returned results.

### Worth Migrating Later

- Consider optional `feedparser` integration once sources grow beyond current
  Google/Bing/domestic RSS feeds. Use it for `entries[i].link`,
  `entries[i].links`, `published_parsed`, source metadata, and bozo diagnostics.
- Migrated: add domain-specific query allowlists for canonicalization. Known
  domains can drop noisy query strings more aggressively while unknown publisher
  domains still keep non-tracking query params.
- Migrated: add IDN/punycode display normalization for reader-facing domains.
  This affects display only; safety checks still use the parsed host.
- Add path dot-segment normalization only after tests confirm it does not break
  publisher-specific article URLs.

### Not Worth Migrating Yet

- Do not replace the whole resolver with Requests. Keep urllib plus our SSRF
  checks; borrow the history/debug model rather than the dependency and redirect
  behavior wholesale.
- Do not introduce a full URL normalization dependency unless our in-project
  canonicalizer becomes hard to reason about or source diversity grows.
- Do not make malformed feed parsing fatal if at least one source succeeds.
  Prefer warnings plus partial results.
