"""§162 A2: reviewer qualification plumbing must never self-grant authority."""

from __future__ import annotations

import pytest

from src.evals.release_benchmark_reviewer_qualification import (
    LABEL_NOT_EVALUATED,
    LABEL_OFFICIAL,
    QUALIFICATION_DENIED,
    QUALIFICATION_GRANTED,
    QUALIFICATION_NOT_EVALUATED,
    REASON_EXPECTED_LABEL_LEAKED,
    REASON_GRANT_ON_FAILED_CALIBRATION,
    REASON_LABEL_WITHOUT_QUALIFICATION,
    REASON_MISSING_ANSWER_MODEL_FAMILY,
    REASON_MISSING_BLIND_CASE_ID,
    REASON_MISSING_MODEL_FAMILY,
    REASON_MIXED_REVIEWERS,
    REASON_PRIOR_VERDICT_LEAKED,
    REASON_PROVENANCE_HASH_MISMATCH,
    REASON_REVIEWER_CLAIMED_AUTHORITY,
    REASON_SAME_MODEL_FAMILY,
    REASON_UNAUTHORIZED_CASE_IDENTITY,
    CalibrationResult,
    InjectedModelReviewer,
    LabelDecision,
    ManualHumanReviewer,
    QualificationDecision,
    ReviewedControl,
    ReviewerIdentity,
    ReviewObservation,
    ReviewerProvenance,
    ReviewerQualificationViolation,
    build_reviewer_input,
    check_calibration,
    decide_case_label,
    decide_qualification,
    make_identity,
    parse_review_observation,
    reviewer_identity_hash,
    validate_blind_input,
    validate_provenance,
    validate_reviewer_independence,
)

INSTANT = "2026-10-01T00:00:00Z"
LATER = "2026-10-01T00:05:00Z"
AUTHORITY = "release-benchmark-label-authority-1"

_CONTROL_AXES = {
    "wrong_citation": ("covered", "supported", "gap"),
    "missing_aspect": ("partial", "supported", "supported"),
    "unsupported_claim": ("covered", "gap", "gap"),
}
_CONTROL_ISSUE = {
    "wrong_citation": "wrong_citation",
    "missing_aspect": "coverage_gap",
    "unsupported_claim": "unsupported_claim",
}
_VARIANTS = ("wrong_citation", "missing_aspect", "unsupported_claim")


def _identity(**overrides):
    base = {
        "reviewer_kind": "model",
        "provider": "independent-provider",
        "model_family": "independent-family",
        "model_id": "independent-model",
        "revision": "2026-09",
    }
    base.update(overrides)
    return make_identity(**base)


def _input(*, blind_case_id: str = "blind-case-1", payload=None, **overrides):
    return build_reviewer_input(
        answer_bundle_ref="docs/research_quality/RELEASE_BENCHMARK_REMOTE_OBSERVATION_2026-09-29/answer_bundle.json",
        source_bundle_ref="tests/fixtures/release_benchmark/sources",
        rubric_ref="tests/fixtures/release_benchmark/gold_v1.json",
        control_set_ref="release-benchmark-semantic-calibration-v1",
        blind_case_id=blind_case_id,
        blind_payload=payload if payload is not None else {"question": "q", "answer": "a"},
        **overrides,
    )


def _observation(
    variant: str | None,
    *,
    provenance: ReviewerProvenance,
    blind_case_id: str = "blind-case-1",
    issues: list[dict[str, object]] | None = None,
    axes: dict[str, str] | None = None,
) -> ReviewObservation:
    if variant is None:
        axes = axes or {"question_coverage": "covered", "evidence_grounding": "supported", "citation_support": "supported"}
        issue_rows = issues or []
    else:
        axes = axes or dict(zip(("question_coverage", "evidence_grounding", "citation_support"), _CONTROL_AXES[variant], strict=True))
        issue_rows = issues if issues is not None else [
            {"issue_type": _CONTROL_ISSUE[variant], "reason": "control", "evidence_refs": []}
        ]
    return parse_review_observation(
        {**axes, "issues": issue_rows, "dimension_consistent": True},
        provenance=provenance,
        blind_case_id=blind_case_id,
    )


def _reviewer(*, identity=None, response=None, invoke=None):
    identity = identity or _identity()
    calls = {"n": 0}

    def default_produce(reviewer_input):
        calls["n"] += 1
        return response if response is not None else {
            "question_coverage": "covered",
            "evidence_grounding": "supported",
            "citation_support": "supported",
            "issues": [],
            "dimension_consistent": True,
        }

    reviewer = InjectedModelReviewer(
        identity=identity,
        produce=invoke or default_produce,
        invocation_id_factory=lambda: "invocation-1",
        clock=lambda: INSTANT,
    )
    return reviewer, calls


def _provenance(*, identity: ReviewerIdentity | None = None, reviewer_input=None) -> ReviewerProvenance:
    reviewer, _ = _reviewer(identity=identity)
    observation = reviewer.review(reviewer_input or _input())
    return observation.provenance


def _perfect_controls(*, provenance, overflag_variants=(), missed_variants=()):
    rows = []
    for variant in _VARIANTS:
        if variant in missed_variants:
            axes = {"question_coverage": "covered", "evidence_grounding": "supported", "citation_support": "supported"}
            rows.append(ReviewedControl(variant, _observation(variant, provenance=provenance, axes=axes, issues=[])))
            continue
        issues = None
        if variant in overflag_variants:
            issues = [
                {"issue_type": _CONTROL_ISSUE[variant], "reason": "control", "evidence_refs": []},
                {"issue_type": "unsupported_claim" if variant != "unsupported_claim" else "wrong_citation",
                 "reason": "extra", "evidence_refs": []},
            ]
        rows.append(ReviewedControl(variant, _observation(variant, provenance=provenance, issues=issues)))
    return rows


def _calibration(*, overflag=0, missed=0):
    provenance = _provenance()
    controls = _perfect_controls(
        provenance=provenance,
        overflag_variants=tuple(_VARIANTS[:overflag]),
        missed_variants=tuple(_VARIANTS[len(_VARIANTS) - missed:] if missed else ()),
    )
    return provenance, check_calibration(
        reviewer_provenance=provenance,
        control_observations=controls,
        clean_answer_observations=(_observation(None, provenance=provenance),),
    )


# ------------------------------------------------------- 1-4: the two gates

def test_one_perfect_calibration_grants_nothing():
    """6/6 + 6/6 passes the gate but must not produce a judge by itself."""
    provenance, calibration = _calibration()
    assert calibration.target_detected == 3
    assert calibration.target_total == 3
    assert calibration.specificity_correct == 3
    assert calibration.specificity_total == 3
    assert calibration.target_gate_pass is True
    assert calibration.specificity_gate_pass is True
    assert calibration.calibration_pass is True
    assert calibration.eligible_for_authority_review is True
    assert calibration.to_dict()["qualified_judge"] is False
    assert calibration.to_dict()["formal_semantic_label"] is False
    assert calibration.to_dict()["release_observation"] is False
    # Authority was never consulted.
    assert QualificationDecision.not_evaluated().status == QUALIFICATION_NOT_EVALUATED
    assert QualificationDecision.not_evaluated().qualified_judge is False


def test_target_detection_without_specificity_fails():
    """6/6 detection with an over-flagging control is still a failure."""
    _, calibration = _calibration(overflag=1)
    assert calibration.target_gate_pass is True
    assert calibration.specificity_gate_pass is False
    assert calibration.calibration_pass is False
    assert calibration.specificity_violations == 1


def test_specificity_without_target_detection_fails():
    _, calibration = _calibration(missed=1)
    assert calibration.target_gate_pass is False
    assert calibration.specificity_gate_pass is False
    assert calibration.calibration_pass is False
    assert calibration.target_missed == 1


def test_averaged_scores_can_never_be_read_as_a_pass():
    """A nearly-perfect reviewer must still fail; no blended accuracy exists."""
    _, calibration = _calibration(overflag=1)
    payload = calibration.to_dict()
    assert payload["calibration_pass"] is False
    confusion = payload["confusion"]
    assert isinstance(confusion, dict)
    assert set(confusion) == {
        "true_positive", "false_negative", "true_negative", "false_positive"
    }
    assert not any(
        isinstance(value, float) for value in payload.values()
    ), "calibration must expose counts and booleans, never a blended score"


# --------------------------------------------------- 5-6: independence/provenance

def test_same_model_family_as_the_answer_model_fails_closed():
    provenance = _provenance(identity=_identity(model_family="deepseek"))
    with pytest.raises(ReviewerQualificationViolation) as exc:
        validate_reviewer_independence(
            provenance, answer_model_families=("deepseek",)
        )
    assert exc.value.reason == REASON_SAME_MODEL_FAMILY


def test_missing_families_fail_closed():
    with pytest.raises(ReviewerQualificationViolation) as exc:
        validate_reviewer_independence(
            _provenance(identity=_identity(model_family="")),
            answer_model_families=("deepseek",),
        )
    assert exc.value.reason == REASON_MISSING_MODEL_FAMILY

    with pytest.raises(ReviewerQualificationViolation) as exc:
        validate_reviewer_independence(_provenance(), answer_model_families=())
    assert exc.value.reason == REASON_MISSING_ANSWER_MODEL_FAMILY


def test_provenance_hash_mismatch_fails_closed():
    provenance = _provenance()
    tampered = _input(blind_case_id="blind-case-2")
    with pytest.raises(ReviewerQualificationViolation) as exc:
        validate_provenance(provenance, reviewer_input=tampered)
    assert exc.value.reason == REASON_PROVENANCE_HASH_MISMATCH


def test_missing_blind_case_id_and_unknown_case_fail_closed():
    with pytest.raises(ReviewerQualificationViolation) as exc:
        validate_blind_input(_input(blind_case_id="  "), authorized_case_ids=("x",))
    assert exc.value.reason == REASON_MISSING_BLIND_CASE_ID

    with pytest.raises(ReviewerQualificationViolation) as exc:
        validate_blind_input(
            _input(blind_case_id="unlisted-case"), authorized_case_ids=("blind-case-1",)
        )
    assert exc.value.reason == REASON_UNAUTHORIZED_CASE_IDENTITY


# ------------------------------------------------------------- 7-8: leakage

def test_expected_label_leakage_is_rejected():
    reviewer_input = _input(
        payload={"question": "q", "nested": {"expected_label": "covered"}}
    )
    with pytest.raises(ReviewerQualificationViolation) as exc:
        validate_blind_input(reviewer_input, authorized_case_ids=("blind-case-1",))
    assert exc.value.reason == REASON_EXPECTED_LABEL_LEAKED


def test_prior_reviewer_verdict_leakage_is_rejected():
    reviewer_input = _input(
        payload={"question": "q", "rows": [{"probe_verdict": "supported"}]}
    )
    with pytest.raises(ReviewerQualificationViolation) as exc:
        validate_blind_input(reviewer_input, authorized_case_ids=("blind-case-1",))
    assert exc.value.reason == REASON_PRIOR_VERDICT_LEAKED


# ---------------------------------------------------- 9: no authority in schema

def test_observation_schema_has_no_authority_field():
    fields = ReviewObservation.__dataclass_fields__
    assert "qualified_judge" not in fields
    assert "semantic_label" not in fields
    assert "release_observation" not in fields


def test_reviewer_cannot_smuggle_an_authority_claim():
    provenance = _provenance()
    for key in ("qualified_judge", "formal_semantic_label", "approved"):
        with pytest.raises(ReviewerQualificationViolation) as exc:
            parse_review_observation(
                {
                    "question_coverage": "covered",
                    "evidence_grounding": "supported",
                    "citation_support": "supported",
                    "issues": [],
                    key: True,
                },
                provenance=provenance,
                blind_case_id="blind-case-1",
            )
        assert exc.value.reason == REASON_REVIEWER_CLAIMED_AUTHORITY


def test_unknown_observation_fields_are_rejected():
    provenance = _provenance()
    with pytest.raises(ReviewerQualificationViolation):
        parse_review_observation(
            {
                "question_coverage": "covered",
                "evidence_grounding": "supported",
                "citation_support": "supported",
                "issues": [],
                "extra_notes": "hello",
            },
            provenance=provenance,
            blind_case_id="blind-case-1",
        )


def test_mixed_reviewers_cannot_be_blended_into_one_calibration():
    provenance = _provenance()
    other = _provenance(identity=_identity(model_id="someone-else"))
    controls = _perfect_controls(provenance=provenance)
    controls.append(
        ReviewedControl("wrong_citation", _observation("wrong_citation", provenance=other))
    )
    with pytest.raises(ReviewerQualificationViolation) as exc:
        check_calibration(reviewer_provenance=provenance, control_observations=controls)
    assert exc.value.reason == REASON_MIXED_REVIEWERS


# ------------------------------------------- authority seams stay separate

def test_calibration_pass_alone_cannot_be_granted_by_the_checker():
    """The frozen anti-pattern: calibration_pass must not imply GRANTED."""
    provenance, calibration = _calibration()
    assert calibration.calibration_pass is True
    decision = decide_qualification(
        authority_identity=AUTHORITY,
        decision_timestamp=LATER,
        reviewer_provenance=provenance,
        calibration=calibration,
        granted=False,
        decision_reason="authority withheld pending scope decision",
    )
    assert decision.status == QUALIFICATION_DENIED
    assert decision.qualified_judge is False


def test_authority_cannot_grant_on_a_failed_calibration():
    provenance, calibration = _calibration(overflag=1)
    assert calibration.calibration_pass is False
    with pytest.raises(ReviewerQualificationViolation) as exc:
        decide_qualification(
            authority_identity=AUTHORITY,
            decision_timestamp=LATER,
            reviewer_provenance=provenance,
            calibration=calibration,
            granted=True,
            decision_reason="looks good",
        )
    assert exc.value.reason == REASON_GRANT_ON_FAILED_CALIBRATION


def test_granted_judge_still_needs_a_second_authority_for_a_label():
    """A granted judge is eligibility for adjudication, not a label."""
    provenance, calibration = _calibration()
    qualification = decide_qualification(
        authority_identity=AUTHORITY,
        decision_timestamp=LATER,
        reviewer_provenance=provenance,
        calibration=calibration,
        granted=True,
        decision_reason="12/12 blind control performance",
    )
    assert qualification.status == QUALIFICATION_GRANTED

    case_review = _observation(None, provenance=provenance, blind_case_id="official-case-1")

    # No label exists until the case-label authority acts.
    assert LabelDecision.not_evaluated().status == LABEL_NOT_EVALUATED
    assert LabelDecision.not_evaluated().official_semantic_label is None

    label_decision = decide_case_label(
        authority_identity=AUTHORITY,
        decision_timestamp=LATER,
        qualification=qualification,
        case_review=case_review,
        accepted=True,
        decision_reason="independent review matches frozen sources",
        label={"question_coverage": "covered", "evidence_grounding": "supported"},
    )
    assert label_decision.status == LABEL_OFFICIAL
    assert label_decision.official_semantic_label == {
        "question_coverage": "covered",
        "evidence_grounding": "supported",
    }
    assert label_decision.qualification_artifact_hash == qualification.artifact_hash()


def test_case_label_authority_refuses_an_ungranted_reviewer():
    provenance, _ = _calibration()
    case_review = _observation(None, provenance=provenance, blind_case_id="official-case-1")
    with pytest.raises(ReviewerQualificationViolation) as exc:
        decide_case_label(
            authority_identity=AUTHORITY,
            decision_timestamp=LATER,
            qualification=QualificationDecision.not_evaluated(),
            case_review=case_review,
            accepted=True,
            decision_reason="skip the authority",
            label={"question_coverage": "covered"},
        )
    assert exc.value.reason == REASON_LABEL_WITHOUT_QUALIFICATION


def test_official_label_requires_an_explicit_label_payload():
    provenance, calibration = _calibration()
    qualification = decide_qualification(
        authority_identity=AUTHORITY,
        decision_timestamp=LATER,
        reviewer_provenance=provenance,
        calibration=calibration,
        granted=True,
        decision_reason="12/12",
    )
    case_review = _observation(None, provenance=provenance, blind_case_id="official-case-1")
    with pytest.raises(ReviewerQualificationViolation):
        decide_case_label(
            authority_identity=AUTHORITY,
            decision_timestamp=LATER,
            qualification=qualification,
            case_review=case_review,
            accepted=True,
            decision_reason="approved",
        )


# ------------------------------------------------------------ adapters / purity

def test_adapters_are_protocol_only_and_never_call_a_provider():
    reviewer, calls = _reviewer()
    assert reviewer.reviewer_kind == "model"
    observation = reviewer.review(_input())
    assert calls["n"] == 1
    assert isinstance(observation, ReviewObservation)
    assert observation.blind_case_id == "blind-case-1"
    assert reviewer_identity_hash(reviewer.identity) == reviewer_identity_hash(_identity())


def test_manual_human_adapter_shares_the_same_contract():
    identity = _identity(reviewer_kind="manual_human", provider="owner", model_family="human")
    reviewer = ManualHumanReviewer(
        identity=identity,
        produce=lambda reviewer_input: {
            "question_coverage": "covered",
            "evidence_grounding": "supported",
            "citation_support": "supported",
            "issues": [],
        },
        invocation_id_factory=lambda: "manual-1",
        clock=lambda: INSTANT,
    )
    observation = reviewer.review(_input())
    assert observation.provenance.identity.reviewer_kind == "manual_human"
    validate_reviewer_independence(
        observation.provenance, answer_model_families=("deepseek",)
    )


def test_unknown_reviewer_kind_is_rejected_at_construction():
    with pytest.raises(ReviewerQualificationViolation):
        make_identity(
            reviewer_kind="oracle",
            provider="p",
            model_family="f",
            model_id="m",
            revision="r",
        )


def test_calibration_result_is_deterministic_and_grants_nothing_twice():
    provenance, first = _calibration()
    _, second = _calibration()
    assert first.to_dict() == second.to_dict()
    assert first.artifact_hash() == second.artifact_hash()
    assert isinstance(first, CalibrationResult)
    assert provenance.input_manifest_hash == first.input_manifest_hash
