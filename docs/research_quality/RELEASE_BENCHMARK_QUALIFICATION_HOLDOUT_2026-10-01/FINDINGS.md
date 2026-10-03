# A3-D-3 — fresh composite qualification holdout, first attempt (2026-10-01)

## Setup

```text
holdout              RQ-QUAL-HOLDOUT-v1
composite sha256     e5da77caec1905a361c9720bf6b384a1225da76a7e09c07c5a8515f575c133b9
cluster A            CLUSTER-A-NWS-HEAT    fixture d99fc107...   source 3663875d... (NWS-HEAT)
cluster B            CLUSTER-B-NOAA-TIDES  fixture 0f5fd6a7...   source 276fa82d... (NOAA-TIDES)
packet_sha256        f8d3ff81af3adff8f5ee69222642fb4703290fa034e68e73cea8b3048f4168f5
items                16 (2 clusters x 2 instances x (1 baseline + 3 controls))
reviewer             model / OpenAI / GPT / gpt-5.6-sol / 2026-10
session              fresh and isolated; the packet was the first and only message
transport            manual_copy_paste (operator moved bytes, contributed no verdict)
answer_model_family  deepseek  -> model_family != answer_model_family holds
output_hash          afcaf52dc360d741e3b59582226b0a05bb117cb80d02d801117862bd933fbab8
```

The packet was emitted from the holdouts frozen before execution, wrapped in
explicit reviewer-visible boundaries, and verified leak-free (no cluster,
composite, gate, holdout, qualification, calibration or specificity vocabulary).
The reviewer was told nothing about the consumed calibration set, the previous
attempt, the failure axis, the cluster structure, the per-cluster gate or the
threshold. `packet.txt` itself is not committed; it is regenerable from the
frozen fixtures and its digest is recorded above.

## Result: FAIL, and it reproduces the previous failure signature

```text
CLUSTER-A-NWS-HEAT    target 6/6   specificity 4/6   clean answers 2/2   pass = false
CLUSTER-B-NOAA-TIDES  target 6/6   specificity 4/6   clean answers 2/2   pass = false
overall_pass          false
eligible_for_authority_review  false
qualified_judge / formal_semantic_label / release_observation  false
release_gate          NO_GO
```

Both clusters fail, so the conjunction fails. No judge was granted, no label was
produced, and the result was not re-sampled.

| blind | variant | cluster | expected (QC/EG/CS) | observed | target | specific |
| --- | --- | --- | --- | --- | --- | --- |
| item-01 | unsupported_claim | A | covered/gap/**gap** | covered/gap/**supported** | yes | **no** |
| item-04 | unsupported_claim | A | covered/gap/**gap** | covered/gap/**supported** | yes | **no** |
| item-08 | unsupported_claim | B | covered/gap/**gap** | covered/gap/**supported** | yes | **no** |
| item-16 | unsupported_claim | B | covered/gap/**gap** | covered/gap/**supported** | yes | **no** |
| item-02, 03, 09, 14 | missing_aspect | A/B | partial/supported/supported | exact | yes | yes |
| item-10, 12, 13, 15 | wrong_citation | A/B | covered/supported/gap | exact | yes | yes |
| item-05, 06, 07, 11 | baseline | A/B | clean, no issues | exact | — | — |

Every control that failed is an `unsupported_claim`, and all four failed the same
way: the unsupported sentence was correctly detected on the evidence axis, while
`citation_support` was left `supported` even though the sentence carries a
citation to the real frozen locator whose content does not support it. No
spurious issues were raised anywhere; both real answers came back clean in both
clusters.

## What this establishes

This is the first **cross-document, cross-topic, fresh-holdout reproduction** of
the A3-B2 signature. The consumed-set attempt (`rq-review-20261001-001`) failed
with 6/6 detection and 4/6 specificity, failing exactly the two
`unsupported_claim` controls on `citation_support`. On a pre-registered holdout
built from two different documents and two different topics, with different
claim surface forms and no reused item content, the same reviewer produces the
same numbers and the same single-axis error.

That upgrades the finding from "single axis-semantics instability" to a
**reproducible reviewer-family failure mode**: for this family, an unsupported
but cited sentence is treated as `evidence_grounding=gap` while `citation_support`
is left `supported`, so the reviewer does not distinguish "the citation resolves
to a real source" from "the citation supports the sentence". The frozen
expectation is unchanged and was not relaxed.

Scope limits, recorded so the claim is not overstated:

- this characterises one reviewer family and version, not models in general;
- it says nothing about whether another family would pass;
- it does not establish a contract defect: `citation_support` is defined
  semantically in the frozen rubric, and the reviewer was given that definition;
- the earlier `DIAGNOSTIC_REPEAT` on the consumed set and this fresh attempt
  agree, which is evidence about the reviewer, not about the holdout design.

## Next (not decided here)

The infrastructure is now validated end to end: a fresh holdout, a leak-free
packet, a byte-preserving ingest, per-cluster gates and a full digest chain. The
qualification attempt itself failed, so no authority step is available. Any next
step is an explicit decision, not an automatic retry: either accept the family
characterisation as the current limit of qualified semantic judging, or qualify a
different reviewer against this same frozen holdout (which would now also carry
the interpretability caveat that the reviewer family changed between attempts).
