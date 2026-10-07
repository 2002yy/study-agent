# Deep-4A Audited Publication Candidate Contract

**状态：FROZEN semantics**

**Implementation gate：**

```text
Deep-3 merge commit:
e5382659b0aa1deca9954702b108aa51ef745e93

AND

exact-main ordinary CI green
AND

Deep-3 CLOSED recorded
```

Deep-3 exact-main CI 未成功前：

```text
允许：
  contract/docs
  seam audit
  test design

禁止：
  Deep-4A production implementation
  production activation
```

---

# 1. Authority

当前 Deep-4A seam authority：

```text
e5382659b0aa1deca9954702b108aa51ef745e93
```

该 exact-main 上已经确认以下 seam 相对 Deep-3 reviewed candidate byte-identical：

```text
src/application/deep_continuation.py
src/repositories/deep_continuation_repository.py
src/application/deep_trigger.py
src/application/research_web_lookup_dispatch.py
src/web/research/research_brief_projection.py
src/web/research/synthesis_assembler.py
src/web/research/final_answer_auditor.py
```

既有 authority：

```text
Standard
  c48a1ac313e59ab0104364db519340f1460e84dc
  L3 37514856913

Deep-1
  e5c63c03c9ac77b273f2bfc158111ac676e9bc42
  CI 37599443309

Deep-2
  1514bbf76031dfeca2cb03e9c52adf5d149cd724
  CI 37628909373

Deep-3T
  823265ae113c0f488e0e8d2d0a448c6079b80884
  CI 37642664449

Deep-3
  semantic PASS
  merged e5382659b0aa1deca9954702b108aa51ef745e93
  exact-main CI must still close before implementation
```

---

# 2. Deep-4 split

Deep-4 is explicitly split:

```text
Deep-4A
  Deep result
  → ResearchBrief
  → synthesis candidate
  → mechanical + abstaining semantic audit
  → durable audited publication candidate

Deep-4B
  qualified semantic judge
  → publication approval
  → answer revision / user-visible cutover
```

Deep-4A does **not** publish a replacement answer.

Deep-4B is separately qualification-gated.

---

# 3. Deep-4A single objective

Deep-4A converts a valid Deep terminal into a durable, bounded, reproducible:

```text
audited-but-not-approved publication candidate
```

without granting answer authority.

Canonical flow:

```text
Deep-3 parent completed
→ PUBLICATION discovery
→ durable deep_publication pending
→ reload Deep child
→ validate source
→ load validated active ResearchState
→ ResearchBriefProjection
→ unit-safe EvidencePayload projection
→ deterministic synthesis
→ Final Answer Auditor
→ durable deep_publication audited
```

---

# 4. Non-goals

Deep-4A must not:

```text
replace assistant_message
append a second assistant ChatTurn
modify pedagogy_snapshot
modify learning_state
publish research memory
grant semantic authority
choose a semantic judge
call an LLM
call search
call reader/network
rerun Deep research
modify ResearchState
approve a final answer
```

---

# 5. Publication authority

Throughout Deep-4A:

```text
publication_authority = false
```

There is no successful Deep-4A transition that may set it to true.

Any implementation containing:

```text
publication_authority = true
```

inside the Deep-4A path violates this contract.

---

# 6. Semantic judge authority

Current qualified semantic judge:

```text
NONE
```

The existing `FinalAnswerAuditor` default:

```text
judge=None
→ abstaining_judge
→ audited-but-not-approved
```

is the only production semantic configuration allowed in Deep-4A.

Forbidden:

```text
judge=<some model>
judge=GPT-5.6
judge=DeepSeek
judge=the answer model
judge=any caller-supplied model
```

without a separately frozen qualification authority.

---

# 7. Why a model cannot simply be injected

Existing reviewer qualification failed on fresh holdout:

```text
target detection     6/6
specificity          4/6
qualified_judge      false
formal_semantic_label false
release              NO-GO
```

Therefore:

```text
mechanical synthesis validity
≠
semantic publication approval
```

Deep-4A preserves that distinction.

---

# 8. Existing layers are authoritative

Deep-4A reuses:

```text
claim_engine_load()
build_research_brief_projection()
collect_evidence_payloads()
assemble_synthesis_draft()
audit_final_answer()
```

It must not introduce:

```text
DeepResearchBrief
DeepSynthesis
DeepFinalAnswerAuditor
DeepEvidenceGate
DeepSemanticJudge
```

---

# 9. ResearchState authority

The Deep child remains the sole data plane.

Deep-4A loads:

```text
child WebLookupRun
→ claim_engine_load(child)
```

and requires:

```text
available == true
effective_mode == active
state != None
```

The parent never receives a copied `ResearchState`.

---

# 10. ResearchState immutability

Before all projection work:

```text
before = canonical ResearchState bytes/digest
```

After:

```text
ResearchBrief
EvidencePayload
Synthesis
Audit
```

the state digest must be unchanged.

Deep-4A is read-only with respect to research truth.

---

# 11. Durable namespace

Deep-4A owns exactly one parent control-plane key:

```text
rag_snapshot.deep_publication
```

Schema:

```text
deep-publication-v1
```

This key represents a publication **candidate/audit**, not a published answer.

---

# 12. Deep publication states

`dispatch_status`:

```text
pending
audited
blocked
```

Legal transitions:

```text
ABSENT  → pending
ABSENT  → blocked        (erratum, see 12.1)
pending → audited
pending → blocked
```

Illegal:

```text
audited → pending
audited → blocked
blocked → pending
blocked → audited
```

First terminal wins.

## 12.1 Erratum: ABSENT → blocked

Sections 12, 26 and the A9/A10 controls were mutually inconsistent. Section 26 requires the
child to exist with an exact lineage *before* a pending candidate can be attached, while A9/A10
require a missing child or a wrong lineage to become a durable blocked terminal. A failure
before attach cannot produce `pending → blocked`, so under the original wording those two cases
could never be recorded at all.

The transition is therefore extended by exactly one edge:

```text
ABSENT → blocked
```

It is permitted only when a deterministic authority or integrity validation in
`attach_pending` fails, so that no legal pending candidate could be established at all.
The typical cases are:

```text
child_missing
lineage_mismatch
deep_terminal_integrity_failure
```

This repairs the contradiction; it does not widen Deep-4A's authority. A malformed recorded
`deep_publication` is still not recreated or repaired (section 13): the block declines and
fails closed with `publication_integrity_failure`.

---

# 13. Absent vs malformed

As in Deep-1/3:

```text
key absent
!=
key present but null/malformed
```

If `deep_publication` is present but malformed:

```text
do not treat it as absent
do not recreate it
do not silently repair it
```

Explicit service access fails closed.

---

# 14. Trigger extension

Deep-4A reuses the existing `DeepTriggerRunner`.

No second background worker.

Runner scan order becomes:

```text
ARM
→ PENDING
→ PUBLICATION
```

This allows one scan to execute:

```text
Standard
→ Deep handoff
→ Deep execution
→ Deep parent finalize
→ Deep-4A audit
```

when each stage finishes within that scan.

---

# 15. Trigger kind

`DeepTriggerItem.kind` extends to:

```text
arm
pending
publication
```

No new queue table.

No scheduler ledger.

No durable trigger cursor.

---

# 16. PUBLICATION discovery — absent candidate

A parent is coarse-discovered when:

```text
chat_turn.status == completed

deep_terminal:
  schema_version == standard-deep-terminal-v1
  state == ESCALATE_DEEP
  dispatch_status == completed

deep_publication key ABSENT
```

Discovery does not validate:

```text
child digest
handoff
ResearchState
projection
synthesis
```

Those belong below.

---

# 17. PUBLICATION discovery — pending recovery

If `deep_publication` is already present and is exactly:

```text
schema_version == deep-publication-v1
dispatch_status == pending
```

it must be rediscovered even if another source component has subsequently become invalid.

Reason:

```text
pending
→ corruption/tamper
```

must reach the service so it can become durable `blocked`.

---

# 18. Malformed publication terminal

If `deep_publication` is:

```text
null
string
wrong schema
audited
blocked
```

it is not returned as new publication work by discovery.

Recorded terminal integrity is handled by service reads.

---

# 19. Publication batch

v1:

```text
PUBLICATION_BATCH = 16
```

Runner concurrency remains:

```text
1
```

No fairness guarantee is added beyond the existing trigger contract.

---

# 20. Runner callback

Add:

```text
publish(parent_turn_id, thread_id)
```

Runner calls it positionally.

Production composition adapts keyword-only service methods:

```python
publish=lambda parent, thread: publication.process(
    parent_turn_id=parent,
    thread_id=thread,
)
```

---

# 21. Wake semantics unchanged

`wake()` remains:

```text
Event.set()
return
```

Deep-4A must never enter the chat request thread.

---

# 22. Deep-4A crash recovery

Supported windows:

```text
A. Deep-3 completed / deep_publication absent
   → startup/periodic discovery recreates work

B. deep_publication pending / process crash
   → pending rediscovered

C. synthesis/audit computed / before transaction commit
   → recomputed deterministically

D. audited transaction committed / callback result lost
   → later read returns existing audited terminal

E. blocked commit / result lost
   → later read returns existing blocked terminal
```

---

# 23. DeepPublicationService

New:

```text
src/application/deep_publication.py
```

Suggested outcome:

```python
@dataclass(frozen=True)
class DeepPublicationOutcome:
    status: Literal[
        "not_requested",
        "audited",
        "blocked",
    ]
    parent_turn_id: str
    child_run_id: str
    reason: str
    result: dict | None
```

There is no `approved` status in Deep-4A.

---

# 24. process() state machine

```text
read parent
↓
read deep_publication

absent:
    validate Deep parent terminal
    atomically attach pending

recorded audited/blocked:
    validate recorded terminal
    return first terminal
    0 synthesis

pending:
    validate pending binding

↓
reload child
↓
validate source binding
↓
claim_engine_load(child)
↓
ResearchBriefProjection
↓
unit-safe payload
↓
deterministic synthesis
↓
abstaining Final Answer Auditor
↓
finalize audited
```

Unknown exception:

```text
propagate to trigger
pending remains pending
```

---

# 25. DeepPublicationRepository

New:

```text
src/repositories/deep_publication_repository.py
```

Responsibilities only:

```text
read
attach pending
finalize audited
block
first-terminal-wins
transactional source revalidation
```

No research semantics.

---

# 26. Pending attachment transaction

Use:

```text
BEGIN IMMEDIATE
```

and re-read:

```text
parent
rag_snapshot
deep_terminal
child WebLookupRun
```

Require:

```text
parent.status == completed
parent.thread_id exact

deep_terminal recorded completed
validate_recorded_terminal(...) == valid

child_run_id exact
child exists
owner/thread lineage exact
child is terminal
```

Then write `deep_publication=pending`.

---

# 27. Pending shape

```text
{
  "schema_version": "deep-publication-v1",
  "dispatch_status": "pending",

  "owner": {
    "thread_id": "...",
    "turn_id": "...",
    "child_run_id": "..."
  },

  "source": {
    "deep_terminal_sha256": "...",
    "child_terminal_sha256": "...",
    "source_run_sha256": "..."
  },

  "publication_authority": false
}
```

No result while pending.

---

# 28. Deep terminal digest

`deep_terminal_sha256`:

```text
SHA-256(
  canonical JSON of the entire recorded deep_terminal
)
```

Canonical JSON:

```text
sort_keys=True
ensure_ascii=False
separators=(",", ":")
UTF-8
```

---

# 29. Source-run digest

`source_run_sha256` binds the durable Deep child used for audit.

Projection includes:

```text
id
owner_thread_id
parent_run_id
query
status
provider_status
stop_reason
answer_confidence
completed_at
selected_sources
rejected_sources
research_context
```

The projection excludes transient in-memory values.

---

# 30. Source-run digest purpose

It closes:

```text
validate child
→ child DB contents change
→ audit/finalize
```

TOCTOU.

At audited finalization transaction:

```text
current source_run_sha256
must equal pending source_run_sha256
```

Otherwise:

```text
blocked / source_run_changed
```

---

# 31. ResearchState digest

After successful `claim_engine_load()`:

```text
research_state_sha256 =
SHA-256(canonical JSON(state.to_dict()))
```

This digest is placed only in the final audited result.

It is not a second ResearchState.

---

# 32. Multi-unit blocker — frozen fix

Current bug:

```text
ResearchEvidence ev1
  unit u1
  unit u2

collect_evidence_payloads()
→ two EvidencePayload(evidence_id="ev1")

assembler:
  {payload.evidence_id: payload}

→ one unit silently overwritten
```

Deep-4A must fix this before activation.

---

# 33. Unit-safe evidence model

Add:

```python
@dataclass(frozen=True)
class EvidencePayloadUnit:
    unit_id: str
    source: str = ""
    modality: str = "unknown"
    provenance: str = ""
    content: str = ""
    observation: str = ""
    page: int | None = None
    region: str = ""
```

Extend `EvidencePayload` with:

```python
units: tuple[EvidencePayloadUnit, ...] = ()
```

Existing singular fields may remain for backwards-compatible construction/tests.

---

# 34. One evidence → one payload

`collect_evidence_payloads(state)` must return:

```text
exactly one EvidencePayload
per ResearchEvidence.evidence_id
```

All `EvidenceUnit`s remain inside:

```text
payload.units
```

No duplicate evidence IDs.

---

# 35. Unit ordering

Units preserve the authoritative order from:

```text
ResearchEvidence.units
```

No sorting by content/source.

This makes regeneration deterministic.

---

# 36. Payload text

For unit-backed payloads:

```text
text()
```

must include every non-empty unit:

```text
observation if present
else content
```

in deterministic unit order.

No unit may disappear because another unit shares its evidence ID.

---

# 37. Mixed modalities

If an evidence object contains:

```text
text + visual
multiple visual units
multiple pages
```

the payload remains one evidence-level object.

It must not collapse to one arbitrary singular modality/page/region.

Citation/validation code must inspect all units.

---

# 38. Visual locator validation

For every visual unit referenced by an evidence payload:

```text
page != None
region != ""
```

must be preserved in the generated citation label/metadata.

A multi-visual evidence citation must preserve every relevant:

```text
p.N
region
```

not just the final unit.

---

# 39. Legacy single-unit compatibility

Existing:

```python
EvidencePayload(
    "e1",
    content="...",
    page=...,
)
```

must continue to behave as one implicit unit.

This avoids rewriting all §148/§149 consumers solely for constructor compatibility.

---

# 40. Multi-unit mutation gate

Mandatory negative control:

```text
one evidence
  u1 = text "A"
  u2 = text "B"

projection authorizes evidence id ev1

→ payload map contains one ev1
→ payload text contains A and B
```

Mutation:

```text
restore old per-unit duplicate EvidencePayload projection
→ test FAIL
```

Also:

```text
one evidence
  chart p.2 region r1
  chart p.5 region r2

→ citation retains both locators
```

---

# 41. ResearchBrief

Deep-4A uses exactly:

```text
build_research_brief_projection(state)
```

No Deep-specific projection.

Projection is hashed from:

```text
projection.to_dict()
```

using canonical JSON SHA-256.

---

# 42. Synthesis writer

Deep-4A production uses:

```text
extractive_writer
```

only.

No injected LLM writer.

Thus Deep-4A has:

```text
0 model calls
0 network calls
0 reads
```

after the Deep child is terminal.

---

# 43. Why deterministic writer

Deep-4A is establishing:

```text
artifact plumbing
authority binding
mechanical correctness
crash recovery
audit boundary
```

not answer prose quality.

A model writer belongs only in a later qualified publication contract.

---

# 44. Synthesis mechanical rejection

A legitimate ResearchState may still be impossible to synthesize safely:

```text
claim has no authorised evidence
visual evidence lacks locator
limitation/stance contract fails
```

This is not durable-state corruption.

Therefore:

```text
SynthesisContractViolation
```

does **not** map to `deep_publication=blocked`.

It maps to terminal:

```text
audited-but-not-approved
candidate_status = mechanically_rejected
```

with bounded issue code.

---

# 45. Integrity failure vs candidate rejection

`blocked` is reserved for authority/integrity failures:

```text
parent unavailable
Deep terminal invalid
child missing
lineage mismatch
source run changed
claim engine malformed/unavailable
pending publication integrity failure
```

Research insufficiency is not integrity failure.

---

# 46. Final Answer Auditor

When synthesis succeeds:

```python
audit_final_answer(
    draft=draft,
    projection=projection,
    payloads=payloads,
    judge=None,
    repairer=None,
)
```

No caller may override these production arguments in Deep-4A.

---

# 47. Normal Deep-4A semantic result

Because no qualified judge exists, a mechanically valid candidate normally reaches:

```text
audit_verdict = fail
approval_status = audited-but-not-approved
question_coverage = unverified
evidence_grounding = unverified
judge_authority = none
publication_authority = false
```

This is expected success for Deep-4A.

---

# 48. Audited is not approved

Deep-4A status:

```text
dispatch_status = audited
```

means:

> the publication candidate reached an honest audit terminal.

It does not mean:

```text
audit verdict pass
answer safe to publish
semantic support verified
```

---

# 49. Audited result schema

Result schema:

```text
deep-audit-artifact-v1
```

Exact bounded fields:

```text
schema_version
child_run_id
child_status

deep_terminal_sha256
child_terminal_sha256
source_run_sha256
research_state_sha256

projection_sha256
draft_sha256
audit_sha256

candidate_status
audit_verdict
approval_status
question_coverage
evidence_grounding
issue_codes

judge_authority
publication_authority
audited_at
```

---

# 50. Candidate status

Allowed:

```text
assembled
mechanically_rejected
```

`assembled` means a `SynthesisDraft` was produced.

`mechanically_rejected` means projection/data were valid enough to audit but synthesis contract rejected publication construction.

Neither implies approval.

---

# 51. No raw artifact in parent

`deep_publication.result` must not include:

```text
ResearchState
ResearchBrief body
EvidencePayload contents
EvidenceUnit contents
SynthesisDraft text
raw citations
page bodies
model output
full AuditIssue reasons
exception text
```

Only bounded hashes/status/codes.

---

# 52. Draft digest

If a draft exists:

```text
draft_sha256 =
SHA-256(canonical JSON(draft.to_dict()))
```

If synthesis is mechanically rejected:

```text
draft_sha256 = ""
```

No fake digest.

---

# 53. Audit digest

Define a bounded audit projection:

```text
verdict
approval_status
question_coverage
evidence_grounding
issue_codes
unanswered_aspects
contradiction_gap count
citation_support_gap count
repair_used
```

`audit_sha256` is SHA-256 of that canonical projection.

Raw exception/error strings do not enter the parent.

---

# 54. Issue codes

Store only bounded issue types, deduplicated in deterministic order.

Examples:

```text
semantic_support_unverified
question_coverage_incomplete
evidence_grounding_incomplete
critical_question_unanswered
visual_locator_missing
assertion_without_evidence_ref
```

No unbounded `reason` text.

---

# 55. Audited finalization transaction

Use:

```text
BEGIN IMMEDIATE
```

Re-read:

```text
parent
deep_terminal
deep_publication
child run
```

Before `pending→audited`, require:

```text
parent still completed

deep_publication still pending
owner exact

deep_terminal still valid completed
deep_terminal_sha256 unchanged

child terminal projection unchanged
child_terminal_sha256 unchanged

source_run_sha256 unchanged
```

Only then commit audited result.

---

# 56. First-terminal-wins

Inside transaction:

```text
if dispatch_status == audited or blocked:
    return existing
```

This check occurs before positive source validation.

A settled publication audit is never reinterpreted because the child is later corrupted.

---

# 57. Block transition

`pending→blocked` must not require the broken component to validate.

As with Deep-3:

```text
the corruption causing the block
must not prevent the block being persisted
```

Minimal transaction authority:

```text
real parent
correct thread
parent completed
deep_publication schema
pending
publication owner binding
```

---

# 58. Bounded block reasons

At least:

```text
parent_unavailable
publication_integrity_failure
deep_terminal_integrity_failure
child_missing
lineage_mismatch
source_run_changed
claim_engine_unusable
```

Unknown exception text never becomes a durable reason.

---

# 59. Unknown exceptions

Unexpected:

```text
DB transient error
programming error
unexpected runtime error
```

must:

```text
propagate to DeepTriggerRunner
leave deep_publication pending
```

Runner logs and future scan retries.

---

# 60. Recorded audited terminal validation

A recorded `audited` terminal is not trusted merely because it exists.

Require:

```text
schema exact
owner exact
publication_authority=false

result exact key set
result.schema == deep-audit-artifact-v1

all required SHA fields:
  "" only where contract explicitly permits draft_sha256
  otherwise 64-char lowercase hex

judge_authority == none
publication_authority == false

approval_status == audited-but-not-approved
```

No child read is required for ordinary first-terminal replay.

---

# 61. Recorded blocked terminal

Require only:

```text
bounded reason
result absent/None
publication_authority=false
```

Do not require the Deep source/handoff/child to still validate.

---

# 62. Assistant answer immutability

Deep-4A must prove byte-identical:

```text
assistant_message
```

before/after:

```text
pending attach
audit
audited commit
blocked commit
crash recovery
```

No background answer replacement.

---

# 63. Other parent immutability

Must also remain unchanged:

```text
status
user_message
role
mode
model
route_snapshot
lookup_terminal
standard_continuation
deep_terminal
pedagogy_snapshot
conversation_instruction
```

Only:

```text
rag_snapshot.deep_publication
```

may change.

---

# 64. Learning immutability

Deep-4A may not mutate:

```text
chat_threads.learning_state
durable learner adjudication
mastery
review schedule
pedagogy phase
```

---

# 65. Research memory isolation

Deep-4A must not call:

```text
ResearchMemoryService.publish()
```

Research memory remains:

```text
explicit opt-in
historical lead only
unresolved
```

and has no publication authority.

---

# 66. Answer Claim Binder boundary

Existing:

```text
answer_claim_binder
answer_consistency
research_binding_rows
```

are **not activated by Deep-4A**.

They are reserved as a mechanical publication gate for Deep-4B.

Deep-4A must not claim they solve semantic approval.

---

# 67. Deep-4B gate

Deep-4B cannot begin automatic publication until a semantic judge is formally qualified.

Qualification must freeze:

```text
judge identity
provider/model/version
holdout identity
qualification artifact digest
qualification result
same/different answer-model family
authority scope
```

A model name in config is not qualification.

---

# 68. Deep-4B future minimum conjunction

Future publication approval must require at least:

```text
ResearchBrief/Synthesis mechanical PASS

AND

qualified Final Answer Auditor semantic PASS

AND

full-publication Evidence Gate shape

AND

Answer Claim Binder fully bound

AND

Answer Consistency PASS
```

Deep-4A does not implement this conjunction.

---

# 69. No direct assistant overwrite in Deep-4B assumption

Deep-4A freezes one architectural constraint for later:

```text
background Deep result
must not silently overwrite assistant_message
```

Reason:

```text
frontend may still display original safe answer
client history may still contain original safe answer
pedagogy/learning truth was evaluated against original safe answer
```

Future cutover must use an explicit answer revision contract.

---

# 70. Deep-4A allowed files

Implementation may modify:

```text
NEW src/application/deep_publication.py
NEW src/repositories/deep_publication_repository.py

MOD src/repositories/deep_trigger_repository.py
MOD src/application/deep_trigger.py
MOD src/application/runtime_repository.py

MOD src/web/research/synthesis_assembler.py

NEW tests/test_deep_publication.py
NEW tests/test_deep_publication_trigger_integration.py

MOD tests/test_deep_trigger.py
MOD tests/test_synthesis_assembler.py

docs/DEEP_4A_CONTRACT.md
docs/PROJECT_STATUS.md
```

No DB migration is expected.

---

# 71. Forbidden surface

Deep-4A must not modify:

```text
active_research_runtime.py
deep_execution.py
deep_runtime.py
deep_seed.py
deep_handoff.py
Deep-3 terminal semantics

ResearchStopGate
Evidence Gain
gap planner
ResearchRuntimeCursor

research_brief_projection.py semantics
final_answer_auditor.py semantic policy

answer_claim_binder.py
answer_consistency.py

research_memory_service.py
persistent_memory.py

chat_service.py
deep_chat_service.py
assistant response streaming

pedagogy
learning state

frontend
DB schema/migrations
```

If implementation requires one of these:

```text
STOP
contract assumption must be re-audited
```

---

# 72. Core negative controls

At minimum:

```text
A1  completed Deep + no deep_publication
    → PUBLICATION discovered

A2  deep_terminal blocked
    → no new publication discovery

A3  publication audited
    → not rediscovered

A4  publication blocked
    → not rediscovered

A5  publication pending
    → rediscovered after restart

A6  malformed publication key
    → not treated as absent

A7  PENDING Deep finalized during runner scan
    → same scan PUBLICATION callback runs

A8  pending publication + corrupt deep_terminal
    → still discovered
    → service durable-blocks it

A9  child missing
    → durable blocked

A10 child lineage mismatch
    → durable blocked

A11 source run changes after pending attach
    → durable blocked source_run_changed

A12 claim_engine_load unavailable/invalid
    → durable blocked

A13 honest empty/failed research state
    → honest audited-not-approved
    → not integrity blocked solely for lack of support
```

---

# 73. Multi-unit negative controls

Mandatory:

```text
M1 one evidence, two text units
   → one EvidencePayload
   → both unit contents preserved

M2 one evidence, text + chart
   → one EvidencePayload
   → neither modality lost

M3 one evidence, two charts on different pages
   → both page/region locators preserved

M4 two evidence ids
   → remain two payloads

M5 old single-unit EvidencePayload constructor
   → behavior remains compatible

M6 payload map by evidence_id
   → no unit collision
```

---

# 74. Audit negative controls

```text
AU1 production Deep-4A makes 0 model calls

AU2 production Deep-4A makes 0 network calls

AU3 mechanically valid draft
    → abstaining semantic audit
    → audited-but-not-approved

AU4 caller cannot inject judge through production composition

AU5 mechanical synthesis rejection
    → audited mechanically_rejected
    → publication_authority=false

AU6 audit result cannot write raw reasons/bodies into parent

AU7 ResearchState digest unchanged after projection/synthesis/audit
```

---

# 75. Transaction/crash controls

```text
C1 crash before pending attach
   → absent candidate rediscovered

C2 crash after pending attach
   → pending rediscovered

C3 crash after audit compute before commit
   → deterministic recompute

C4 audited commit then response lost
   → existing audited terminal returned

C5 two processes attach concurrently
   → one durable pending identity

C6 two auditors finalize concurrently
   → first terminal wins

C7 audited vs blocked race
   → first committed terminal wins

C8 source mutated after service validation but before commit
   → transaction detects digest mismatch
```

---

# 76. Parent isolation controls

```text
I1 assistant_message byte-identical

I2 pedagogy_snapshot byte-identical

I3 learning_state byte-identical

I4 deep_terminal byte-identical

I5 lookup_terminal byte-identical

I6 standard_continuation byte-identical

I7 ResearchMemory row count unchanged
```

---

# 77. Mutation requirements

Critical tests must be mutation-sensitive.

At minimum:

```text
remove PUBLICATION periodic discovery
→ restart recovery test FAIL

remove third runner phase
→ same-scan Deep→audit test FAIL

restore old duplicate EvidencePayload-per-unit behavior
→ multi-unit test FAIL

drop one visual unit locator
→ multi-visual test FAIL

allow semantic judge injection
→ production no-judge test FAIL

set publication_authority=true
→ authority test FAIL

remove source-run digest recheck
→ TOCTOU test FAIL

move first-terminal check after source validation
→ settled-terminal corruption test FAIL

allow assistant_message write
→ immutability test FAIL
```

Passing tests without mutation sensitivity are not sufficient authority.

---

# 78. Review gates

```text
G4A-1   same DeepTriggerRunner reused
G4A-2   no queue table
G4A-3   PUBLICATION durable recovery
G4A-4   absent != malformed
G4A-5   pending survives restart
G4A-6   same-scan Deep→publication candidate
G4A-7   child lineage bound
G4A-8   Deep terminal digest bound
G4A-9   source-run digest bound
G4A-10  transactional TOCTOU recheck

G4A-11  existing claim_engine_load reused
G4A-12  validated active ResearchState required
G4A-13  ResearchState immutable
G4A-14  existing ResearchBrief projection reused

G4A-15  one evidence produces one payload
G4A-16  all EvidenceUnits preserved
G4A-17  mixed modality preserved
G4A-18  all visual locators preserved
G4A-19  single-unit compatibility preserved

G4A-20  deterministic extractive writer only
G4A-21  0 model calls
G4A-22  0 network calls
G4A-23  synthesis mechanical failure fails closed to non-approval
G4A-24  existing Final Answer Auditor reused

G4A-25  semantic judge authority NONE
G4A-26  abstaining judge used
G4A-27  approval_status not approved
G4A-28  publication_authority always false
G4A-29  no Answer Claim Binder activation
G4A-30  no ResearchMemory publication

G4A-31  parent result bounded/hash-only
G4A-32  no raw evidence copied
G4A-33  first terminal wins
G4A-34  deterministic integrity→blocked
G4A-35  honest research insufficiency != integrity blocked
G4A-36  unknown exception leaves pending

G4A-37  assistant_message immutable
G4A-38  pedagogy immutable
G4A-39  learning state immutable
G4A-40  Deep-3 terminal immutable

G4A-41  mutation controls pass
G4A-42  focused tests pass
G4A-43  Deep-1/2/3 regressions pass
G4A-44  synthesis/auditor regressions pass
G4A-45  trigger regressions pass
G4A-46  ruff pass
G4A-47  expanded mypy pass
G4A-48  mypy baseline pass
G4A-49  git diff --check pass
G4A-50  file/scope audit pass
G4A-51  exact-head ordinary CI pass
```

---

# 79. Local candidate gate

One candidate gate:

```text
Deep-4A focused
Deep trigger
Deep-1/2/3 regressions
ResearchBrief projection
synthesis assembler
Final Answer Auditor
multi-unit regression
runtime composition

ruff
expanded mypy
mypy baseline
git diff --check
scope audit
```

`mypy baseline` remains mandatory.

---

# 80. Commit discipline

One bounded slice:

```text
PUBLICATION discovery
+ runner third phase
+ publication repository/service
+ multi-unit fix
+ deterministic synthesis/audit
+ production composition
+ tests
```

Then:

```text
one local candidate gate
one implementation commit
one PR
```

Do not split:

```text
trigger
payload
audit
repository
```

into repeated CI cycles.

---

# 81. CI discipline

Deep-4A uses:

```text
ordinary exact-head CI
```

as merge gate.

Deep-4A does **not** run formal final Deep L3 because:

```text
publication_authority=false
assistant answer unchanged
```

---

# 82. Formal Deep L3 boundary

Formal Deep L3 is reserved for the later cutover that first permits:

```text
qualified semantic authority
publication_authority=true
user-visible approved Deep answer revision
```

That belongs to Deep-4B / final publication cutover.

Old L3 evidence never transfers to that activation SHA.

---

# 83. Deep-4A CLOSED definition

Deep-4A CLOSED means:

```text
a completed Deep research child
can automatically and durably reach

ResearchState
→ ResearchBrief
→ unit-safe evidence plane
→ deterministic synthesis
→ fail-closed audit

and persist a reproducible
audited-but-not-approved
publication candidate
```

with:

```text
crash recovery
first-terminal-wins
0 model calls
0 network calls
0 answer mutation
0 learning mutation
publication_authority=false
```

---

# 84. Deep-4A CLOSED does not mean

It does not mean:

```text
Deep answer published
Deep answer shown to user
semantic support qualified
assistant_message replaced
research memory confirmed
release GO
```

---

# 85. Deep-4B entrance condition

Deep-4B may begin only when all are true:

```text
Deep-4A CLOSED
exact-main ordinary CI green

AND

a semantic judge has a separate
formal qualification authority
```

Without that qualification:

```text
Deep-4B publication = NO-GO
```

---

# 86. User-visible cutover boundary

Any future approved Deep answer must be represented as an explicit:

```text
answer revision
```

or equivalent user-visible versioned artifact.

It must not silently mutate the already-delivered safe answer.

The precise revision/UI contract belongs to Deep-4B.

---

# 87. One-sentence model

> **Deep-4A turns completed Deep research into a durable, reproducible, unit-safe and mechanically audited publication candidate, while deliberately refusing to grant semantic or user-visible answer authority until a separately qualified judge and answer-revision cutover exist.**
