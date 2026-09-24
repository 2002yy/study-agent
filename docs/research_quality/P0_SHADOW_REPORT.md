# RQCE-P0-C5 Shadow Report (gold-blind baseline vs shadow)

> 组件诊断报告，不是 Release Gate。Shadow 输入只来自预记录 projection；Gold 只在 decision 完成后评分。production source assessment、benchmark surface match、independent manual audit 三层保持分离。

- cases fixture: `tests/fixtures/research_quality/frozen_trap_cases.json`
- transcripts fixture: `tests/fixtures/research_quality/legacy_transcripts.json`
- manual live candidate audit: `tests/fixtures/research_quality/live_candidate_manual_audit.json`
- evaluated frozen cases: 10

## Frozen 10 聚合指标

- closed runs: 10/10
- false closures (baseline 误闭环): 7
- shadow blocked runs: 6
- caught false closures (shadow 抓到): 6
- missed false closures (shadow 漏抓): 1
- overblocked correct closures (shadow 误 BLOCK): 0
- primary retrieval rate: 4/7 (57.14%)
- mean useful read ratio: 1.00 (contributing reads 15/15)
- mean evidence-linked critical claim coverage: 90.00% (covered 10/11)
- metric caveat: synthetic frozen transcripts contain no deliberately wasted successful reads; the 1.00 useful-read result is fixture-bound, not a production KPI.

## Frozen 10 逐 case

| case_id | false_closure | violated | shadow | primary retrieval | coverage | useful |
|---|---|---|---|---|---:|---:|
| trap-secondary-only-frozen | True | primary_not_read | block | False | 100% | 1.00 |
| trap-duplicate-source-frozen | True | independent_sources_below_minimum | block | False | 100% | 1.00 |
| trap-old-primary-frozen | True | freshness_unmet | block | True | 100% | 1.00 |
| trap-conflicting-primary-frozen | True | conflict_unresolved | pass | True | 100% | 1.00 |
| trap-no-primary-exists-frozen | False | - | pass | False | 100% | 1.00 |
| trap-community-opinion-frozen | False | - | pass | False | 100% | 1.00 |
| trap-numerical-original-frozen | True | primary_not_read | block | False | 100% | 1.00 |
| trap-causal-competing-frozen | True | conflict_unresolved | block | True | 100% | 1.00 |
| trap-simple-factual-frozen | False | - | pass | True | 100% | 1.00 |
| trap-unanswerable-frozen | True | question_unverifiable | block | False | 0% | 1.00 |

## Live 10 operational observation

- search API status=ok: 10/10
- returned candidates: 50 total
- benchmark surface matches: 10/50 across 2/10 cases
- reads: 6/6 successful in the original observation harness
- cases with provider errors: 8/10
- boundary: this is provider/search/reader observation only; benchmark surface matching is an eval heuristic, not production relevance truth.

## Live 10 semantic projection + shadow

- projection completed: 8/10; unavailable: 2
- external calls: **14 logical / 17 attempts; 5 failed attempts**
- projected public documents: **4**
- evidence-producing cases: **1/10**; 9 produced no public document projection
- persisted payload boundary: URL/title/source metadata, structured labels, hashes and audit only; no page body, prompt or raw model output.

| case_id | projection | false_closure | shadow | primary | useful |
|---|---|---|---|---|---:|
| trap-secondary-only-live | completed | True | block | False | 0.00 |
| trap-duplicate-source-live | unavailable | - | unavailable | - | - |
| trap-old-primary-live | completed | True | block | False | 0.00 |
| trap-conflicting-primary-live | completed | True | block | False | 0.00 |
| trap-no-primary-exists-live | completed | True | block | False | 0.00 |
| trap-community-opinion-live | completed | True | block | False | 0.00 |
| trap-numerical-original-live | completed | True | block | False | 0.00 |
| trap-causal-competing-live | completed | True | block | False | 0.00 |
| trap-simple-factual-live | completed | False | pass | True | 0.75 |
| trap-unanswerable-live | unavailable | - | unavailable | - | - |

- live false closures: 7; caught: 7; missed: 0; overblocked: 0
- caveat: the 7 live blocks are fail-closed under evidence starvation; this is not evidence that the Gate discriminated seven rich evidence graphs correctly.

## Combined evaluated cases

- evaluated: 18/20
- false closures: 14; caught: 13; missed: 1; overblocked: 0
- primary retrieval: 5/13 (38.46%)
- useful reads: 18/19; macro=0.60
- useful-read caveat: live reads are heavily selected toward the one successful evidence-producing case, so this is not a production KPI.

## Live retrieval truth classification (Truth Fix)

The previous C5-C label `RELEVANCE_FALSE_NEGATIVE` was semantically invalid because it was assigned whenever `returned > 0 && benchmark_relevant == 0`. That condition did **not** prove that production relevance rejected a good candidate. The Truth Fix separates:

1. provider/search result;
2. production `source_assessment` (`worth_reading`);
3. benchmark lexical surface match;
4. independent manual audit of whether the candidate can directly contribute answer evidence.

Only `manual=ANSWER_RELEVANT && benchmark_surface_match=false` may be called `BENCHMARK_MATCH_FALSE_NEGATIVE`.

### Truth-fixed taxonomy

| failure_type | count |
|---|---:|
| QUERY_UNDERSPECIFIED | 0 |
| PROVIDER_RECALL_MISS | 0 |
| **NO_ANSWER_RELEVANT_CANDIDATE** | **7** |
| **BENCHMARK_MATCH_FALSE_NEGATIVE** | **0** |
| SOURCE_ROLE_MISMATCH | 0 |
| READ_NOT_SCHEDULED | 0 |
| READ_FAILED | 0 |
| PROJECTION_REJECTED | 0 |
| CLAIM_PROJECTION_UNAVAILABLE | 2 |
| COMPLETED_WITH_EVIDENCE | 1 |

The two projection-unavailable cases retain `CLAIM_PROJECTION_UNAVAILABLE` as the primary failure. Their retrieval-layer condition is preserved separately as a secondary reason rather than overwritten.

### Candidate truth layers

| metric | count |
|---|---:|
| returned candidates | 50 |
| production `worth_reading=true` | **50** |
| benchmark surface matches | 10 |
| independent audit `ANSWER_RELEVANT` | **5** |
| independent audit `TOPIC_ONLY` | 10 |
| independent audit `OFF_TARGET` | **35** |

**Critical finding:** all 50 recorded candidates were considered `worth_reading=true` by the legacy production assessor, including **35 manually audited OFF_TARGET candidates**. In this recorded sample, the benchmark matcher had **0 confirmed false negatives** against `ANSWER_RELEVANT` candidates.

This means the old phrase “7 relevance false negatives” was wrong in both direction and ownership: the stronger observed production issue is **relevance false positives / weak candidate discrimination**, while the upstream search layer often returns off-target results in the first place.

### Per-case retrieval truth

| case_id | primary failure | secondary | returned | prod worth | benchmark match | manual answer | topic-only | off-target | reads | docs |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| trap-secondary-only-live | NO_ANSWER_RELEVANT_CANDIDATE | - | 5 | 5 | 0 | 0 | 0 | 5 | 0 | 0 |
| trap-duplicate-source-live | CLAIM_PROJECTION_UNAVAILABLE | NO_ANSWER_RELEVANT_CANDIDATE | 5 | 5 | 0 | 0 | 0 | 5 | 0 | 0 |
| trap-old-primary-live | NO_ANSWER_RELEVANT_CANDIDATE | - | 5 | 5 | 0 | 0 | 5 | 0 | 0 | 0 |
| trap-conflicting-primary-live | NO_ANSWER_RELEVANT_CANDIDATE | - | 5 | 5 | 0 | 0 | 0 | 5 | 0 | 0 |
| trap-no-primary-exists-live | NO_ANSWER_RELEVANT_CANDIDATE | - | 5 | 5 | 0 | 0 | 0 | 5 | 0 | 0 |
| trap-community-opinion-live | NO_ANSWER_RELEVANT_CANDIDATE | - | 5 | 5 | 0 | 0 | 0 | 5 | 0 | 0 |
| trap-numerical-original-live | NO_ANSWER_RELEVANT_CANDIDATE | - | 5 | 5 | 0 | 0 | 0 | 5 | 0 | 0 |
| trap-causal-competing-live | NO_ANSWER_RELEVANT_CANDIDATE | - | 5 | 5 | 0 | 0 | 0 | 5 | 0 | 0 |
| trap-simple-factual-live | COMPLETED_WITH_EVIDENCE | - | 5 | 5 | 5 | 5 | 0 | 0 | 4 | 4 |
| trap-unanswerable-live | CLAIM_PROJECTION_UNAVAILABLE | NO_ANSWER_RELEVANT_CANDIDATE | 5 | 5 | 5 | 0 | 5 | 0 | 0 | 0 |

## What the recorded candidates actually show

Representative failures are not good sources rejected by a strict benchmark. They are off-target search results:

- GitHub REST rate-limit question → pages for the English word **“current”** and the unrelated Current banking brand;
- CVE-2024-3094 provenance question → dictionary pages for **“independently”**;
- GitHub Actions retention question → **“current”** dictionary pages;
- Microsoft/OpenAI confidential terms and BLS numerical question → **“exact”** dictionary/Excel-function pages;
- Python free-threaded community question → **“do”** dictionary pages;
- CrowdStrike causal question → **“why”** dictionary/entertainment pages.

The Node.js release-schedule case is less extreme: its five results are about Node.js, but none is the official schedule or directly answers which release lines currently receive security updates, so the audit marks them `TOPIC_ONLY` rather than `OFF_TARGET`.

## RQCE-P0 Exit Gate self-check

1. **legacy user-visible behavior unchanged**: Truth Fix changes eval/report artifacts only; no `WebLookupService`, gateway, reader or Gate behavior is changed.
2. **ClaimState/Trace/Gate persistence unchanged**: A2/A3 contracts remain intact.
3. **20-case harness repeatability: PASS / COMPLETE**: frozen fixtures deterministic; live execution protocol/schema/runner re-executable; report derives from structured artifacts.
4. **False Closure reasons remain explicit**: claim/gap reasons remain recorded by the shadow runner.
5. **unknown evidence ID still fails closed**: existing runner/state validation remains unchanged.

## P0 Exit Decision after Truth Fix

**RQCE-P0 harness = PASS / COMPLETE; production activation = NO-GO.**

The recorded live bottleneck is now stated more precisely:

> **pre-read retrieval quality failure = query formulation / degraded-provider fallback / first-nonempty acceptance + weak production candidate discrimination.**

The data do **not** support “benchmark matcher is too strict” as the primary explanation (`BENCHMARK_MATCH_FALSE_NEGATIVE=0` in the independent audit). They also do not support fixing production by copying the benchmark lexical threshold.

### P1 implementation direction

Before changing runtime behavior, P1 should audit and then address this order:

1. **SearchIntent / focused query formulation** for natural-language research questions;
2. **remove first-nonempty success semantics** across query/provider fallback; merge bounded diverse query results into a CandidatePool;
3. **role-aware CandidatePool + rerank**, so topical/source-role fit matters more than one-token lexical overlap;
4. only then tune read scheduling and downstream evidence extraction.

Do **not** implement `worth_reading = benchmark_relevant` and do not treat a lexical overlap threshold as production truth.
