# B-Search-2B7-A — OPML source directory import + offline Top-K recall

Base `14a18bd9`. Offline only: no feed reads, no model calls, no network at import
or recall. RP-1 NO-GO.
Evidence: `reading-notebook-ui-evidence/rss-directory-snapshot/` (OPML snapshot +
`index.json`; `recall2.txt`).

## Upstream
`xiangyugongzuoliu/awesome-rss-feeds-list` — `feeds.opml`, 30 category OPMLs under
`feeds/`, `stats.json`, `LICENSE`. Snapshot downloaded via GitHub API base64 →
raw bytes (note: PowerShell text piping mangles UTF-8 CJK; base64→bytes is required).
`feeds.opml` sha256 recorded in the index.

## Importer (`tools/import_opml_directory.py`)
Bounded, offline: rejects `<!ENTITY` (entity-expansion vector); escapes bare `&`;
parses each category file of the form `cn-<cat>.opml` / `en-<cat>.opml` (language +
category). Normalizes `xmlUrl` (scheme/host lowercased, default ports dropped),
dedupes by normalized URL, **merges category/language tags** for the same URL,
assigns a stable `source_id` (`sha256(url)[:16]`), records provenance. **Every
record starts `cataloged`** — availability is never assumed, no evidence authority.

## Real import (2,000-source directory)
| metric | value |
| --- | --- |
| raw outlines | 2000 |
| invalid files | 0 |
| final sources | **2000** |
| upstream `active_count` | 2000 (exact match) |
| languages | en 1207 / cn 793 (matches upstream) |
| multi-category URLs | 0 (no cross-category duplicates in this dataset) |

## Recall (`src/web/research/source_directory.py` — deterministic `recall_sources`)
Token match (latin + CJK) over title+categories; a language preference only
**boosts** a token match, it never creates one; results sorted by score then id,
with `score` + `reason`.

| question | top-3 | note |
| --- | --- | --- |
| `Python 最新版本` | 豌豆花下猫-Python猫 (1.5), Python Blog (1.0) | relevant |
| `Factorio 2.0 train interrupts` | **[]** | no such source (correct) |
| `围棋 提子 规则` | **[]** | **no false Go(Golang) match** |
| `Go 语言 net/http` | Go 夜聊 (1.5), 猫鱼的小窝 (net, 1.5), pluralistic.net (1.0) | correct #1; **"net" over-match** |
| `今天晚饭吃什么` | **[]** | no forced recall |

## Acceptance
- OPML (full + category) imported offline, real 2,000-row data ✔; URL normalize/
  dedupe/stable-id/multi-category merge ✔; index with title/topic/language/source/
  status ✔; `recall_sources(question, k=3)` ✔; ambiguity: Go/围棋 distinct,
  irrelevant → empty ✔; **0 network in import and recall** ✔; all `cataloged` ✔.
- Known limit: the common token `net` over-matches (`net/http`). Not blocking; a
  stop-word/specificity pass is the next refinement.

## Boundaries
No feed reads, no online qualification, no production Agent change, no model/network
budget change, no Evidence Gate, no #208/Shadow impact. 2B7-B will do on-demand
qualification and a real `recall → verify → feed → entry → read` chain — this slice's
offline recall is **not** end-to-end success.
