# B-Search-2B7-B — on-demand qualification + real directory-sourced read

Base `fb000391`. Experimental (no production wiring). RP-1 NO-GO.
Evidence: `reading-notebook-ui-evidence/model-driven-search-2b7b/chain.json`.

## Fixes from the 2B7-A review
1. **Recall precision**: added a stop-word list; `net`/`com`/`blog`/`news`… no longer
   recall unrelated sources. `net/http server` → **[]** (was spurious `.net` hits).
2. **URL validity (importer)**: a source URL with **credentials** (`user:pass@`), an
   **abnormal port** (≠ 80/443), or a **non-global IP literal** is now rejected.
3. **Reproducibility**: the index records the **upstream commit**
   (`fb8922c2…`) plus **sha256 of `feeds.opml`, `stats.json` and all 30 category
   files** (32 file hashes), alongside the existing `feeds.opml` hash. (The full
   2,000-row index remains an external snapshot; the manifest makes it reproducible.)

## On-demand qualification + real chain (safety-constrained path)
Recall from the 2,000 directory, then qualify **only the selected** source via the
existing `safe_fetch` (SSRF-constrained: per-hop scheme/IP validation, IP-pinned
connection) — **not** the production Reader (still blocked).

| question | candidates | outcome |
| --- | --- | --- |
| `Python 教程` | 2 | #1 `feed-0350e654` → `unavailable` (`invalid_feed_xml`); #2 **Python Blog** → feed `ok` **10 entries** → entry read `ok` **12,239 chars** |
| `Go 夜聊 播客` | 3 | #1 **Go 夜聊** → feed `ok` **10 entries** → entry read `ok` **2,990 chars** |

**This is a directory-recalled source** (not the hand-registered Python Feed):
`question → recall → source selection → feed → entry → article → body`, with a
failure (invalid XML) recorded as `unavailable` and the chain falling through to the
next candidate.

## Separate reporting (per the contract)
- **Recall accuracy**: precise after the stop-word fix (`net`/围棋/irrelevant → empty;
  `Python`/`Go 夜聊` correct).
- **Online feed availability**: 1/2 Python candidates, 1/1 Go candidate `ok`;
  invalid XML → `unavailable` (not fabricated).
- **Article read success**: 2/2 reached articles (12,239 / 2,990 chars) via the
  safety-constrained path.
- **Body ⇄ question relevance**: bodies captured with previews in `chain.json`;
  first-entry selection only — relevance scoring not done here.
- **Residual Reader block**: the production `gateway.read` connection/redirect safety
  is **still open**; the directory's article URLs must not enter it until a dedicated
  reader-safety slice lands.

## Verification
`source_directory` tests 2 PASS; `ruff` PASS; mypy current 122 / baseline 128 NEW 0.
Budgets (model/search/feed/read/round/time) unchanged; no Evidence Gate / main / #208
/ Shadow change.

## Verdict
**PASS (experimental)**: the system autonomously found and used a real source from a
2,000-entry directory and read a real article body through a safety-constrained path.
The production Reader remains blocked — this is not a production qualification.
