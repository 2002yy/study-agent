# Paired attribution — model-ability-ab / answer-paired-24

Scores were sealed first (`sealed-scores/SEAL.json`, blind scores sha256
`5D5F3E8A…`, review md `0CC558DF…`) BEFORE reading `organizer-key.json`.

## What the A/B factor actually is
- **Arm A** = structured, production-style planner: `ResearchEpisode.interpret()`
  → structured `unresolved_questions`.
- **Arm B** = free-form planner: `B_PROMPT` → natural-language subquestions.
- **Same model** (`deepseek-flash`), **same fixed evidence**, **same answer stage**.
- So the 4 outputs per question are **2 planning strategies × 2 repeats**, not 4 models.
- (Separately: the same batch runs the answer stage at 20 s / 2800 tokens, vs the
  earlier 5 s / 1400 which left 12/24 blocked → runtime-parameter evidence is the
  parseable-rate jump, NOT these semantic scores.)

## Reveal (label → arm → repeat)
| topic | case | A (r1,r2) | B (r1,r2) |
|---|---|---|---|
| asyncio | H05 | 003=79, 004=95 | 001=90, 024=94 |
| go | H03 | 002=2, 020=2 | 009=2, 019=2 |
| pricing | H01 | 005=75, 016=76 | 014=74, 006=77 |
| calendar | H06 | 022=33, 007=31 | 017=26, 018=34 |
| bridge | H02 | 023=88, 011=88 | 008=88, 012=88 |
| http | H04 | 021=71, 013=79 | 010=86, 015=93 |

## Per-question arm comparison
| topic | A mean | B mean | Δ(B−A) | A repeat spread | B repeat spread |
|---|---:|---:|---:|---:|---:|
| asyncio | 87.00 | 92.00 | **+5.00** | 16 | 4 |
| go | 2.00 | 2.00 | 0.00 | 0 | 0 |
| pricing | 75.50 | 75.50 | 0.00 | 1 | 3 |
| calendar | 32.00 | 30.00 | −2.00 | 2 | 8 |
| bridge | 88.00 | 88.00 | 0.00 | 0 | 0 |
| http | 75.00 | 89.50 | **+14.50** | 8 | 7 |

**Overall: A n=12 mean 59.92, B n=12 mean 62.83, Δ=+2.92 (B).**

## Criterion-level (only non-constant sub-scores)
| criterion | A | B | reading |
|---|---|---|---|
| http `choices` | [0, 8] | [15, 15] | **only non-overlapping gap** — B commits to scenario choice, A refuses |
| http `308` | [9, 9] | [9, 13] | B slightly better on method-preservation |
| asyncio `gather_exception` | [15, 16] | [18, 18] | small, 1 A run drags |
| asyncio `taskgroup_cancel`/`sibling` | one A run low | stable | within repeat noise |
| calendar `british_dates` | [0, 0] | [0, 8] | one B run only |
| calendar `caveat` | [1, 7] | [0, 0] | favors A slightly |

## Attribution (3 buckets)
1. **Model reasoning / arithmetic failure (plan-irrelevant):** go rules (both arms 2/2), pricing critical value (both arms 0/18). No planning strategy fixes these.
2. **Upstream evidence gap:** HTTP 308 (RFC 9110 §15.4.9 erratum 7109 — excerpt genuinely lacks method preservation), UK statute body not extracted. Caps both arms equally.
3. **Answer assembly / decision commitment:** HTTP `choices` is the one place the plan appears to matter (B='free-form' committed, A='structured' hedged). n=2 only.

## Verdict
- Blind review's **semantic NO-GO stands**.
- With the reveal: **no convincing accuracy gain from the A/B planning strategy.** Only Δ(bridge, go, pricing) are exact ties; asyncio +5 is inside a 16-point repeat spread; HTTP +14.5 is the sole candidate signal and rests on one criterion (`choices`) at n=2.
- Report's "cannot claim new config > old" is now confirmed at the plan level. The runtime-parameter conditional GO still rests only on the 12/24→24/24 parseable-rate jump.
- Do **not** enlarge the sample; if the HTTP-planning hypothesis is pursued, pre-register a larger paired run on `choices`/308 alone.
