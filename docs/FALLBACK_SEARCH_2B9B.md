# B-Search-2B9-B — cross-topic source discovery (Phase 1 diagnosis)

Real `deepseek-flash`, live, `tools/eval_2b9b_diag.py` (wraps `search_exact`/`read`). Raw: `diag.json`.

## Where "arrival" fails (exact)
### Factorio (train interrupts vs fixed schedule) — **RECALL**
- q1 `Factorio 2.0 train interrupts vs schedules when not to use` → Top-5 all generic:
  `factorio.com/`, `wiki.factorio.com/Main_Page/zh`, `ali213.net/zt/factorio/`, `factorio.com/download`,
  `3dmgame.com/games/factorio/` — **no mechanism article**.
- q2 (Chinese) → **identical Top-5**.
- q3 `site:wiki.factorio.com train interrupts` → **0 results**.
- Read: `wiki.factorio.com/Main_Page/zh` (a homepage), read OK but it is a landing page.
- → the specific entry **never entered Top-5**; the model cannot choose what was never returned.

### Go rules (提子 / 打劫) — **RECALL + READER**
- 3 queries (incl. one naming 维基百科) → Top-5 **identical every time**:
  `weiqigo.com`, `19x19.com`, `cosumi.net`, `metool.online/zh/games/go/`, `go-master.cn` — all
  server/homepages, **no rule article**.
- Read of `metool.online/zh/games/go/` → **`security_refused:response_too_large`** (exact reader
  branch + reason).

### Python 3.15.0 (control) — passes via feed seed; 1 read, `finished` ✅

## Diagnosis
- **Dominant failure = recall**: `search_exact` returns homepages/listicles; `site:` returns nothing.
  The backend also returned the **same Top-5 across different queries** → the search service looks
  query-insensitive/degraded right now (recorded as a real failure, not faked).
- **Secondary = reader**: one oversized page refused with `response_too_large`.
- The model's query refinement (mechanism terms, `site:`) did not lift specificity.

## Proposed generic fix (NOT hardcoded)
Bounded, evidence-preserving **in-page link following**: from a discovered relevant hub page
(e.g. a wiki), follow a small number of same-site links toward a specific article, reusing the
existing URL-safety + admission gate, with the link source recorded; and prefer specific entries
over homepages. No `site:`-only reliance; no per-topic rules.

## Verdict
**PARTIAL** — Phase 1 (diagnosis with exact locations) done; Phase 2 (generic discovery improvement)
and Phase 3 (paired real validation) **not done**. Do not claim arrival PASS.
