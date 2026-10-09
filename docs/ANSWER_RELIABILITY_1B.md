# Answer Reliability 1B — reasoning licence, verifiable derivations, calculator wiring

Worktree `D:/study-agent-validation/answer-verification-shadow`, branch
`codex/answer-verification-shadow`, baseline `0cdcfe07` (base `40e0e311`).
Slice 1b. Does **not** modify the frozen 24 A/B answers, the blind review, the
unblind mapping or the sealed scores. RP-1 stays NO-GO.

## Scope (frozen)
| work | decision |
| --- | --- |
| general reasoning licence (facts vs derivations) | implemented |
| verifiable derivation shape | implemented |
| `exact_calculation.py` | reused, not rebuilt |
| `answer_verification.py` | reused + wired (`formula_origin`) |
| `formula_origin` | added, program-derived, downgrade-only |
| `final_answer_auditor.py` | limited wiring (`tool_result_consistency`) |
| B0/B1/B2 diagnostic | implemented |
| B+A planner migration | deferred (Slice 2) |
| go rule engine | deferred (separate slice) |

## What changed
- `tools/research_ability_ab.py`: new `ANSWER_PROMPT_V2` (domain-general; separates
  external facts from user-authorised derivations, no per-subject exemption) and
  `citation_checks_v2` for the derivation schema (`calculations`/`boundaries`/
  `derivations`, numeric or string scalars).
- `src/application/answer_verification.py`: `formula_origin` on proposals;
  `resolve_formula_origin` verifies numeric premises against the original question
  (user_given) or an owned evidence text (evidence_quote) and can only *downgrade*
  to `unverified`; `model_recall` is never a source. Arithmetic `PASS` under an
  unverified formula downgrades the aggregate to `UNKNOWN` (`verified_support=False`).
- `src/web/research/final_answer_auditor.py`: additive `tool_consistency` /
  `attach_tool_consistency` + `AuditResult.tool_result_consistency` (default
  `unverified`, so no caller changes behaviour unless it attaches a report). A
  tool `FAIL` becomes a blocking `tool_result_mismatch`; semantics stay UNKNOWN.
- `tools/run_answer_reliability_1b.py`: B0 old prompt / B1 V2 prompt / B2 V2 +
  calculator, same fixed evidence and plan, same model (`deepseek-flash`).

## B0/B1/B2 evidence (fixed evidence, 20 s / 2800 tokens)
`reading-notebook-ui-evidence/model-ability-ab/answer-reliability-1b/`

| case | arm | result |
| --- | --- | --- |
| H01 pricing | B0 | threshold **12.5** (wrong) |
| H01 pricing | B1 | narrative threshold **20.3125** (right); machine boundary field inconsistent |
| H01 pricing | B2 | machine boundary claimed **17.1875** → tool returned **FAIL boundary_mismatch, exact 325/16 = 20.3125** |
| H03 go | B0 | refused ("无法根据现有证据回答") |
| H03 go | B1 | **full derivation**: C4 legal, captures C3, correct new board; C3 illegal suicide; practice — matches rubric |
| H03 go | B2 | same, correct |

Tool checks on H01 B2: 4/4 line calculations `PASS`; boundary `FAIL` (model value
wrong, tool exact value correct). Structural schema clean in all 6 rows.

## The four questions
1. **Go over-abstention** — fixed by the licence: B0 refused, B1/B2 solved the
   boards. This is a policy failure, not an evidence gap (the question authorised
   "basic rules").
2. **Pricing via the existing calculator** — the tool computes `20.3125` exactly
   and detects the model's wrong value (`FAIL`). A single-call B2 does **not** yet
   feed the value back, so the final prose can still be wrong; a bounded
   reconciliation call is the next step.
3. **Formula without a trusted source** — enforced: `model_recall` is always
   unverified and `PASS` arithmetic cannot upgrade it (unit-tested).
4. **Mechanical wiring** — no false pass (FAIL on mismatch, UNKNOWN on
   unsupported/unverified), no over-budget, no mis-reject. Semantic support stays
   UNKNOWN throughout.

## Limits
- n is 2 cases × 3 arms; H01 sampling variance is large (B1 20.3125 vs B2 17.1875).
- The numeric-premise origin check is conservative and unit-blind: a coefficient
  written as "5 百万" in an evidence text does not match the literal `5`, so some
  true evidence origins are reported `unverified` (safe, never the reverse).
- No go rule engine yet: board legality under stated rules remains UNKNOWN, so B2
  adds nothing mechanical for H03.

## Next
- Bounded reconciliation call for B2 (model re-answers using the tool's exact
  values) to measure whether the calculator actually corrects the final answer.
- Then B+A planner wiring (Slice 2).
