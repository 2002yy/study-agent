# repeat-002 — second response to the same packet (diagnostic only)

## What this is

A **second** reviewer response for the **same** frozen packet, recorded because
the operator supplied it after the first result was adjudicated.

```text
review_run_id        rq-review-20261001-001   (same packet, same blind ids)
packet_sha256        60ded5ea3063d016ab58563d2f5dbfc65ff8f7cf3c29f14943cc2a7866b32642
output_hash          8a299be8a26d037738580fbbbcff790aac6c4db38acb53b3f30ac6bf0f9b9294
first response hash  7e6098a55d141f3257b445a3a47ff89e4b6f78cb308ddff4fd31dbe498d73b08
```

The first response is preserved unchanged in the parent directory. This one is
distinguished from it by `output_hash`, since both share the run id and the
input manifest hash.

## Result: still FAIL

```text
target detection       6/6   (FN 0)      unchanged
specificity            5/6   (FP 1)      was 4/6
real answers clean     2/2
calibration_pass       false
eligible_for_authority_review / qualified_judge / formal_semantic_label  false
release_gate           NO_GO
```

| control (blind) | variant | expected axes | first run | this run |
| --- | --- | --- | --- | --- |
| item-01 | missing_aspect | partial/supported/supported | specific | specific |
| item-02 | wrong_citation | covered/supported/gap | specific | specific |
| item-03 | missing_aspect | partial/supported/supported | specific | specific |
| item-05 | unsupported_claim | covered/gap/gap | **not specific** (CS=supported) | **not specific** (CS=supported) |
| item-06 | unsupported_claim | covered/gap/gap | **not specific** (CS=supported) | specific (CS=gap, + wrong_citation) |
| item-08 | wrong_citation | covered/supported/gap | specific | specific |

The single improvement is item-06, and it arrives by a different route: the
reviewer added a `wrong_citation` issue for the missing `#page=2` suffix rather
than applying the semantic citation rule it still declines on item-05. Two items
of the same class are treated inconsistently by the same reviewer, which is
diagnostic evidence of axis-semantics instability rather than of a contract
defect.

## Governance status: cannot qualify, whatever the score

Per §162 **C7** (frozen after A3-B2) this set is
`CONSUMED_FOR_QUALIFICATION_SELECTION`. A second response against it:

- cannot be used for qualification, even at 6/6 + 6/6;
- must not be produced by pointing the reviewer at the known failure locations
  (targeted re-prompt = calibration-set overfitting);
- does not change the A3-B2 verdict, which stands as FAIL.

## PROVENANCE: DIAGNOSTIC_REPEAT (confirmed by the operator 2026-10-01)

```text
provenance_class          = DIAGNOSTIC_REPEAT
session_isolation         = fresh_session
packet                    = original_frozen_packet
failure_position_disclosed = false
steering                  = false
qualification_use         = FORBIDDEN
```

Confirmed: a fresh isolated session, the original frozen packet, no disclosure
of the failure positions and no steering. It is therefore legitimate diagnostic
evidence about reviewer axis behaviour.

It still cannot qualify anything: C7 marks this calibration set
`CONSUMED_FOR_QUALIFICATION_SELECTION`, so a repeat on it is forbidden for
qualification **even if it had reached 6/6 + 6/6**.

## What the repeat strengthens

```text
item-05  still reports citation_support = supported
item-06  now reports gap, but via an extra wrong_citation issue
         (missing #page=2 suffix) rather than the semantic rule
```

So the reviewer's axis mapping for the structure
`unsupported_claim + real locator + semantic mismatch` is **not stable**: two
items of the same class were treated differently by the same reviewer in the
same session. That is diagnostic evidence about axis semantics, not about the
frozen expectation table, and it is recorded as such.


## Defect found while evaluating this response (fixed)

The ingest artifact mapped per-item verdicts by variant, so two items sharing a
variant both showed the first verdict of that variant. The aggregate counts were
always correct (they come from the checker's positional verdict list), but the
per-item table could misattribute a pass or a fail to the wrong blind case —
which would have made this very comparison wrong. Verdicts are now paired
positionally and a regression breaks exactly one of two same-variant controls.
Regenerating the committed first-run artifact reproduces it identically apart
from the ingest timestamp.
