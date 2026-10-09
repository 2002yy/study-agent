# Answer Reliability 1C — bounded reconciliation and final-answer repair

Worktree `D:/study-agent-validation/answer-verification-shadow`, branch
`codex/answer-verification-shadow`, baseline `6e091473`. Slice 1c. Does not
modify the frozen 24 A/B answers, the blind review, the mapping or sealed
scores. RP-1 stays NO-GO.

## Goal
Close the loop the previous slice left open: **tool detects error → repair the
final answer → verify again**. Reuse `exact_calculation.py`,
`answer_verification.py` and `final_answer_auditor.py`; no second verifier.

## Frozen contract (implemented)
| stage | owner | rule |
| --- | --- | --- |
| initial answer | DeepSeek Flash | answer + structured derivations |
| deterministic check | existing calculator | PASS / FAIL / UNKNOWN |
| repair admission | program | only a FAIL row with an exact value |
| bounded reconcile | DeepSeek Flash | max 1 call, 8 s / 600 tokens, affected fragments only |
| numeric authority | program | final number = tool exact value (+ re-straddled probes) |
| second check | program | repaired rows PASS + answer carries the exact value |
| final audit | existing auditor | semantic UNKNOWN, original publication gate |

## Files
- `src/application/answer_reconciliation.py` (new): `admit_repair`,
  `repair_messages`, `parse_repair` (accepts only `{"answer": str}`),
  `apply_numeric_authority` (overwrites FAILed results with exact values and
  re-straddles stale boundary probes), `answer_mentions_values`.
- `src/application/answer_verification.py`: boundary rows now expose
  `left`/`right`/`variable` for traceability.
- `tools/run_answer_reliability_1b.py`: added arm `B2R`, which **reuses B2's
  exact answer** (paired, not re-sampled) and then runs tool + one bounded
  repair.
- `tests/test_answer_reconciliation.py`, gate entries in `tests/stage_gates.json`.

## Live evidence (fixed evidence, 20 s / 2800 + one 8 s / 600 repair call)
`model-ability-ab/answer-reliability-1b/`

| run | B2 boundary | admitted | repair calls | second check | answer carries value |
| --- | --- | --- | --- | --- | --- |
| sample A | PASS | no | 0 | n/a | n/a |
| sample B | **FAIL** | yes | 1 (330 tok) | **PASS** | **true (20.3125)** |

Sample B (captured): B2 claimed threshold `12.5`; the tool proved the root
`325/16 = 20.3125`; the one bounded repair call rewrote the affected
explanation; the program filled the authoritative value and moved the probes to
straddle the true root; the second check passed and the final answer now states
`x = 20.3125 百万事件/月`.

## The three questions
1. **Can the tool detect the error?** Yes — B2 boundary `FAIL boundary_mismatch`
   with exact value `20.3125` (stable; also `FAIL arithmetic_mismatch` on a
   residual calculation).
2. **Can it correct the final answer?** Yes, within one bounded call: second
   check PASS and the revised answer contains the authoritative value.
3. **Any new dangerous error?** No. The repair touches only the answer text; the
   program owns the number; claims/citations/sources are untouched; a formula
   whose origin is unverified keeps `verified_support=False`; `tool_result`
   dimension stays `unverified`; semantic support stays UNKNOWN.

## Cost (must be recorded)
B2-R is not the same budget as B2: it adds at most one call at 8 s / 600 tokens
(observed 330 completion tokens, 1.17 s in sample B). The row records
`repair_meta`/`repair_elapsed_seconds`; a repair that stays inconsistent keeps
FAIL with no retry.

## Limits
- The repair prompt/flow fixes arithmetic only; board legality (H03) still has no
  rule engine, so B2-R does not admit a go repair (`no_determinable_fail`).
- `answer_value_consistent` checks boundary roots only (the user-facing critical
  value); residual calculation rows are recorded but not required in prose.
- Sampling variance is large at n=1 live samples; the paired B2→B2-R design
  removes the initial-answer variance but not the repair-call variance.

## Next
B+A planner work is a separate slice; the live bottleneck is that B decomposes
into many subquestions but actual body reading is still thin, so the next main
line should drive subquestions into real search/evidence reading (query sharing,
target coverage), not add more planning layers.
