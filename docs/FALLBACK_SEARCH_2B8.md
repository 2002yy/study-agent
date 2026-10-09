# B-Search-2B8 — Feed entry semantic selection (PARTIAL)

## 2B8-D-QUAL — real dual-channel A/B (limited-scope PASS, frozen runs)
Ran for real (real feed XML + real per-case search snapshot, SHA256 recorded; real
`deepseek-flash`): B vs A — tutorial negative: A read release+downloads, **B read 0 and finished**;
similar_title: A read free-threading **+ an extra release post**, **B read only free-threading after
3 tool-layer rejections**; not_first/final_vs_prerelease/no_article matched. Key numbers: **false
"satisfies-the-goal" claims 0**, **truly-relevant wrongly blocked 0**, **correct give-up/recovery
yes**. Also fed `assessment` back into the next observation (arm B) — the flagged defect. Caveats:
n=6; live unfrozen positive/negative NOT run; the feedback fix is not isolated from the admission
rules. See `D_QUAL_RESULTS.md`.


## 2B8-D — cross-source admission + post-read goal match
`search_admission()` (title+snippet): Feed keeps its hard gate (`admission_map` exclusions stay
hard, not bypassable). For **search** only explicit conflicts are refused — a tutorial request vs a
release/download page, a release request vs a tutorial, or a *different* demanded version; a thin
title ("Python 学习笔记") is `explore` (readable, never auto-deemed relevant); a likely match is
`allow`. The feed threshold is NOT applied to search; no URL is globally banned. `assess_body()`
judges a read body as `matches / partial_background / mismatch / insufficient_information` with
met/missing conditions + a locating snippet: a generic Python tutorial is `partial_background` for
`Python 3.15.0 入门教程` (missing `version:3.15.0`), never "the 3.15 tutorial was found". The agent
registers `url_admission` for search results, writes explicit conflicts into `entry_exclusions`
(`search_*`), and records `assessment` after a read. Evidence Gate untouched.

**Real cross-source A/B NOT run this slice → overall PARTIAL.**


## 2B8-C — tool-layer admission + frozen-snapshot A/B
`confirmed` (discovered) is now separate from goal-fit: `admission_map()` marks each entry
eligible / excluded(type|version|below_threshold); `read_page` checks `entry_exclusions` BEFORE
confirmed/quota/safety and returns `entry_not_eligible` without fetching or spending quota, so no
other confirmation path can bypass it. Frozen snapshot A/B: B rejected 2 ineligible feed entries in
`similar_title` (excluded-entry reads **0**, extra feed mis-read **1→0**, correct article kept) →
**feed-entry scope limited PASS**. The `tutorial_conflict` negative still fails but now via the
**`search` path** (not gated) → **overall PARTIAL**. See `AB_METRICS_C.md`.


## 2B8-B real-model A/B (RESULT: NO improvement) — see AB_METRICS.md
5 cases × {A plain, B ranked}, real model, identical code path. Arm B improved only the
`similar_title` case (and read an extra wrong URL there); on `Python 3.15.0 入门教程` **arm B read
the release post** although the observation carried `no_relevant_entry`. `no_relevant_entry` is
advisory only — the model still reads any *confirmed* feed URL. `not_first` / `final_vs_prerelease`
/ `no_article` were identical. selected-correct A 2/3 vs B 3/3; correct-refusal 1/2 both;
**dangerous mis-selection A 0/1 vs B 1/1**. → **PARTIAL**; enforcement must move into the tool
layer (block confirming/reading selector-excluded entries), not just the observation.


## 2B8-B — Agent wiring + logic fixes + Reader deadline (PARTIAL) — base `cccb6363`
- **Wiring**: `research_tool_agent` feed stage now calls `rank_entries()`/`select_entry()`
  and feeds the model the ranked scores + reasons + `excluded` + a `no_relevant_entry`
  marker. No extra model call; model still chooses tools. The selection is also recorded
  under `call["entry_selection"]`.
- **Type-gate hole FIXED**: an exact version no longer bypasses the tutorial requirement —
  `Python 3.15.0 入门教程` must resolve to a tutorial, never the release post (and refuses
  when no tutorial entry exists). A release request may still be satisfied by an exact
  version; a final release is never replaced by a pre-release.
- **Reader budget gap FIXED**: `article_fetcher` passes an absolute `deadline`;
  `safe_fetch_result` uses per-hop `min(timeout, deadline-now)` and raises
  `deadline_exhausted` — a redirect chain cannot re-acquire the full timeout per hop.
- Housekeeping: corrected a stale assertion (truncation now raises `SafeFetchRefusal`
  per the frozen contract).
- Gates: `test_entry_selection` + `test_research_tool_agent` + `test_reader_safety`
  **26 PASS**; ruff PASS; mypy baseline held.
- **NOT done (budget)**: the five-case real-model A/B comparison, a natural-question
  live RSS run and a no-article negative, and the numerator/denominator metric output.
  **Verdict stays PARTIAL**: wiring and logic fixes are in place, but it is **not yet
  proven** that the real agent more often reads the right article, misreads less, and
  knows when to give up.


Base `441b7ea4`. Relevance only; never evidence. RP-1 NO-GO.
Evidence: `reading-notebook-ui-evidence/reader-safety-2/entry_selection.json`.

## What was built
`src/web/research/entry_selection.py`: deterministic entry ranking against the
**full research goal** (topic terms + exact version + question type + pre/final):
- `score_entry(title, question)` → `(score, reasons, notes)`; a **typed** request
  (tutorial vs release) must be satisfied by the **same family or an exact version**,
  otherwise score 0 (`typed_request_unsatisfied`);
- `rank_entries` returns per-entry score/reasons/`excluded`;
- `select_entry(..., min_score=2)` returns `None` ⇒ **`no_relevant_entry`** when
  nothing clears the bar (weak single-token overlap refused).

## Real demonstration (actual directory-recalled Python blog feed, 10 entries)
| question | result |
| --- | --- |
| `Python 3.15.0 正式发布说明` | **“Python 3.15.0 (final) is here!”** (score 6, `version_exact:3.15.0`, `final`); “candidate 3” ranked 3 (prerelease penalty) |
| `Python 入门教程` | **`no_relevant_entry`** (all releases `typed_request_unsatisfied`) |
| `围棋 提子 规则` | **`no_relevant_entry`** |

Defects found & fixed while building: (1) pre-release “candidate 3” tied with the
final release → prerelease penalty + final bonus; (2) a tutorial request matched a
release post → same-family type gate; (3) a bare topic token over-selected → the
type bonus only applies when the question asks that family, and `min_score=2`
refuses weak overlap; (4) CJK type words weren’t token-matched → substring type/
version detection.

## Separation kept
`read_success` (HTTP/reader) is recorded separately from this `relevance`
judgement, and both are separate from `evidence_support` (Evidence Gate — untouched).

## Verification
`tests/test_entry_selection.py` **6 PASS** (correct-not-first, final>prerelease,
tutorial rejects release, tutorial-without-tutorial refused, unrelated refused, weak
overlap refused). `ruff` PASS; mypy current 122 / baseline 128 NEW 0.

## Residual recorded (not fixed here)
The general article reader calls `safe_fetch_result()` **without an absolute
`deadline`**, so a redirect chain may re-acquire the full timeout per hop. This is a
Reader **budget-qualification gap**; it does not block selection work but the overall
time cap is not fully closed.

## Verdict
**PARTIAL**: the selection layer + relevance refusal work and are demonstrated on a
real feed; the full five-case controlled comparison **and a real model-driven agent
task** (vs preset tool actions) are **not** completed in this slice, so no claim of a
broad semantic improvement.

## Boundaries
No change to Reader safety, publication, Evidence Gate, main, #208, Shadow or RP-1;
no new model/search/feed/read/round/time budget. B production wiring not enabled.

## Next
Run the real model-driven agent selection over the directory (same budget), record
`question → source_id → feed_url → candidate/selected entry → read_url` + reasons,
and compute selected-correct / correct-refusal / mis-read rates — only then judge
whether the semantic layer holds. Also pass the absolute `deadline` into the reader.
