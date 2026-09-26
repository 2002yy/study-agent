# Study Agent Agent Instructions

This file defines repository-wide execution rules for Codex/agents working in this repository.

The goal is to preserve engineering quality while avoiding repeated context loading, redundant scans, repeated full-suite validation, oversized logs, duplicate CI watching, and rediscovery of already-frozen decisions.

## 1. Source of truth and cold start

1. Treat `docs/PROJECT_STATUS.md` **Current Handoff** as the primary current-state entrypoint.
2. Read only the contract/task documents explicitly referenced by the current handoff or task. Do not recursively read historical status/roadmap documents unless a concrete contradiction or missing fact requires it.
3. Frozen decisions recorded in `PROJECT_STATUS.md`, taskbooks, accepted review findings, or an existing inventory/audit are authoritative. Do not reopen or re-derive them unless new evidence proves a regression or contradiction.
4. Do not rely on chat history as the only durable state. At the end of each phase or key closed loop, record the recoverable state in repository docs before continuing.
5. A cold-start agent should reconstruct only what is needed for the current batch: current branch/base/head, dirty state, current handoff, the active contract, changed files, and directly relevant tests.

## 2. Context and token efficiency

1. Prefer **targeted reads** over repository-wide reads.
2. Before opening a large file, first use file names, symbols, `rg`, `git diff --stat`, `git diff --name-only`, or an existing inventory to narrow the relevant region.
3. Do not reread unchanged large files merely because they were important in an earlier phase.
4. Do not restate long project history in progress updates. Updates should contain only:
   - what changed;
   - evidence obtained;
   - blocker/risk;
   - next action.
5. If an authoritative inventory/audit already exists, reuse it. Re-scan the whole repository only when the inventory is demonstrably stale for the current question.
6. When checking whether an inventory is stale, first inspect files changed since its recorded base/head. Widen the scan only if those changes can invalidate the inventory.
7. Prefer incremental review ranges such as `PREVIOUS_VERIFIED_HEAD...HEAD` rather than rereviewing the whole PR or historical implementation.
8. Do not duplicate design reasoning already completed in ChatGPT/review documents. If implementation instructions cite a frozen decision, execute it rather than re-arguing it.

## 3. Repository-wide scan policy

A repo-wide scan is allowed only when at least one of these is true:

- the task explicitly requires an exhaustive inventory or compatibility audit;
- no trustworthy prior inventory exists;
- a structural refactor may have moved/renamed the relevant writers/consumers;
- changed files since the prior inventory touch code-generation, registration, plugin discovery, routing, serialization, or other mechanisms that can create hidden call sites;
- a focused scan gives conflicting evidence and the result cannot be resolved locally.

Otherwise:

1. start with changed files and known owners;
2. search exact symbols/constructors/literals;
3. inspect only matching call sites;
4. widen incrementally if necessary.

When a repo-wide scan is performed, save the useful result as a durable inventory/report so later batches do not repeat the same scan.

## 4. Test execution policy — Staged Regression Policy (L0–L3)

Frozen 2026-09-23 (see `docs/PROJECT_STATUS.md` §109). Applies from **P2-A3 onward**. Supersedes the previous default of "run full pytest per candidate head".

### 4.1 The four layers

| Layer | When it runs | Content |
| --- | --- | --- |
| **L0 quick gate** | every commit | Ruff + `git diff --check` + tracked worktree clean |
| **L1 focused** | every implementation slice | the slice's own module tests + every directly affected test (the slice's *impact set*) |
| **L2 stage integration** | every sub-phase CLOSED (Ax / Bx / Cx) | the sub-phase's whole stack + adjacent contract tests + key regressions |
| **L3 full regression** | major phase CLOSED (P2-A / P2-B / …), production cutover, pre-release | full `pytest tests` |

Default rhythm: **small slice → focused; sub-phase → integration; major phase → full.**

### 4.2 L1 impact sets (never a single test file)

Every slice declares an **impact set**, not one filename. Named sets live in `tests/stage_gates.json`. Derivation rule:

> the slice's own test file(s) + every test that references a symbol the slice touched + the layer directly below it.

Example (A3 browser adapter): its own test + `test_progressive_routing.py` + `test_scheduling.py` + `test_candidate_resolution.py` + the browser/fallback subset of `test_active_research_runtime.py`.

### 4.3 L2 stage integration gate

Run pytest over the named stage gate in `tests/stage_gates.json` — e.g. `p2-a-retrieval-stack` = A0 taxonomy + A1 breaker + A2 lifecycle/routing/scheduling/chain + A3 browser. This is the retrieval-subsystem regression; synthesis, agent loop and unrelated modules are **not** included.

Do not build a framework for this. A manifest plus plain `pytest <paths>` is enough.

### 4.4 Mandatory early L3 (escalate regardless of layer)

Run full pytest immediately when a change touches:

1. shared core data models — `RuntimeReadOutcome`, candidate lifecycle, routing/scheduling contract, Evidence/Support/Gate;
2. production authority cutover (e.g. the A2d-4 single-execution-authority switch);
3. persistence schema / cursor compatibility;
4. a broad cross-layer refactor;
5. a focused test failing for an unknown reason;
6. behaviour drift that cannot be proven locally contained.

Ordinary adapters, instrumentation, fixtures and provider integration do **not** force L3.

### 4.5 L3 rules

Run the full backend pytest suite **once per candidate head**. A second full run is justified only when, after the previous full run, one of these changed:

- production code;
- runtime behavior;
- serialization or persistence contracts;
- test infrastructure/fixtures with broad reach;
- dependency/configuration affecting the tested runtime.

Do **not** rerun the full suite for changes limited to:

- docs/status/handoff text;
- PR title/body;
- comments only;
- formatting/import ordering that does not change runtime behavior;
- test-name/message cleanup with no fixture/control-flow change.

If a review fix changes only a small production area, rerun affected focused tests first. Run the full suite again only when the fix creates a new candidate production head.

### 4.6 Gate order

- **L0 + L1** (default per slice): Ruff → affected focused tests → `git diff --check` → worktree cleanliness → diff-scope audit.
- **L2** (sub-phase close): L0 + L1 + the named stage gate.
- **L3** (major-phase close / cutover / pre-release): L0 + L1 + L2 + full pytest, then Ruff → `git diff --check` → worktree cleanliness → diff-scope audit.

mypy runs only if the repository declares a baseline/config; this repository currently declares none, so it is not part of the gate.

Do not interleave repeated full-suite runs between small fixes when focused tests can provide the needed signal.

### 4.7 Retro-application note

Under this policy A2d-1/2/3 and A3-0 would **not** have required L3; A2d-4 (authority cutover) and A2e (sub-phase close) did. Historical full runs remain valid evidence — do not re-run them merely to "comply".

## 5. Verbose command-output policy

1. Redirect very verbose commands to a temporary file when practical, especially full pytest, mypy, large build logs, and long static scans.
2. On success, report only concise evidence: command, pass/fail count, duration when useful, and relevant summary metrics.
3. On failure, inspect the smallest useful slice first (error summary / tail / named failing test / failing job). Read the full log only if the concise slice is insufficient.
4. For `rg` or inventory scans, prefer counts and file lists first; fetch matching lines only for the subset needed to make a decision.
5. For Git diffs, inspect in this order:
   - `git diff --stat`;
   - `git diff --name-only`;
   - targeted patches for changed files;
   - full diff only when necessary.
6. Do not paste entire successful logs into handoff/status documents.

## 6. PR and review policy

1. Keep each architectural/contract batch independently reviewable when practical. Do not continue the next semantic batch on an unmerged branch if separating the batches materially improves rollback/review clarity.
2. Before opening a PR, verify:
   - intended base/head;
   - worktree clean;
   - expected file scope;
   - local candidate-head gates complete.
3. PR bodies should contain:
   - locked scope;
   - explicit non-scope;
   - base/head review range;
   - concise verification evidence;
   - known limitations/deferred work.
4. Review only the smallest relevant range. After a review-fix commit, inspect `PREVIOUS_VERIFIED_HEAD...NEW_HEAD`, not the whole PR again, unless the fix changes architecture or invalidates earlier assumptions.
5. Do not merge when the reviewed head has moved. Use expected-head protection/checks when available.
6. A green PR at an old head is not evidence for a newer head.

## 7. CI policy

1. After push/opening a PR, query CI state once to capture run IDs and exact `head_sha`.
2. Do **not** continuously run `gh run watch`, polling loops, or repeated status queries inside an agent session merely to wait for CI completion.
3. Resume/check CI in a later turn or explicit follow-up. When checking, query only the known run(s) or exact head SHA.
4. Inspect detailed job logs only if a run fails or a required gate is ambiguous.
5. For PR closeout, distinguish:
   - exact-head push CI;
   - exact-head pull-request CI;
   - merge commit / exact-main CI.
6. Do not call a batch `REMOTE GO / DELIVERED` until the required exact-head CI is green; if the project contract requires merge-main verification, wait for the merge commit's main CI as well.
7. Do not rerun an already-green workflow merely to obtain duplicate evidence unless the head changed or the prior result is invalid/stale.

## 8. Failure/retry discipline

1. When a command appears hung, first distinguish code deadlock from terminal/pipeline/output-buffer behavior before changing production code.
2. Do not repeatedly rerun the same expensive failing command without changing the hypothesis, instrumentation, or execution method.
3. Prefer a minimal reproducer/focused test for diagnosis, then return to the normal gate sequence.
4. Preserve failure samples, root cause, repair reason, and the proof that distinguishes the fixed behavior from the old behavior (negative control when useful).

## 9. Handoff and recoverability

After every phase or key closed loop, update the repository's authoritative handoff with enough information for another agent/window to continue without chat history.

Record at least:

- result and decision;
- implementation summary;
- exact branch/base/head/commit or PR state;
- worktree cleanliness;
- focused/full test evidence;
- CI evidence when applicable;
- failure samples and root cause for meaningful defects;
- known limitations and deferred items;
- unfinished work;
- the single next execution slice.

Do not record raw logs when a concise durable summary is sufficient.

## 10. Scope-control rules

1. Do not fix adjacent issues just because they are visible during a batch. Record them in the appropriate inventory/debt section unless they block the current acceptance gate.
2. If completing a task unexpectedly requires touching files explicitly listed as out of scope, stop the implementation expansion and first determine whether the contract/scope assumption was wrong.
3. Prefer narrow commits with one semantic purpose over large mixed commits.
4. Documentation-only follow-up after a fully validated production candidate does not by itself require rerunning the full test suite.

## 11. Default progress-update format

For non-trivial work, keep updates short and evidence-based. Prefer:

```text
Changed: <one concise statement>
Evidence: <focused result / exact SHA / relevant metric>
Risk: <only if real>
Next: <one next action>
```

Avoid narrating every shell command or repeating frozen background.

## 12. Study Agent project-specific defaults

1. `docs/PROJECT_STATUS.md` is the current-status owner; do not create competing long-term STATUS/ROADMAP documents.
2. RQCE stage/batch boundaries and frozen decisions recorded there must not be silently reopened.
3. Existing inventories such as failure-state writer inventories are reusable inputs. Re-scan only when changed files can invalidate them.
4. Real SearXNG/bounded qualification runs are evidence runs, not routine development tests. Do not repeat them after unrelated code/doc changes.
5. Full release/qualification suites are phase gates, not per-edit feedback loops.

## 13. Definition of efficient success

A task is not more correct because it used more scans, longer logs, more full-suite reruns, or more CI polling.

Prefer the smallest evidence set that proves the requested behavior while preserving the repository's frozen quality gates, crash/recovery guarantees, compatibility rules, and reviewability.
