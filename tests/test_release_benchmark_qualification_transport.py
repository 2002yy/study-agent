"""§162 A3-D-2: composite transport scores per cluster and never by total."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import pytest

from src.evals.release_benchmark_blind_review import (
    SCHEMA_HOLDOUT_INGEST,
    SCHEMA_HOLDOUT_MANIFEST,
    SCHEMA_HOLDOUT_PACKET,
    build_holdout_packet,
    ingest_holdout_review_run,
)
from src.evals.release_benchmark_reviewer_qualification import (
    ReviewerQualificationViolation,
    make_identity,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/release_benchmark"
COMPOSITE = FIXTURES / "qualification_holdout_v1.json"
RUN_ID = "rq-qual-20261001-001"
INSTANT = "2026-10-01T08:00:00Z"

CLUSTER_A = "CLUSTER-A-NWS-HEAT"
CLUSTER_B = "CLUSTER-B-NOAA-TIDES"

_JUDGMENT = {
    "actual": (("covered", "supported", "supported"), ()),
    "wrong_citation": (("covered", "supported", "gap"), ("wrong_citation",)),
    "missing_aspect": (("partial", "supported", "supported"), ("coverage_gap",)),
    "unsupported_claim": (("covered", "gap", "gap"), ("unsupported_claim",)),
}

_FORBIDDEN_AGGREGATES = (
    "overall_tp", "overall_tn", "overall_accuracy", "overall_score",
    "total_correct", "overall_confusion", "overall_target_total",
)


def _composite() -> dict:
    return json.loads(COMPOSITE.read_text(encoding="utf-8"))


def _built() -> tuple[dict, dict]:
    built = build_holdout_packet(
        composite=_composite(), root=ROOT, review_run_id=RUN_ID
    )
    return built["packet"], built["manifest"]


def _row(variant: str, blind_case_id: str) -> dict:
    axes, issue_types = _JUDGMENT[variant]
    return {
        "blind_case_id": blind_case_id,
        "question_coverage": axes[0],
        "evidence_grounding": axes[1],
        "citation_support": axes[2],
        "issues": [
            {"issue_type": issue_type, "reason": "source-bound", "evidence_refs": []}
            for issue_type in issue_types
        ],
    }


def _response(manifest: dict, *, break_specificity_in: str | None = None) -> str:
    rows = []
    broken = False
    for item in manifest["items"]:
        row = _row(item["variant"], item["blind_case_id"])
        if (
            not broken
            and break_specificity_in is not None
            and item["cluster_id"] == break_specificity_in
            and item["variant"] == "unsupported_claim"
        ):
            # Exactly one control: target still detected, citation support left supported.
            row["citation_support"] = "supported"
            broken = True
        rows.append(row)
    return json.dumps({"review_run_id": RUN_ID, "observations": rows}, ensure_ascii=False)


def _ingest(packet: dict, manifest: dict, raw: str) -> dict:
    return ingest_holdout_review_run(
        packet=packet,
        manifest=manifest,
        raw_response_text=raw,
        reviewer_identity=make_identity(
            reviewer_kind="model",
            provider="OpenAI",
            model_family="GPT",
            model_id="gpt-5.6-sol",
            revision="2026-10",
        ),
        invocation_id=RUN_ID,
        timestamp=INSTANT,
        answer_model_families=("deepseek",),
    )


# ------------------------------------------------------------- packet hygiene

def test_packet_hides_the_composite_structure() -> None:
    packet, _ = _built()
    blob = json.dumps(packet, ensure_ascii=False).lower()
    for forbidden in ("cluster", "composite", "gate_rule", "overall_pass",
                      "holdout_id", "instance_id"):
        assert forbidden not in blob
    assert packet["schema_version"] == SCHEMA_HOLDOUT_PACKET


def test_packet_carries_no_per_cluster_counts() -> None:
    packet, manifest = _built()
    assert len(packet["items"]) == 16
    assert len(manifest["items"]) == 16
    # Cluster membership is only in the repository-side manifest.
    assert {item["cluster_id"] for item in manifest["items"]} == {CLUSTER_A, CLUSTER_B}


def test_packet_build_is_deterministic() -> None:
    first, first_manifest = _built()
    second, second_manifest = _built()
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert json.dumps(first_manifest, sort_keys=True) == json.dumps(
        second_manifest, sort_keys=True
    )


def test_manifest_records_the_full_digest_chain() -> None:
    packet, manifest = _built()
    assert manifest["schema_version"] == SCHEMA_HOLDOUT_MANIFEST
    composite = _composite()
    assert manifest["composite_manifest_sha256"] == composite["content_sha256"]
    assert set(manifest["cluster_fixture_sha256"]) == {CLUSTER_A, CLUSTER_B}
    assert set(manifest["cluster_source_sha256"]) == {"NWS-HEAT", "NOAA-TIDES"}
    assert manifest["packet_sha256"]
    assert manifest["input_manifest_hash"] == packet["input_manifest_hash"]


# --------------------------------------------------------------- cluster tree

def test_every_cluster_passes_when_all_controls_are_right() -> None:
    packet, manifest = _built()
    artifact = _ingest(packet, manifest, _response(manifest))
    assert artifact["schema_version"] == SCHEMA_HOLDOUT_INGEST
    results = artifact["cluster_results"]
    assert set(results) == {CLUSTER_A, CLUSTER_B}
    for cluster_id, result in results.items():
        assert result["target_detected"] == 6, cluster_id
        assert result["target_total"] == 6
        assert result["specificity_correct"] == 6
        assert result["specificity_total"] == 6
        assert result["target_gate_pass"] is True
        assert result["specificity_gate_pass"] is True
        assert result["cluster_pass"] is True
    assert artifact["overall_pass"] is True
    assert artifact["eligible_for_authority_review"] is True
    # Even a full pass is not a judge and not a label.
    assert artifact["qualified_judge"] is False
    assert artifact["formal_semantic_label"] is False
    assert artifact["release_observation"] is False
    assert artifact["release_gate"] == "NO_GO"


def test_result_tree_exposes_no_aggregate_counts() -> None:
    packet, manifest = _built()
    artifact = _ingest(packet, manifest, _response(manifest))
    blob = json.dumps(artifact, ensure_ascii=False)
    for forbidden in _FORBIDDEN_AGGREGATES:
        assert forbidden not in blob
    assert "overall_pass" in blob


def test_artifact_carries_the_digest_chain() -> None:
    packet, manifest = _built()
    raw = _response(manifest)
    artifact = _ingest(packet, manifest, raw)
    composite = _composite()
    assert artifact["composite_manifest_sha256"] == composite["content_sha256"]
    assert artifact["cluster_fixture_sha256"] == manifest["cluster_fixture_sha256"]
    assert artifact["cluster_source_sha256"] == manifest["cluster_source_sha256"]
    assert artifact["packet_sha256"] == manifest["packet_sha256"]
    assert artifact["output_hash"] == sha256(raw.encode("utf-8")).hexdigest()


# ------------------------------------------------- anti-averaging behaviour

def test_one_cluster_failing_specificity_fails_the_whole_holdout() -> None:
    """A: all right, B: 6/6 detection but 5/6 specificity -> overall false."""
    packet, manifest = _built()
    artifact = _ingest(
        packet, manifest, _response(manifest, break_specificity_in=CLUSTER_B)
    )
    assert artifact["cluster_results"][CLUSTER_A]["cluster_pass"] is True
    b_result = artifact["cluster_results"][CLUSTER_B]
    assert b_result["target_gate_pass"] is True
    assert b_result["specificity_gate_pass"] is False
    assert b_result["specificity_correct"] == 5
    assert b_result["cluster_pass"] is False
    assert artifact["overall_pass"] is False
    assert artifact["eligible_for_authority_review"] is False
    assert artifact["qualified_judge"] is False
    assert artifact["formal_semantic_label"] is False
    assert artifact["release_gate"] == "NO_GO"


def test_the_symmetric_case_fails_too() -> None:
    """A fails, B is perfect -> overall still false."""
    packet, manifest = _built()
    artifact = _ingest(
        packet, manifest, _response(manifest, break_specificity_in=CLUSTER_A)
    )
    assert artifact["cluster_results"][CLUSTER_A]["cluster_pass"] is False
    assert artifact["cluster_results"][CLUSTER_B]["cluster_pass"] is True
    assert artifact["overall_pass"] is False
    assert artifact["eligible_for_authority_review"] is False


def test_overall_pass_is_exactly_the_conjunction() -> None:
    packet, manifest = _built()
    for broken in (None, CLUSTER_A, CLUSTER_B):
        artifact = _ingest(
            packet, manifest, _response(manifest, break_specificity_in=broken)
        )
        per_cluster = [
            result["cluster_pass"] for result in artifact["cluster_results"].values()
        ]
        assert artifact["overall_pass"] == all(per_cluster)
        assert artifact["eligible_for_authority_review"] == artifact["overall_pass"]


# -------------------------------------------------------------- ingest refusals

def test_ingest_rejects_an_unknown_blind_case_id() -> None:
    packet, manifest = _built()
    raw = json.dumps({
        "review_run_id": RUN_ID,
        "observations": [_row("actual", f"{RUN_ID}-item-99")],
    })
    with pytest.raises(ReviewerQualificationViolation):
        _ingest(packet, manifest, raw)


def test_ingest_rejects_a_reviewer_supplied_consistency_flag() -> None:
    packet, manifest = _built()
    rows = [
        _row(item["variant"], item["blind_case_id"]) for item in manifest["items"]
    ]
    rows[0]["dimension_consistent"] = True
    raw = json.dumps({"review_run_id": RUN_ID, "observations": rows})
    with pytest.raises(ReviewerQualificationViolation):
        _ingest(packet, manifest, raw)


def test_ingest_refuses_a_same_family_reviewer() -> None:
    packet, manifest = _built()
    with pytest.raises(ReviewerQualificationViolation):
        ingest_holdout_review_run(
            packet=packet,
            manifest=manifest,
            raw_response_text=_response(manifest),
            reviewer_identity=make_identity(
                reviewer_kind="model",
                provider="DeepSeek",
                model_family="deepseek",
                model_id="deepseek-pro",
                revision="2026-09",
            ),
            invocation_id=RUN_ID,
            timestamp=INSTANT,
            answer_model_families=("deepseek",),
        )
