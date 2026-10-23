# Product iteration policy — Static Loop + Dynamic Loop

> **Stable product contract (effective 2026-10-20).** Entry: root [`AGENTS.md`](../AGENTS.md).
> `docs/PROJECT_STATUS.md` §0 **continues to own actual progress, active work,
> blocker evidence, and the one next execution slice**. This file is neither a
> competing roadmap nor a current-state snapshot. Preserve existing review/CI
> and staged L0–L3 rules.

## Priority order (binding)

When deciding what to do **next**, apply these ranks in order:

| Rank | Work | Selection / exit condition |
| --- | --- | --- |
| **P0** | Security, privacy/consent, unbounded API cost, data-integrity or unsafe publication regression | Stop unsafe work; restore fail-closed and add negative control before paid/production action. |
| **P1** | A real user task cannot finish meaningfully: no substantive final answer, missing attachment/vision, lost follow-up, tool result dropped, false fallback, broken recoverability | Reproduce from an actual trace; fix smallest causal layer; offline end-to-end proof and honest final user message. |
| **P2** | Task finishes but is weak, slow, stale, poorly sourced, fails to adapt, or worse than a fair ChatGPT comparison | Quantify quality/time/correction gap; isolate model vs search vs shell vs UI; repair and remeasure. |
| **P3** | Cosmetic polish, new feature ideas, refactoring and speculative optimization with no demonstrated user deficit | Do only after blockers or with explicit user priority and bounded scope. |

Priority is **not** “the newest branch wins” or “more tests wins.”
Respect the user’s explicit, current task and existing owned worktrees; do not
take over another agent's work or change a frozen contract unilaterally.
P0 conditions override requests to skip safety/authorization gates. Record
new issues outside the approved slice for triage instead of silently expanding it.

## Static Loop (deterministic, no model/API spending)

Use for layouts, UI state, model routing, run/turn identity, attachment propagation,
answer/evidence publication contracts, retry budgets, timing semantics, persistence,
and accessibility. Prefer a traceable failing negative control, narrow code change,
unit/contract tests, Fake Provider + Playwright, and the existing staged L0–L3 gates.

**Static PASS:** exact-code evidence proves the intended invariant under success
and failure cases. Static PASS never claims real model understanding or real-user
task completion.

## Dynamic Loop (real user task, authorized and budgeted)

1. Freeze a realistic user question, attachments, new constraints, and what
   “useful final answer” would mean. Include chat, coding, game guide,
   comparative research, visual and mixed-input cases when relevant.
2. Run Study Agent end-to-end with *actual model/search/tools/UI* only with explicit
   permission, privacy safeguards and a shared durable budget cap. Never run
   live paid examples in standard CI or imply permission from a test name.
3. Independently compare with a **real observed** ChatGPT run using the same
   task, known source/tool differences, and verified external facts when needed.
   ChatGPT is a reference, **not** ground truth or a mandated identical output.
4. Capture provenance separately: user input and follow-ups, model requests
   and provider model IDs, search queries/read outcomes, citations, attachment
   binding and vision events, G1/G2, actual persisted assistant_message,
   visible timestamps, cost reservations, true billed cost when available.
5. Diagnose a gap at the narrowest owner: **model**, **retrieval/source reading**,
   **orchestration/answer publication contract**, or **UI/transport**.
   Test plain-model vs same-model-in-shell when causal attribution is unclear.
6. Convert reproducible defects into Static Loop tests and fixes, then rerun
   a Dynamic Loop comparison **only with fresh authorization and budget**.

**Dynamic PASS:** an end-user-visible, substantive, correct/appropriately
qualified final answer serves the task, including material new constraints and
authorized images when relevant. G1/G2, tool activity, research summaries,
fallback copy, tests and CI are *not substitutes* for a final answer.

## Evidence and release discipline

For a product-affecting PR/handoff, provide these fields (with `not_run` or
`not_applicable` rather than invented outcomes):

| Field | Minimum evidence |
| --- | --- |
| `priority` | P0/P1/P2/P3, reason and real-user symptom (if known) |
| `loop` | static / dynamic / combined |
| `owner` | model / retrieval / orchestration / UI / infrastructure |
| `static_evidence` | exact head, failing case, changed files, negative control, L1/L2/L3 when applicable, exact-head CI |
| `dynamic_evidence` | actual user-visible assistant answer and comparison, or `not_run` with reason |
| `budget_authorization` | approval, persistent limit, ledger/path and scope, or `not_applicable` |
| `decision` | product-go / product-no-go / engineering-only, and next smallest slice |

Prefer `first_substantive_ms`, visible useful information at 10/20/30 seconds,
whether the final answer actually addresses the question, claim correctness,
correction turns, source coverage, failure recovery, and end-user cost.
Time of a fallback or research summary does not count as final-answer latency.
For source-limited answers, publish supported parts while accurately labeling
uncertainty; never launder unverified figures into “general knowledge.”
Attachments must not be claimed read when vision or extraction never ran.

**Release semantics:** Engineering gates can approve a narrow static change.
A product-quality improvement is not `product-go` without dynamic evidence
when the claim concerns live model/search/user experience. Do not block unrelated
docs/security/infra changes merely because a new paid dynamic trial is pending.

## Agent startup, branch visibility, and governance

The agent reads **the policy committed to its checked-out codebase**, normally
the default `main`, starting from root `AGENTS.md` and the current handoff.
Agents are **not required to scan every feature branch** to discover policies.
Once an implementation is validated, publish the durable policy to `main`
through a reviewed PR; do not leave product-wide instructions only on feature
branches, local paths, or ChatGPT conversation history.

The required `product_policy` CI step validates the root entrypoint,
documentation discoverability, and policy structure independently of L1/L2
test-selection. It does **not** prove an AI obeyed its instructions: review
the PR/handoff evidence and verify real runs where needed. Any edit to this
stable policy, ranking or its enforcement requires a deliberate review and
matching contract-test change. Do not add a parallel permanent status/roadmap.
