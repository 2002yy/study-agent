"""§162 A2: reviewer qualification plumbing. Grants nothing by itself.

Four separate seams, deliberately not foldable into one another::

    ReviewerAdapter      -> ReviewObservation       (facts only)
    check_calibration    -> CalibrationResult       (facts only)
    decide_qualification -> QualificationDecision   (explicit authority act)
    decide_case_label    -> LabelDecision           (explicit authority act)

A passing calibration only marks a reviewer as *eligible for authority review*.
There is no code path from ``calibration_pass`` to a granted judge, and no code
path from a granted judge to an official label, without a second explicit act
by a named authority. ``ReviewObservation`` deliberately has no
``qualified_judge`` field, so the type system withholds that power rather than
checking for it at runtime.

No provider SDK, no network call and no model invocation lives here: adapters
take injected callables, so adding an independent model family later is a
runtime dependency rather than a change to this contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Callable, Mapping, Protocol, Sequence
from uuid import uuid4

from src.evals.release_benchmark_semantic_controls import (
    AXES,
    ConfusionCounts,
    ControlVerdict,
    confusion_from,
    evaluate_clean_answer,
    evaluate_control,
    specificity_gate_passes,
    target_gate_passes,
)

SCHEMA = "release-benchmark-reviewer-qualification-v1"

REVIEWER_KIND_MODEL = "model"
REVIEWER_KIND_MANUAL_HUMAN = "manual_human"
REVIEWER_KINDS = (REVIEWER_KIND_MODEL, REVIEWER_KIND_MANUAL_HUMAN)

QUALIFICATION_GRANTED = "GRANTED"
QUALIFICATION_DENIED = "DENIED"
QUALIFICATION_NOT_EVALUATED = "NOT_EVALUATED"

LABEL_OFFICIAL = "OFFICIAL"
LABEL_REJECTED = "REJECTED"
LABEL_NOT_EVALUATED = "NOT_EVALUATED"

REASON_MISSING_MODEL_FAMILY = "missing_model_family"
REASON_MISSING_ANSWER_MODEL_FAMILY = "missing_answer_model_family"
REASON_SAME_MODEL_FAMILY = "same_model_family"
REASON_UNKNOWN_REVIEWER_KIND = "unknown_reviewer_kind"
REASON_MISSING_BLIND_CASE_ID = "missing_blind_case_id"
REASON_UNAUTHORIZED_CASE_IDENTITY = "unauthorized_case_identity"
REASON_EXPECTED_LABEL_LEAKED = "expected_label_leaked"
REASON_PRIOR_VERDICT_LEAKED = "prior_verdict_leaked"
REASON_PROVENANCE_INCOMPLETE = "provenance_incomplete"
REASON_PROVENANCE_HASH_MISMATCH = "provenance_hash_mismatch"
REASON_REVIEWER_CLAIMED_AUTHORITY = "reviewer_claimed_authority"
REASON_UNKNOWN_OBSERVATION_FIELD = "unknown_observation_field"
REASON_MIXED_REVIEWERS = "mixed_reviewers"
REASON_GRANT_ON_FAILED_CALIBRATION = "grant_on_failed_calibration"
REASON_LABEL_WITHOUT_QUALIFICATION = "label_without_qualification"
REASON_MISSING_AUTHORITY_IDENTITY = "missing_authority_identity"
REASON_MISSING_LABEL = "missing_label"

# Fields a review observation may carry. Anything else is rejected.
_OBSERVATION_FIELDS = frozenset({*AXES, "issues", "dimension_consistent"})

# Names that would hand a reviewer authority it must never hold.
_FORBIDDEN_OBSERVATION_KEYS = frozenset({
    "qualified_judge", "qualified", "judge", "judge_qualified", "granted",
    "authority", "qualification", "approved", "admission", "admitted",
    "formal_semantic_label", "semantic_label", "official_label", "label",
    "release_observation", "release_gate", "score", "verdict",
})

# Names that would leak the answer key or a competing prior judgment.
_EXPECTED_LABEL_KEYS = frozenset({
    "expected", "expected_label", "expected_labels", "expected_axes",
    "gold", "gold_label", "gold_labels", "answer_key", "reference_answer",
    "rubric_answer", "ground_truth",
})
_PRIOR_VERDICT_KEYS = frozenset({
    "prior_verdict", "previous_verdict", "reviewer_verdict", "probe_verdict",
    "deepseek_verdict", "semantic_probe", "prior_judgment",
    "previous_judgment", "legacy_calibration", "semantic_calibration",
})


class ReviewerQualificationViolation(ValueError):
    """A §162 contract rule was broken; the caller must fail closed."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


def canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _require_utc(value: str, reason: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ReviewerQualificationViolation(reason, "timestamp is missing")
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReviewerQualificationViolation(reason, "timestamp is invalid") from exc
    if instant.tzinfo is None or instant.utcoffset() != timezone.utc.utcoffset(instant):
        raise ReviewerQualificationViolation(reason, "timestamp is not UTC")
    return instant


# --------------------------------------------------------------------- inputs


@dataclass(frozen=True)
class ReviewerInput:
    """Exactly what a reviewer may see: frozen references plus a blind payload."""

    answer_bundle_ref: str
    source_bundle_ref: str
    rubric_ref: str
    control_set_ref: str
    input_manifest_hash: str
    blind_case_id: str
    blind_payload: Mapping[str, object]
    rubric_hash: str = ""
    controls_hash: str = ""

    def manifest_fields(self) -> dict[str, str]:
        return {
            "answer_bundle_ref": self.answer_bundle_ref,
            "source_bundle_ref": self.source_bundle_ref,
            "rubric_ref": self.rubric_ref,
            "control_set_ref": self.control_set_ref,
            "blind_case_id": self.blind_case_id,
        }

    def expected_manifest_hash(self) -> str:
        return canonical_hash(self.manifest_fields())

    def resolved_rubric_hash(self) -> str:
        return self.rubric_hash or canonical_hash(self.rubric_ref)

    def resolved_controls_hash(self) -> str:
        return self.controls_hash or canonical_hash(self.control_set_ref)


@dataclass(frozen=True)
class ReviewerIdentity:
    reviewer_kind: str
    provider: str
    model_family: str
    model_id: str
    revision: str

    def to_dict(self) -> dict[str, str]:
        return {
            "reviewer_kind": self.reviewer_kind,
            "provider": self.provider,
            "model_family": self.model_family,
            "model_id": self.model_id,
            "revision": self.revision,
        }


@dataclass(frozen=True)
class ReviewerProvenance:
    """Reviewer-side facts. ``qualification_authority`` records who is expected
    to adjudicate; it confers no authority by itself."""

    identity: ReviewerIdentity
    invocation_id: str
    timestamp: str
    input_manifest_hash: str
    rubric_hash: str
    controls_hash: str
    qualification_authority: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "identity": self.identity.to_dict(),
            "invocation_id": self.invocation_id,
            "timestamp": self.timestamp,
            "input_manifest_hash": self.input_manifest_hash,
            "rubric_hash": self.rubric_hash,
            "controls_hash": self.controls_hash,
            "qualification_authority": self.qualification_authority,
        }


def reviewer_identity_hash(identity: ReviewerIdentity) -> str:
    return canonical_hash(identity.to_dict())


def provenance_hash(provenance: ReviewerProvenance) -> str:
    return canonical_hash(provenance.to_dict())


def _scan_forbidden_keys(value: object, path: str = "") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            lowered = str(key).strip().lower()
            where = f"{path}.{key}" if path else str(key)
            if lowered in _EXPECTED_LABEL_KEYS:
                raise ReviewerQualificationViolation(
                    REASON_EXPECTED_LABEL_LEAKED, where
                )
            if lowered in _PRIOR_VERDICT_KEYS:
                raise ReviewerQualificationViolation(
                    REASON_PRIOR_VERDICT_LEAKED, where
                )
            _scan_forbidden_keys(item, where)
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _scan_forbidden_keys(item, f"{path}[{index}]")


def validate_blind_input(
    reviewer_input: ReviewerInput, *, authorized_case_ids: Sequence[str]
) -> None:
    """Fail closed before any reviewer sees the input."""
    if not reviewer_input.blind_case_id.strip():
        raise ReviewerQualificationViolation(REASON_MISSING_BLIND_CASE_ID)
    if reviewer_input.blind_case_id not in set(authorized_case_ids):
        raise ReviewerQualificationViolation(
            REASON_UNAUTHORIZED_CASE_IDENTITY, reviewer_input.blind_case_id
        )
    if reviewer_input.input_manifest_hash != reviewer_input.expected_manifest_hash():
        raise ReviewerQualificationViolation(REASON_PROVENANCE_HASH_MISMATCH)
    _scan_forbidden_keys(reviewer_input.blind_payload)


def validate_reviewer_independence(
    provenance: ReviewerProvenance, *, answer_model_families: Sequence[str]
) -> None:
    """A different family is necessary but not sufficient; it is still required."""
    if provenance.identity.reviewer_kind not in REVIEWER_KINDS:
        raise ReviewerQualificationViolation(
            REASON_UNKNOWN_REVIEWER_KIND, provenance.identity.reviewer_kind
        )
    family = provenance.identity.model_family.strip().lower()
    if not family:
        raise ReviewerQualificationViolation(REASON_MISSING_MODEL_FAMILY)
    families = {item.strip().lower() for item in answer_model_families if item.strip()}
    if not families:
        raise ReviewerQualificationViolation(REASON_MISSING_ANSWER_MODEL_FAMILY)
    if family in families:
        raise ReviewerQualificationViolation(REASON_SAME_MODEL_FAMILY, family)


def validate_provenance(
    provenance: ReviewerProvenance, *, reviewer_input: ReviewerInput
) -> None:
    if not provenance.invocation_id.strip():
        raise ReviewerQualificationViolation(REASON_PROVENANCE_INCOMPLETE, "invocation_id")
    _require_utc(provenance.timestamp, REASON_PROVENANCE_INCOMPLETE)
    if not provenance.rubric_hash.strip() or not provenance.controls_hash.strip():
        raise ReviewerQualificationViolation(REASON_PROVENANCE_INCOMPLETE, "hashes")
    if provenance.input_manifest_hash != reviewer_input.input_manifest_hash:
        raise ReviewerQualificationViolation(REASON_PROVENANCE_HASH_MISMATCH)
    if provenance.rubric_hash != reviewer_input.resolved_rubric_hash():
        raise ReviewerQualificationViolation(
            REASON_PROVENANCE_HASH_MISMATCH, "rubric"
        )
    if provenance.controls_hash != reviewer_input.resolved_controls_hash():
        raise ReviewerQualificationViolation(
            REASON_PROVENANCE_HASH_MISMATCH, "controls"
        )


# --------------------------------------------------------------- observations


@dataclass(frozen=True)
class ReviewIssue:
    issue_type: str
    reason: str = ""
    evidence_refs: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "issue_type": self.issue_type,
            "reason": self.reason,
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass(frozen=True)
class ReviewObservation:
    """What a reviewer may say. Note the absence of any authority field."""

    blind_case_id: str
    provenance: ReviewerProvenance
    axes: Mapping[str, str]
    issues: tuple[ReviewIssue, ...]
    dimension_consistent: bool

    def judgment(self) -> dict[str, object]:
        return {
            AXES[0]: self.axes[AXES[0]],
            AXES[1]: self.axes[AXES[1]],
            AXES[2]: self.axes[AXES[2]],
            "issues": [issue.to_dict() for issue in self.issues],
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "blind_case_id": self.blind_case_id,
            "provenance": self.provenance.to_dict(),
            "axes": dict(self.axes),
            "issues": [issue.to_dict() for issue in self.issues],
            "dimension_consistent": self.dimension_consistent,
        }


def parse_review_observation(
    payload: Mapping[str, object],
    *,
    provenance: ReviewerProvenance,
    blind_case_id: str,
) -> ReviewObservation:
    """Strictly parse a reviewer response; authority-shaped fields are rejected."""
    if not isinstance(payload, Mapping):
        raise ReviewerQualificationViolation(
            REASON_UNKNOWN_OBSERVATION_FIELD, "observation is not an object"
        )
    for key in payload:
        lowered = str(key).strip().lower()
        if lowered in _FORBIDDEN_OBSERVATION_KEYS:
            raise ReviewerQualificationViolation(
                REASON_REVIEWER_CLAIMED_AUTHORITY, str(key)
            )
        if lowered not in _OBSERVATION_FIELDS:
            raise ReviewerQualificationViolation(
                REASON_UNKNOWN_OBSERVATION_FIELD, str(key)
            )
    axes: dict[str, str] = {}
    for axis in AXES:
        value = payload.get(axis)
        if not isinstance(value, str) or not value.strip():
            raise ReviewerQualificationViolation(
                REASON_UNKNOWN_OBSERVATION_FIELD, axis
            )
        axes[axis] = value
    raw_issues = payload.get("issues", [])
    if not isinstance(raw_issues, (list, tuple)):
        raise ReviewerQualificationViolation(
            REASON_UNKNOWN_OBSERVATION_FIELD, "issues"
        )
    issues = []
    for row in raw_issues:
        if not isinstance(row, Mapping) or not isinstance(row.get("issue_type"), str):
            raise ReviewerQualificationViolation(
                REASON_UNKNOWN_OBSERVATION_FIELD, "issue"
            )
        refs = row.get("evidence_refs", ())
        if not isinstance(refs, (list, tuple)) or any(
            not isinstance(ref, str) for ref in refs
        ):
            raise ReviewerQualificationViolation(
                REASON_UNKNOWN_OBSERVATION_FIELD, "evidence_refs"
            )
        reason = row.get("reason", "")
        if not isinstance(reason, str):
            raise ReviewerQualificationViolation(
                REASON_UNKNOWN_OBSERVATION_FIELD, "reason"
            )
        issues.append(
            ReviewIssue(
                issue_type=str(row["issue_type"]),
                reason=reason,
                evidence_refs=tuple(str(ref) for ref in refs),
            )
        )
    consistent = payload.get("dimension_consistent", True)
    if not isinstance(consistent, bool):
        raise ReviewerQualificationViolation(
            REASON_UNKNOWN_OBSERVATION_FIELD, "dimension_consistent"
        )
    return ReviewObservation(
        blind_case_id=blind_case_id,
        provenance=provenance,
        axes=axes,
        issues=tuple(issues),
        dimension_consistent=consistent,
    )


# ------------------------------------------------------------- calibration


@dataclass(frozen=True)
class ReviewedControl:
    variant: str
    observation: ReviewObservation


@dataclass(frozen=True)
class CalibrationResult:
    """Facts about a reviewer's blind control performance. Not a permission."""

    reviewer_identity_hash: str
    input_manifest_hash: str
    controls: tuple[ControlVerdict, ...]
    confusion: ConfusionCounts
    target_gate_pass: bool
    specificity_gate_pass: bool
    calibration_pass: bool
    clean_answer_correct: int
    clean_answer_total: int

    @property
    def target_detected(self) -> int:
        return self.confusion.true_positive

    @property
    def target_total(self) -> int:
        return self.confusion.target_total

    @property
    def target_missed(self) -> int:
        return self.confusion.false_negative

    @property
    def specificity_correct(self) -> int:
        return self.confusion.true_negative

    @property
    def specificity_total(self) -> int:
        return self.confusion.specificity_total

    @property
    def specificity_violations(self) -> int:
        return self.confusion.false_positive

    @property
    def eligible_for_authority_review(self) -> bool:
        """A passing gate buys eligibility only — never a granted judge."""
        return self.calibration_pass

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA,
            "reviewer_identity_hash": self.reviewer_identity_hash,
            "input_manifest_hash": self.input_manifest_hash,
            "target_detected": self.target_detected,
            "target_total": self.target_total,
            "target_missed": self.target_missed,
            "specificity_correct": self.specificity_correct,
            "specificity_total": self.specificity_total,
            "specificity_violations": self.specificity_violations,
            "confusion": self.confusion.to_dict(),
            "target_gate_pass": self.target_gate_pass,
            "specificity_gate_pass": self.specificity_gate_pass,
            "calibration_pass": self.calibration_pass,
            "clean_answer_correct": self.clean_answer_correct,
            "clean_answer_total": self.clean_answer_total,
            "controls": [row.to_dict() for row in self.controls],
            "qualified_judge": False,
            "formal_semantic_label": False,
            "release_observation": False,
        }

    def artifact_hash(self) -> str:
        return canonical_hash(self.to_dict())


def check_calibration(
    *,
    reviewer_provenance: ReviewerProvenance,
    control_observations: Sequence[ReviewedControl],
    clean_answer_observations: Sequence[ReviewObservation] = (),
) -> CalibrationResult:
    """Pure function: score blind controls into two independent booleans.

    ``calibration_pass`` is never the only surviving information; the confusion
    counts and per-control verdicts are always preserved so a later reviewer
    generation cannot silently redefine the gate.
    """
    expected_identity = reviewer_identity_hash(reviewer_provenance.identity)
    for item in control_observations:
        _require_same_reviewer(item.observation, expected_identity)
    for observation in clean_answer_observations:
        _require_same_reviewer(observation, expected_identity)
    verdicts = tuple(
        evaluate_control(
            item.variant,
            dimension_consistent=item.observation.dimension_consistent,
            judgment=item.observation.judgment(),
        )
        for item in control_observations
    )
    confusion = confusion_from(verdicts)
    target_pass = target_gate_passes(confusion)
    specificity_pass = specificity_gate_passes(confusion)
    clean_correct = sum(
        1
        for observation in clean_answer_observations
        if evaluate_clean_answer(
            dimension_consistent=observation.dimension_consistent,
            judgment=observation.judgment(),
        )
    )
    return CalibrationResult(
        reviewer_identity_hash=expected_identity,
        input_manifest_hash=reviewer_provenance.input_manifest_hash,
        controls=verdicts,
        confusion=confusion,
        target_gate_pass=target_pass,
        specificity_gate_pass=specificity_pass,
        calibration_pass=target_pass and specificity_pass,
        clean_answer_correct=clean_correct,
        clean_answer_total=len(clean_answer_observations),
    )


def _require_same_reviewer(
    observation: ReviewObservation, expected_identity_hash: str
) -> None:
    if reviewer_identity_hash(observation.provenance.identity) != expected_identity_hash:
        raise ReviewerQualificationViolation(REASON_MIXED_REVIEWERS)


# ---------------------------------------------------------------- authorities


@dataclass(frozen=True)
class QualificationDecision:
    """Answer to "may this reviewer take part in label adjudication?"."""

    status: str
    authority_identity: str
    decision_timestamp: str
    reviewer_identity_hash: str
    calibration_artifact_hash: str
    decision_reason: str

    @property
    def qualified_judge(self) -> bool:
        return self.status == QUALIFICATION_GRANTED

    @classmethod
    def not_evaluated(cls) -> QualificationDecision:
        return cls(
            status=QUALIFICATION_NOT_EVALUATED,
            authority_identity="",
            decision_timestamp="",
            reviewer_identity_hash="",
            calibration_artifact_hash="",
            decision_reason="authority_not_consulted",
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "authority_identity": self.authority_identity,
            "decision_timestamp": self.decision_timestamp,
            "reviewer_identity_hash": self.reviewer_identity_hash,
            "calibration_artifact_hash": self.calibration_artifact_hash,
            "decision_reason": self.decision_reason,
            "qualified_judge": self.qualified_judge,
        }

    def artifact_hash(self) -> str:
        return canonical_hash(self.to_dict())


def decide_qualification(
    *,
    authority_identity: str,
    decision_timestamp: str,
    reviewer_provenance: ReviewerProvenance,
    calibration: CalibrationResult,
    granted: bool,
    decision_reason: str,
) -> QualificationDecision:
    """An explicit authority act. A passing calibration alone grants nothing."""
    if not authority_identity.strip():
        raise ReviewerQualificationViolation(REASON_MISSING_AUTHORITY_IDENTITY)
    _require_utc(decision_timestamp, REASON_PROVENANCE_INCOMPLETE)
    if not decision_reason.strip():
        raise ReviewerQualificationViolation(
            REASON_PROVENANCE_INCOMPLETE, "decision_reason"
        )
    expected_identity = reviewer_identity_hash(reviewer_provenance.identity)
    if calibration.reviewer_identity_hash != expected_identity:
        raise ReviewerQualificationViolation(REASON_MIXED_REVIEWERS)
    if granted and not calibration.calibration_pass:
        raise ReviewerQualificationViolation(REASON_GRANT_ON_FAILED_CALIBRATION)
    return QualificationDecision(
        status=QUALIFICATION_GRANTED if granted else QUALIFICATION_DENIED,
        authority_identity=authority_identity,
        decision_timestamp=decision_timestamp,
        reviewer_identity_hash=expected_identity,
        calibration_artifact_hash=calibration.artifact_hash(),
        decision_reason=decision_reason,
    )


@dataclass(frozen=True)
class LabelDecision:
    """Answer to "is this case's semantic label now official?"."""

    status: str
    authority_identity: str
    decision_timestamp: str
    reviewer_identity_hash: str
    qualification_artifact_hash: str
    case_id: str
    label: Mapping[str, object] | None
    decision_reason: str

    @property
    def official_semantic_label(self) -> Mapping[str, object] | None:
        return dict(self.label) if self.status == LABEL_OFFICIAL and self.label else None

    @classmethod
    def not_evaluated(cls) -> LabelDecision:
        return cls(
            status=LABEL_NOT_EVALUATED,
            authority_identity="",
            decision_timestamp="",
            reviewer_identity_hash="",
            qualification_artifact_hash="",
            case_id="",
            label=None,
            decision_reason="authority_not_consulted",
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "authority_identity": self.authority_identity,
            "decision_timestamp": self.decision_timestamp,
            "reviewer_identity_hash": self.reviewer_identity_hash,
            "qualification_artifact_hash": self.qualification_artifact_hash,
            "case_id": self.case_id,
            "label": dict(self.label) if self.label else None,
            "decision_reason": self.decision_reason,
        }


def decide_case_label(
    *,
    authority_identity: str,
    decision_timestamp: str,
    qualification: QualificationDecision,
    case_review: ReviewObservation,
    accepted: bool,
    decision_reason: str,
    label: Mapping[str, object] | None = None,
) -> LabelDecision:
    """A second, independent authority act. A granted judge is not a label."""
    if not authority_identity.strip():
        raise ReviewerQualificationViolation(REASON_MISSING_AUTHORITY_IDENTITY)
    _require_utc(decision_timestamp, REASON_PROVENANCE_INCOMPLETE)
    if not decision_reason.strip():
        raise ReviewerQualificationViolation(
            REASON_PROVENANCE_INCOMPLETE, "decision_reason"
        )
    if qualification.status != QUALIFICATION_GRANTED:
        raise ReviewerQualificationViolation(
            REASON_LABEL_WITHOUT_QUALIFICATION, qualification.status
        )
    if qualification.reviewer_identity_hash != reviewer_identity_hash(
        case_review.provenance.identity
    ):
        raise ReviewerQualificationViolation(REASON_MIXED_REVIEWERS)
    if accepted and not label:
        raise ReviewerQualificationViolation(REASON_MISSING_LABEL)
    return LabelDecision(
        status=LABEL_OFFICIAL if accepted else LABEL_REJECTED,
        authority_identity=authority_identity,
        decision_timestamp=decision_timestamp,
        reviewer_identity_hash=reviewer_identity_hash(case_review.provenance.identity),
        qualification_artifact_hash=qualification.artifact_hash(),
        case_id=case_review.blind_case_id,
        label=dict(label) if accepted and label else None,
        decision_reason=decision_reason,
    )


# ------------------------------------------------------------------ adapters


class ReviewerAdapter(Protocol):
    """Only a protocol: no provider SDK is bound at this layer."""

    reviewer_kind: str

    @property
    def identity(self) -> ReviewerIdentity: ...

    def review(self, reviewer_input: ReviewerInput) -> ReviewObservation: ...


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class _CallableReviewer:
    reviewer_kind = ""

    def __init__(
        self,
        *,
        identity: ReviewerIdentity,
        produce: Callable[[ReviewerInput], Mapping[str, object]],
        invocation_id_factory: Callable[[], str] = lambda: uuid4().hex,
        clock: Callable[[], str] = _utc_now,
        qualification_authority: str = "",
    ) -> None:
        if identity.reviewer_kind != self.reviewer_kind:
            raise ReviewerQualificationViolation(
                REASON_UNKNOWN_REVIEWER_KIND, identity.reviewer_kind
            )
        self._identity = identity
        self._produce = produce
        self._invocation_id_factory = invocation_id_factory
        self._clock = clock
        self._qualification_authority = qualification_authority

    @property
    def identity(self) -> ReviewerIdentity:
        return self._identity

    def review(self, reviewer_input: ReviewerInput) -> ReviewObservation:
        payload = self._produce(reviewer_input)
        provenance = ReviewerProvenance(
            identity=self._identity,
            invocation_id=self._invocation_id_factory(),
            timestamp=self._clock(),
            input_manifest_hash=reviewer_input.input_manifest_hash,
            rubric_hash=reviewer_input.resolved_rubric_hash(),
            controls_hash=reviewer_input.resolved_controls_hash(),
            qualification_authority=self._qualification_authority,
        )
        return parse_review_observation(
            payload, provenance=provenance, blind_case_id=reviewer_input.blind_case_id
        )


class InjectedModelReviewer(_CallableReviewer):
    """Wraps an injected callable. Deliberately contains no provider code."""

    reviewer_kind = REVIEWER_KIND_MODEL


class ManualHumanReviewer(_CallableReviewer):
    """A named human reviewer supplying the same observation shape."""

    reviewer_kind = REVIEWER_KIND_MANUAL_HUMAN


def build_reviewer_input(
    *,
    answer_bundle_ref: str,
    source_bundle_ref: str,
    rubric_ref: str,
    control_set_ref: str,
    blind_case_id: str,
    blind_payload: Mapping[str, object],
    rubric_hash: str = "",
    controls_hash: str = "",
) -> ReviewerInput:
    """Assemble an input and bind its manifest hash."""
    seed = ReviewerInput(
        answer_bundle_ref=answer_bundle_ref,
        source_bundle_ref=source_bundle_ref,
        rubric_ref=rubric_ref,
        control_set_ref=control_set_ref,
        input_manifest_hash="",
        blind_case_id=blind_case_id,
        blind_payload=blind_payload,
        rubric_hash=rubric_hash,
        controls_hash=controls_hash,
    )
    return ReviewerInput(
        answer_bundle_ref=answer_bundle_ref,
        source_bundle_ref=source_bundle_ref,
        rubric_ref=rubric_ref,
        control_set_ref=control_set_ref,
        input_manifest_hash=seed.expected_manifest_hash(),
        blind_case_id=blind_case_id,
        blind_payload=blind_payload,
        rubric_hash=rubric_hash,
        controls_hash=controls_hash,
    )


def make_identity(
    *,
    reviewer_kind: str,
    provider: str,
    model_family: str,
    model_id: str,
    revision: str,
) -> ReviewerIdentity:
    if reviewer_kind not in REVIEWER_KINDS:
        raise ReviewerQualificationViolation(
            REASON_UNKNOWN_REVIEWER_KIND, reviewer_kind
        )
    return ReviewerIdentity(
        reviewer_kind=reviewer_kind,
        provider=provider,
        model_family=model_family,
        model_id=model_id,
        revision=revision,
    )
