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

**Correction to an earlier inference in this review.** The same-family probe's
1/6 specificity is broad over-flagging; unless it is shown that its errors
concentrate on the same `unsupported_claim -> citation_support` cell, it is **not**
a second independent data point about that cell. The accurate conclusion is:
GPT exposes a reviewer interpretation risk between *citation support* and
*citation existence/validity*, while the frozen rubric already defines
`citation_support` semantically ("a citation is not proof that the source
supports the sentence"), so this round does **not** establish a contract defect.

## Defect found by this execution (fixed in the same slice)

`--ingest` re-wrote the preserved raw response in text mode, so a payload ending
in LF was stored with CRLF and the preserved file no longer matched the original
bytes — the hash chain would have described a re-encoding rather than the
received payload. Ingest now reads and writes bytes, hashes the original bytes,
and requires those bytes to decode to the parsed text. The `raw == response`
byte check above is the direct evidence, and a CRLF regression covers it.

## Finding (adjudicated 2026-10-01)

```text
A3-B2                  = FAIL
cause class            = REVIEWER_AXIS_UNDERDISCRIMINATION
observed               = unsupported_claim correctly detected as
                         evidence_grounding=gap, but the reviewer treated a real
                         citation locator as citation_support=supported even
                         though the cited source does not semantically support
                         the claim
contract decision      = RETAIN FROZEN EXPECTATION
qualification          = NONE
current calibration set = CONSUMED_FOR_QUALIFICATION_SELECTION
                          RETAINED_AS_DIAGNOSTIC_REGRESSION
```

The two axes are not redundant, and the frozen expectation is retained:

```text
evidence_grounding : is there support for this sentence anywhere in the allowed evidence?
citation_support   : does the specific citation attached to it actually support it?
```

A citation that resolves to a real, registered locator can still fail to support
the sentence it is attached to; conversely a true statement can be attached to
the wrong source. GPT's item-05/06 reading ("the claim has no evidence, but the
citation points at a real source, so the citation is supported") is an axis
semantics confusion, not a defect in the frozen table.

## Next (adjudicated, not executed here)

Contract retained, this reviewer's qualification attempt recorded as FAIL, and
**no retry on this set**:

- no targeted re-prompt of the same reviewer against the same six items
  (calibration-set overfitting - even a later 6/6 + 6/6 could not qualify);
- no rotating families until one passes (reviewer selection bias);
- this set becomes a diagnostic regression only.

The next slice is a **fresh independent qualification holdout**: same structure
(6 target / 6 specificity), new instances, new sources and new claim surface
forms, with expected axes frozen **before** the reviewer runs. It must keep at
least one item shaped as *unsupported claim + structurally valid citation +
real locator + locator does not semantically support the claim*, without reusing
item-05/06 content, so that a later pass shows the reviewer learned the rule
rather than these two items.
