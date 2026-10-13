# M4-C5 experimental research capability (default OFF)

This document records the current state of the optional evidence-loop research capability
(`evidence_loop` / `discovery_hops`). It is an experimental technical note. It is **not** a
release announcement: the capability remains default OFF, production B search stays OFF, and
M4-C5 is still NO-GO for release.

## What it does

Within one research run, the loop:

1. searches and reads real pages under the ordinary budget (12 rounds / 4 searches / 6 reads /
   90 s in the standard tier, 180 s and 22 model calls as global hard caps);
2. selects evidence windows deterministically - a page whose dominant subject is another
   product contributes nothing, a passage must be about the asked-about subject and state a
   relation rather than a bare mention, and candidates are taken per region of a page so a long
   page keeps its later mechanism text;
3. extracts candidate claims with citations in one batched model call;
4. verifies each claim independently (quote located in the read body, span recorded) and
   records a raw verdict (`supported` / `contradicted` / `insufficient` / `unavailable`);
5. settles a goal only when every necessary requirement is covered by a claim that is **both**
   verified and attributed to the asked-about subject.

## Attribution rule

A verified claim keeps its raw verifier verdict, but only counts as coverage when it is
attributed to the asked-about subject. A page whose dominant subject is another product
("mention-mass" comparison against the goal's tokens and the question's own subject words, no
product glossary) is recorded with `attribution_pending`, never settles a goal, never suppresses
a follow-up query, and is written to the review channel as `attribution_unconfirmed`.
Goal state is derived from the final eligible coverage set, so the order in which verdicts
arrive cannot change it.

## Experimental results

Fixed pre-extraction checkpoint (same real bodies, goals, sides and budget; only the window
selector differs), 2 runs per arm:

| arm | windows | claims | supported | quotes located in body | unit cost (extract+verify calls per supported claim) |
| --- | --- | --- | --- | --- | --- |
| previous selector | 4 / 4 | 0 / 0 | 0 / 0 | - | N/A |
| new selector | 4 / 4 | 7 / 5 | 6 / 4 | 6/6 and 4/4 | 0.50 / 0.75 |

Long chain on the natural networked path (standard tier, three runs each):

| case | outcome | searches | reads | model calls | automatic recovery | supported | quotes located | goal status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| PostgreSQL | verified x3 | 3/4 | 6/6 | 14 | 0 | 1 per run | located | MVCC supported (attributed source), cost goal explored |
| Minecraft | verified x3 | 4/4 | 6/6 | 14 | 1 per run | 8 / 6 / 8 | all located | hopper supported, dropper explored |

Small samples only. `verified` means evidence that passed verification exists; it does not mean
the whole question has been answered - PostgreSQL's cost requirement and Minecraft's dropper
requirement stay `explored`/`insufficient` in every run so far.

## Known limitations

The capability can verify that a quoted text exists and that it supports a candidate claim, and
it can detect some cases where a source's dominant subject does not match the question.
Cross-product comparisons and content with unclear attribution may still need human review.
Passing citation verification does not mean the research question has been fully resolved.

## Default-off and release qualification

- Default OFF: `evidence_loop=False`, `discovery_hops=False`. With the loop off the qualified
  selector is never reached (measured: zero calls) and the legacy selector is byte-identical.
- No user interface consumes `attribution_unconfirmed` yet. When the capability is enabled for
  users, a separate UI slice should surface only affected results ("source attribution
  unverified"), with the quote, source and affected goal available; no global banner and no
  change to the main research conversation structure.
- Release qualification still requires long-range evidence and closure of the attribution risk;
  this document does not change that.
