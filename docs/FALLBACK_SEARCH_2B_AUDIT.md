# B-Search-2B — existing open-source platform tools: reuse audit

Read-only audit. No Agent/prompt/budget/gate change. Base `947484a3`.
RP-1 NO-GO. Evidence: `reading-notebook-ui-evidence/model-driven-search-2b/platform_probe.json`.

## What already exists (repo, not yet merged)
Draft **PR #168** (`codex/platform-capability-contract`) adds a reusable, replaceable
specialist layer — it is **not on `main`** or the B worktree:
- `src/web/research/platform_capabilities.py`: `PlatformCapability` registry
  (`anonymous`/`optional_auth`/`auth_bound`, per-operation `qualification`),
  `PlatformHit` (forces `epistemic_kind="community_observation"`, grants no
  authority), `PlatformRequest`/`PlatformBatch`, `validate_platform_batch`.
- `src/web/research/discovery.py`, `tools/qualify_anonymous_platforms.py`
  (bounded **anonymous** probes, no cookies/profile/keys; diagnostic only),
  and contract tests.

Registry (documentary hints; every operation starts `unqualified`): bilibili
search/detail via `bili-cli` (fallback MediaCrawler), youtube via `yt-dlp`, rss via
`feedparser`, v2ex public API; xhs/zhihu/reddit/twitter are `auth_bound` /
`unavailable`.

## Environment audit (current host)
Installed tools: **`yt-dlp` absent, `bilibili-cli` absent, MediaCrawler absent,
`xiaohongshu-mcp` absent; Python `yt_dlp`/`feedparser` absent.**

Ran the PR's own read-only anonymous probe (`--live`):

| platform | operation | result |
| --- | --- | --- |
| bilibili | search API | **HTTP 412** (platform_rejected) |
| youtube | public page | **URLError** (timeout ~16 s) |
| rss (blog.python.org) | feed | HTTP 200, but `ModuleNotFoundError` (feedparser not installed) |
| v2ex | feed | **URLError** (timeout ~16 s) |

`cookie_access=false`, `browser_profile_access=false`, `qualified=false`.

## Attribution
- **B站 anonymous API is anti-bot blocked (412)** from this environment; YouTube and
  V2EX **time out**; only plain RSS returned 200 but the parser is absent.
- This is the **same egress/anti-bot restriction** seen in B-Search-2A1 (SearXNG
  engines CAPTCHA/timeout; host 200 ≠ usable). It is the **environment**, not the
  code or the platform contract.

## Conclusion
- The **contract layer is reusable and correct** (replaceable specialists; community
  content never granted authority) — it should be the integration point, once merged.
- But **neither the free search engines nor the anonymous platform tools can be
  qualified from this host**: B站 412, YouTube/V2EX timeout, tools uninstalled.
  So the planned “B站 search → real content → model continues” end-to-end validation
  **cannot be completed here**; it needs an environment with working egress, or a
  service with a proper (keyed) API.
- This is **not** an “OSS vs paid” choice: build the replaceable tool registry and
  fill the slots that actually work in the target environment.

## Next (bounded)
1. Where egress works: `pip install yt-dlp feedparser`, install `bili-cli`, and run
   the PR #168 anonymous probe + one B站 search→content cycle.
2. For this host: treat the free-engine/platform path as environment-blocked; if a
   paid API is evaluated, it is to *substitute a working endpoint*, not to change the
   architecture.
3. Merge/rebase PR #168's contract as the tool-integration layer; do not fork a
   second platform system.

## Boundaries kept
No Agent/prompt/budget/Evidence Gate change; no login/cookie/bypass; no account use;
no provider switch. Base `947484a3` preserved.
