# M4-C5 sealed question set - errata candidates (do not edit the sealed questions)

The sealed set is the project's frozen evaluation input. When the wording looks wrong, it is
recorded here instead of being changed: editing a question to raise the pass rate would destroy
the measurement. The scoring stays as written; the erratum is for interpreting failures.

## Q4 - Factorio "天赋网络" (recorded 2026-10)

- Question as sealed: Factorio 中物流机器人的天赋网络与物流网络有何区别？
- Observation: the official Factorio wiki does not use "天赋网络" as a term. The related systems
  are the **circuit network** (信号网络 / 电路网络) and the **logistic network** (物流网络).
- Consequence seen in the run: the goal's subject terms do not match the pages that actually
  explain the systems, so all qualified windows were rejected (zero windows reached extraction)
  even though four substantive bodies had been read.
- Decision: the sealed question is NOT edited and the rules are NOT loosened to compensate. The
  run is recorded as `material_incomplete` for this question, and the term mismatch is listed
  here as a question-set issue rather than a research-chain defect.

## Q1 - engine result set quality (recorded 2026-10)

- Question as sealed: Python 3.12 中 PEP 701 对 f-string 的改动带来了哪些新能力与不兼容风险？
- Observation in the first product batch: the search engine answered with an unrelated video
  portal, so no confirmable URL existed and the run read nothing. The safety rail correctly
  rejected the model's own URL guess.
- Action taken: a result set whose hosts and titles never mention the question's subject is now
  treated as a search failure and the reserved recovery slot is used for a subject-keyed query
  (commit 8cd73269). This is a chain fix, not a question change.
