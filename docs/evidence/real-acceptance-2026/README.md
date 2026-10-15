# Real-Model Acceptance Pack (2026) — frozen, NOT YET RUN

> **Status: `NOT_YET_RUN`.** This directory contains frozen *inputs* and the
> grading rubric for the real-model acceptance gate. No real model, vision or
> search provider call has been made for these scenarios.
>
> Offline evidence (unit tests, the five-surface integration test, E2E) is
> **not** a substitute for this gate. See `docs/CONTINUOUS_AGENT_HANDOFF.md`.

## 1. What is frozen here

| File | Purpose |
| --- | --- |
| `screenshot-firefly.png` | Uploadeable synthetic character panel (readable values) |
| `reference-notes.pdf` | Text-based synthetic reference document |
| `scenarios.json` | Frozen prompts, ground truth, must-observe / must-not, budget cap |
| `manifest.json` | sha256 of every fixture (freeze check) |
| `build_fixtures.py` | Regenerates the fixtures deterministically (no network) |

The fixtures are **synthetic** and contain no real game data. Ground truth lives
in `scenarios.json`, not in the fixtures' metadata.

## 2. Prerequisite — quota is not the same budget

Before running, confirm **the Study Agent's own provider configuration**, not the
coding tool's quota:

- which provider serves chat, vision and search;
- `attachment_vision_enabled` is ON (vision is opt-in);
- the account and spend ceiling for those providers;
- **OpenCode Go quota returning does NOT enable Study Agent's real model calls.**

Do not start the run until these are confirmed and the budget cap in
`scenarios.json` is accepted by the operator.

## 3. How to run (one round only)

1. Start the app on the candidate commit `6050fa3a` and open a **new session**.
2. Scenario **A**: upload `screenshot-firefly.png`, send the initial prompt,
   wait for the research opening, then send the mid-run correction.
3. Scenario **B**: new session, upload both fixtures, send its prompt.
4. Scenario **C**: new session, no upload, send its prompt.
5. For each scenario capture **five surfaces** together:
   browser (screenshots), HTTP/SSE events, SQLite rows, the search trace, and the
   computation result.
6. Record the outcome as `PASS` / `FAIL` per `must_observe` / `must_not` items.

Stop immediately when the budget cap is reached. A failure is diagnosed
narrowly; do not start large-scale tuning in the same round.

## 4. What this gate actually decides

Not "does it error", but:

- does the real model choose an appropriate tool on its own;
- is the searched material really used;
- does a mid-run supplement keep existing evidence and re-check only what changed;
- is the narration produced by real execution rather than templates;
- is the answer accurate and is the chart consistent with the computation.

Only a full pass unlocks the PR/merge gate (see the handoff, §8):

1. review the 13 skipped tests (already analysed: opt-in isolation + operator
   Crawl4AI e2e — no hidden required gate);
2. open one consolidated **Draft** PR for the branch;
3. confirm #229's three behaviours and tests are covered, then close the old PR
   as superseded;
4. run the new PR's required CI at its **exact head**;
5. decide on a squash merge only after review, migration version and this
   acceptance material all pass. Merging is not automatic.
