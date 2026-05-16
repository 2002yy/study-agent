# Archive Summary

> Compact summary of older project phases for lightweight context loading.

## Archived phases

- v0.1 to v0.4: basic dialogue loop, memory files, after-session updates, early wechat feedback flow
- v0.5 to v0.6: routing, UI shaping, module cleanup, packaging hardening
- v0.7.0 to v0.7.2: multi-source news search, article extraction fallback chain, source blocks, quality-pass cleanup

## Stable lessons

- keep UI rendering and business logic separated when a feature will likely be reused
- prefer safe file writes and bounded flush strategies in Streamlit rerun-heavy paths
- keep compatibility exports when refactoring public helper locations used by tests
- use a machine-readable runtime state file and keep markdown as mirrored views
