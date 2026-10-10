# M4-C0 archive + Slice-1 frozen contract + Q1 scoring contract

Baseline main: **`c4c409f9d94e14b606c9df0e3cb078ae77225890`** (M4-B merged).
Frozen M4-C0 evidence: `D:\study-agent-validation\M4-C0-baseline\` (see `MANIFEST.sha256`).

## 1. M4-C0 archive (accepted conclusion)

**First main information loss is candidate discovery / source quality**, so the next
slice is deep-page discovery and effective reading — NOT evidence binding.

Observed on 9/9 real observation records (3 phases x 3 task types, one question each):

- every cell got search results (15–20 per query); **0/9 cells obtained the actual
  answer page** (bodies were homepages / overviews / platform pages);
- **6/9 cells show a correct deep page rejected by the URL gate** because it was never
  discovered by a legal path (the gate behaviour is correct and stays unchanged);
- **0/18 required sub-goals reached SUPPORTED** under the external term-match audit
  (a lower bound: rule-derivation answers such as 围棋 打劫 / 禁全同 are under-counted).

### Three budget/mechanism corrections (verified in code at `c4c409f9`)

| Claim | Verified fact |
| --- | --- |
| Shadow time budget is 20 s, not 60 s | `research_shadow_seam.BSEARCH_SHADOW_BUDGET_SECONDS = 20.0`, and the default runner passes `hard_seconds=budget_seconds`; defaults are **6 rounds / 4 searches / 3 reads / 20 s**. The M4-C0 matrix used a **custom evaluation runner** at `6/4/3/60` — that is a comparability caveat, not the Shadow default. |
| `follow` consumes the read quota | `research_tool_agent.py`: the `follow` branch (guarded at L402) increments `reads` at **L432**; `read_page` increments at **L518**. Two follows leave only one read of three, so "followed but never read the target" can be **quota exhaustion**, not merely a policy choice. |
| The Shadow's own sub-goal state is not a semantic audit | The default runner passes only question + budget to `run_tool_agent` — no `sub_goals`, and `handoff` is used only for decision-input hashing, never as seeds. The 0/18 figure is an **external** term-match audit, not the Shadow's per-sub-goal verdict. |

## 2. Frozen comparison baseline

- main `c4c409f9…`; the 9 M4-C0 records + the runner/analyser scripts + `MANIFEST.sha256`
  under `M4-C0-baseline`; the M3 traces remain as secondary evidence.
- Any later evaluation question set is **sealed** before use: added to the baseline
  directory with its hash, never reworded after seeing results.

## 3. Slice-1 (approved direction): deep-page discovery and effective reading

One bounded slice, one PR, one concentrated verification. Frozen scope:

| Area | Work | Constraint |
| --- | --- | --- |
| Candidate tracing | Distinguish raw links -> filtered -> shown-to-model -> confirmed source -> actually read | evaluation observability only |
| Deep-page discovery | Audit the existing `follow` extraction, classification and top-10 ordering | **no change to the URL security boundary** |
| Candidate use | Confirmed, high-relevance content pages take precedence over repeated searches and irrelevant homepages | **no budget increase** |
| Error recovery | After a guessed deep link is rejected, direct the model to already-confirmed candidates; never silently approve a guessed URL | keep the gate rejection |
| Regression | Reproduce the Python / K8s / Factorio / Minecraft / Go failures while protecting existing successes | — |

Note: the prompt already asks the model to prefer concrete articles, so adding more
"please read the deep page" text is NOT the fix. First establish whether the right
candidate is extracted, ranked and shown; only then add a deterministic preference.

### Acceptance criteria (freeze before changing anything)

| Item | Condition |
| --- | --- |
| Link-source safety | model-guessed, unconfirmed URLs are still rejected |
| Deep-page recall | when the target link exists on a discoverable page, it enters the legal candidate set |
| Candidate use | when the target is a candidate and budget exists, repeated searches and directory wandering are avoided |
| Resource use | rounds / searches / reads / time limits unchanged |
| Result credibility | the shadow still gains no evidence or publication authority |
| Regression | Lookup / Standard / Deep production decisions unchanged |

**Two separate success metrics** (keep them apart so search gains and action-policy
gains are attributable):

- **discovery rate** — does the needed page become a legal candidate?
- **utilisation rate** — once it is a candidate, does the system actually read usable text?

If the target never appears on any entry page, that is source-discovery shortfall, and
the model must not be forced to read it.

## 4. Q1 scoring contract (frozen; NOT in production logic)

| State | Meaning |
| --- | --- |
| SUPPORTED | direct evidence in read text |
| DERIVED | a trusted rule/fact plus a reviewable derivation |
| PARTIAL | only part of the required conclusion is supported |
| MISSING | insufficient basis |

Conflict and wrong-evidence-source are recorded as **separate markers**, not states.
Example: a 围棋 打劫 answer that knows the rule and correctly plays out the position is
**DERIVED** — it does not need an online page with the identical question.

This is the "Arm C" split: the model proposes research directions, a deterministic
program verifies structure/computation/rule constraints, and an independent audit
prevents false support. Q1 only freezes the scoring contract this round; it must not
enter production judgement logic.

## 4b. Slice-1 implementation notes (this PR)

**Follow ranking audit — no defect found.** `link_discovery.rank_candidates` already
penalises site roots (`home` prior −3.0), penalises noise (−5.0), scales the `article`
prior by question coverage, weights rare query terms, and ranks a narrower target above
a broader one. So the loss is not the ranking algorithm; it is (a) whether the
answer-page link exists on the followed entry page, and (b) whether the model uses the
candidates it already has under a shared read quota.

**What this PR changes (no URL boundary, no budget change).**

- `confirmed_unread` is shown to the model each round: the already-discovered,
  not-yet-read URLs with their basis, ordered by question-term hits, then deep pages
  before site roots, then stable bases (`followed_link` / `feed_entry` /
  `search_result` / `initial_urls` / `registry_seed`). This orders access the run
  already legitimately has; it grants nothing new.
- A gate rejection now names the confirmed candidates to read instead, and says
  guessing is not evidence. The rejection itself is unchanged.
- `candidate_trace` records the pipeline per call: search (results, shown, excluded),
  follow (raw candidates, ranked, shown, page types, newly confirmed) and read
  (admitted, basis). This is what makes discovery-vs-utilisation measurable.

**Real sanity run (2 cells, not the paired re-test).** deep/K8s and lookup/Python at
6/4/3/60: gate rejections went from 1-per-cell in the frozen baseline to **0/2**, and
both cells read two confirmed candidates instead of spending the slot on a guess. The
bodies were still site roots / overviews, not answer pages — so utilisation improved
while discovery quality remains the open half for M4-C1.

**Narrow fix (same PR, after review).** `confirmed` does **not** imply `eligible`:
sources recorded in `entry_exclusions` for the current question are no longer offered as
`confirmed_unread`, and the read gate itself is untouched (the source fact stays as
diagnostics). Read accounting is split into
`confirmed / eligible / attempted / succeeded / failure_reason` instead of one
`admitted` flag, and `newly_confirmed` is a true diff against what was known **before**
the call, so a repeated discovery is not counted again. Tests add a deep-page end-to-end
case (follow a directory -> a new deep page becomes a legal candidate -> it is shown ->
the read succeeds with basis `followed_link`) and a negative control (an excluded
candidate is never recommended while the gate still rejects it).

## 5. Order of work1. M4-C0 archived (this document) with the corrected budget/quota semantics.
2. Baseline frozen.
3. Slice-1 implemented in one bounded PR, then verified once.
4. M4-C1 paired re-test: original vs fixed vs existing research paths, reporting quality
   and cost separately; offline replay is never presented as a live-network result.
5. Only then revisit Q2 / Reader / M5.

Frozen boundaries: production B OFF; RP-1 NO-GO; M5 NO-GO; evidence gate, budgets and
production search sources unchanged; full text capture stays opt-in.
