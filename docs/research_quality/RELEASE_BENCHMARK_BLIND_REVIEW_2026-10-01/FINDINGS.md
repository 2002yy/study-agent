# A3-B2 — first independent-family blind review (2026-10-01)

## Setup

```text
packet schema          release-benchmark-blind-review-packet-v1
review_run_id          rq-review-20261001-001
packet_sha256          60ded5ea3063d016ab58563d2f5dbfc65ff8f7cf3c29f14943cc2a7866b32642
input_manifest_hash    1430b2fcd02341abc67e396d6f131334851d788449a9d3308713c4a0dad533a5
items                  8  (2 frozen real answers + 3 controls x 2 cases)
reviewer_kind          model
provider               OpenAI
model_family           GPT
model_id / revision    gpt-5.6-sol / 2026-10
transport              manual_copy_paste
answer_model_families  deepseek        -> model_family != answer_model_family holds
raw response sha256    7e6098a55d141f3257b445a3a47ff89e4b6f78cb308ddff4fd31dbe498d73b08
```

The reviewer ran in a session with no prior context on this project: it was given
only the bounded reviewer-visible packet, no §161 verdict, no expected labels,
no statement that controls exist, and no target threshold. The operator moved
bytes and contributed no verdict (`transport=manual_copy_paste`).

## Result: calibration FAIL

```text
target detection       6/6   (FN 0)
specificity            4/6   (FP 2)
real answers clean     2/2
target_gate_pass       true
specificity_gate_pass  false
calibration_pass       false
```

Consequences recorded by the artifact itself:

```text
eligible_for_authority_review  false
qualified_judge                false
formal_semantic_label          false
release_observation            false
release_gate                   NO_GO
```

No judge was granted and no label was produced. Per §162 C6 a failed calibration
is NO-GO with no promotion; the gate was not relaxed because the reviewer came
from a different family.

## Where it failed

Both `unsupported_claim` controls. The reviewer found the target axis
(`evidence_grounding=gap`) and named the right issue type, but left
`citation_support=supported`. The frozen expectation is `citation_support=gap`:
the injected falsehood carries a citation to the real locator, and the frozen
rubric states that a citation is not proof that the source supports the sentence.

| control (blind) | variant | expected axes (QC/EG/CS) | observed axes | target | specific |
| --- | --- | --- | --- | --- | --- |
| item-01 | missing_aspect | partial/supported/supported | partial/supported/supported | yes | yes |
| item-02 | wrong_citation | covered/supported/gap | covered/supported/gap | yes | yes |
| item-03 | missing_aspect | partial/supported/supported | partial/supported/supported | yes | yes |
| item-05 | unsupported_claim | covered/gap/**gap** | covered/gap/**supported** | yes | **no** |
| item-06 | unsupported_claim | covered/gap/**gap** | covered/gap/**supported** | yes | **no** |
| item-08 | wrong_citation | covered/supported/gap | covered/supported/gap | yes | yes |

## What this does and does not show

- Not a detection failure: every target was found, both real answers came back
  clean with no issues, and neither violation is a spurious issue.
- A different failure mode from the same-family probe (6/6 detection, 1/6
  specificity, broad over-flagging). GPT under-flags one axis on two controls;
  DeepSeek pro over-flags widely.
- It does **not** establish that this reviewer is unqualified in general. It
  establishes that, under the frozen §161 expectation table, this reviewer does
  not reproduce the required axis mapping on two of six controls.
- It does not adjudicate whether the expectation itself is right. That is a
  contract question (§162 C4 gate is frozen) and is not decided by this artifact.

## Defect found by this execution (fixed in the same slice)

`--ingest` re-wrote the preserved raw response in text mode, so a payload ending
in LF was stored with CRLF and the preserved file no longer matched the original
bytes — the hash chain would have described a re-encoding rather than the
received payload. Ingest now reads and writes bytes, hashes the original bytes,
and requires those bytes to decode to the parsed text. The `raw == response`
byte check above is the direct evidence, and a CRLF regression covers it.

## Next (not decided here)

Two branches, each needing explicit adjudication before any further run:

1. **Contract question** — is "an unsupported but cited sentence must also break
   citation_support" the right §162 expectation, or should the two axes be
   independent? Reopening it changes a frozen table and therefore needs an
   explicit decision, not a quiet edit.
2. **Reviewer question** — run a different independent family, or re-prompt with
   the citation-support rule stated more explicitly (which risks moving toward
   steering, so it needs its own review).

Neither branch is executed here. This artifact stands as the recorded result.
