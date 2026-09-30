"""§162 A3-A: the blind packet leaks nothing and the ingest grants nothing."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import cast

import pytest

from src.evals.release_benchmark_blind_review import (
    CONTROL_VARIANTS,
    REASON_DUPLICATE_ITEM,
    REASON_MISSING_ITEM,
    REASON_RESPONSE_SHAPE,
    REASON_RUN_ID_MISMATCH,
    REASON_SELF_REPORTED_CONSISTENCY,
    REASON_UNKNOWN_ITEM,
    SCHEMA_INGEST,
    SCHEMA_PACKET,
    build_blind_review_packet,
    ingest_review_run,
    render_packet_text,
)
from src.evals.release_benchmark_plan import load_release_benchmark_plan
from src.evals.release_benchmark_registry import load_gold, load_registry
from src.evals.release_benchmark_reviewer_qualification import (
    REASON_REVIEWER_CLAIMED_AUTHORITY,
    REASON_SAME_MODEL_FAMILY,
    ReviewerQualificationViolation,
    make_identity,
)
from src.evals.release_benchmark_semantic_probe import materialize_review_items

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/release_benchmark"
BUNDLE = (ROOT / "docs/research_quality/"
          "RELEASE_BENCHMARK_REMOTE_OBSERVATION_2026-09-29/answer_bundle.json")

RUN_ID = "rq-review-20261001-001"
INSTANT = "2026-10-01T00:00:00Z"

_JUDGMENT = {
    "actual": (("covered", "supported", "supported"), ()),
    "wrong_citation": (("covered", "supported", "gap"), ("wrong_citation",)),
    "missing_aspect": (("partial", "supported", "supported"), ("coverage_gap",)),
    "unsupported_claim": (("covered", "gap", "gap"), ("unsupported_claim",)),
}


def _materialized() -> dict:
    plan = load_release_benchmark_plan(FIXTURES / "plan_v1.json")
    registry = load_registry(FIXTURES / "registry_v1.json", ROOT, plan)
    gold = load_gold(FIXTURES / "gold_v1.json", registry)
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
    return materialize_review_items(bundle, registry, gold, ROOT)


def _packet() -> tuple[dict, dict]:
    materialized = _materialized()
    built = build_blind_review_packet(
        materialized,
        review_run_id=RUN_ID,
        answer_bundle_sha256=sha256(BUNDLE.read_bytes()).hexdigest(),
        registry_sha256=sha256((FIXTURES / "registry_v1.json").read_bytes()).hexdigest(),
        gold_sha256=sha256((FIXTURES / "gold_v1.json").read_bytes()).hexdigest(),
    )
    return cast(dict, built["packet"]), cast(dict, built["manifest"])


def _row(variant: str, blind_case_id: str, *, source_id: str = "src-1") -> dict:
    axes, issue_types = _JUDGMENT[variant]
    return {
        "blind_case_id": blind_case_id,
        "question_coverage": axes[0],
        "evidence_grounding": axes[1],
        "citation_support": axes[2],
        "issues": [
            {"issue_type": issue_type, "reason": "source-bound", "evidence_refs": [source_id]}
            for issue_type in issue_types
        ],
    }


def _response(manifest, *, override=None) -> str:
    rows = []
    for item in manifest["items"]:
        row = _row(item["variant"], item["blind_case_id"])
        if override is not None:
            row = override(row, item) or row
        rows.append(row)
    return json.dumps({"review_run_id": RUN_ID, "observations": rows}, ensure_ascii=False)


def _ingest(packet, manifest, raw, *, identity=None, families=("deepseek",), **kwargs):
    return ingest_review_run(
        packet=packet,
        manifest=manifest,
        raw_response_text=raw,
        reviewer_identity=identity or make_identity(
            reviewer_kind="model",
            provider="OpenAI",
            model_family="GPT",
            model_id="gpt-5.6-sol",
            revision="2026-10",
        ),
        invocation_id=RUN_ID,
        timestamp=INSTANT,
        answer_model_families=families,
        **kwargs,
    )


# ------------------------------------------------------------ packet hygiene

def test_packet_items_carry_no_variant_and_no_case_identity():
    packet, manifest = _packet()
    blob = json.dumps(packet["items"], ensure_ascii=False)
    for item in packet["items"]:
        assert not (set(item) & set(CONTROL_VARIANTS))
        assert not (set(str(value) for value in item.values()) & set(CONTROL_VARIANTS))
    for item in manifest["items"]:
        assert item["case_id"] not in blob
    # The variant map exists only in the repository-side manifest.
    assert all(item["variant"] in {"actual", *CONTROL_VARIANTS} for item in manifest["items"])
    assert "variant" not in blob


def test_packet_never_reveals_that_controls_exist():
    packet, _ = _packet()
    text = json.dumps(packet, ensure_ascii=False).lower()
    for forbidden in ("control", "expected", "gold", "specificity", "balance",
                      "another reviewer", "over-flag", "false positive"):
        assert forbidden not in text


def test_packet_item_ids_are_opaque_and_do_not_encode_the_variant():
    packet, manifest = _packet()
    for item in manifest["items"]:
        assert item["blind_case_id"].startswith(f"{RUN_ID}-item-")
        for variant in CONTROL_VARIANTS:
            assert variant not in item["blind_case_id"]
    assert len(packet["items"]) == len(manifest["items"]) == 8


def test_packet_never_groups_a_case_with_its_own_controls():
    """Position must not reveal which item is a control."""
    _, manifest = _packet()
    variants = [item["variant"] for item in manifest["items"]]
    cases = [item["case_id"] for item in manifest["items"]]
    # No run of four consecutive items belongs to a single case.
    for start in range(len(cases) - 3):
        assert len(set(cases[start:start + 4])) > 1
    assert set(variants) == {"actual", *CONTROL_VARIANTS}


def test_packet_declares_schema_and_manifest_hash():
    packet, manifest = _packet()
    assert packet["schema_version"] == SCHEMA_PACKET
    assert packet["input_manifest_hash"] == manifest["input_manifest_hash"]
    assert len(packet["input_manifest_hash"]) == 64


def test_render_packet_text_is_self_contained_and_item_blind():
    packet, _ = _packet()
    text = render_packet_text(packet)
    assert "INPUT JSON:" in text
    assert RUN_ID in text
    for item in packet["items"]:
        assert item["blind_case_id"] in text
    assert "control" not in text.lower()


def test_packet_build_is_deterministic():
    first, first_manifest = _packet()
    second, second_manifest = _packet()
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert json.dumps(first_manifest, sort_keys=True) == json.dumps(
        second_manifest, sort_keys=True
    )


# ------------------------------------------------------------- ingest happy path

def test_ingest_of_a_perfect_response_passes_calibration_but_grants_nothing():
    packet, manifest = _packet()
    artifact = _ingest(packet, manifest, _response(manifest))
    assert artifact["schema_version"] == SCHEMA_INGEST
    assert artifact["calibration_pass"] is True
    assert artifact["eligible_for_authority_review"] is True
    assert artifact["calibration"]["target_gate_pass"] is True
    assert artifact["calibration"]["specificity_gate_pass"] is True
    assert artifact["calibration"]["target_detected"] == 6
    assert artifact["calibration"]["specificity_correct"] == 6
    # A passing calibration is still not a judge and still not a label.
    assert artifact["qualified_judge"] is False
    assert artifact["formal_semantic_label"] is False
    assert artifact["release_observation"] is False
    assert artifact["release_gate"] == "NO_GO"
    assert artifact["independence_ok"] is True
    assert artifact["invocation_id_kind"] == "harness_assigned_run_id"


def test_ingest_records_the_traceability_tuple():
    packet, manifest = _packet()
    raw = _response(manifest)
    artifact = _ingest(packet, manifest, raw)
    assert artifact["output_hash"] == sha256(raw.encode("utf-8")).hexdigest()
    assert artifact["input_manifest_hash"] == packet["input_manifest_hash"]
    assert artifact["invocation_id"] == RUN_ID
    assert artifact["reviewer"]["provider"] == "OpenAI"
    assert artifact["reviewer"]["model_family"] == "GPT"
    assert artifact["answer_model_families"] == ["deepseek"]


def test_ingest_of_one_overflagged_control_fails_the_gate():
    packet, manifest = _packet()

    def overflag(row, item):
        if item["variant"] == "wrong_citation":
            row["issues"].append(
                {"issue_type": "unsupported_claim", "reason": "extra", "evidence_refs": []}
            )
            row["evidence_grounding"] = "gap"
        return row

    artifact = _ingest(packet, manifest, _response(manifest, override=overflag))
    assert artifact["calibration"]["target_gate_pass"] is True
    assert artifact["calibration"]["specificity_gate_pass"] is False
    assert artifact["calibration_pass"] is False
    assert artifact["qualified_judge"] is False


def test_ingest_computes_consistency_in_code_not_from_the_reviewer():
    """An axis marked supported while its issue reports a gap must be caught."""
    packet, manifest = _packet()

    def lie(row, item):
        if item["variant"] == "wrong_citation":
            row["citation_support"] = "supported"
        return row

    artifact = _ingest(packet, manifest, _response(manifest, override=lie))
    assert artifact["calibration"]["target_gate_pass"] is False
    assert artifact["calibration_pass"] is False


# ------------------------------------------------------------- ingest refusals

def test_ingest_rejects_an_unknown_blind_case_id():
    packet, manifest = _packet()
    raw = json.dumps({
        "review_run_id": RUN_ID,
        "observations": [
            _row("actual", f"{RUN_ID}-item-99"),
        ],
    })
    with pytest.raises(ReviewerQualificationViolation) as exc:
        _ingest(packet, manifest, raw)
    assert exc.value.reason == REASON_UNKNOWN_ITEM


def test_ingest_rejects_a_missing_item():
    packet, manifest = _packet()
    rows = [
        _row(item["variant"], item["blind_case_id"]) for item in manifest["items"][:-1]
    ]
    raw = json.dumps({"review_run_id": RUN_ID, "observations": rows})
    with pytest.raises(ReviewerQualificationViolation) as exc:
        _ingest(packet, manifest, raw)
    assert exc.value.reason == REASON_MISSING_ITEM


def test_ingest_rejects_a_duplicate_item():
    packet, manifest = _packet()
    first = manifest["items"][0]
    rows = [_row(item["variant"], item["blind_case_id"]) for item in manifest["items"]]
    rows.append(_row(first["variant"], first["blind_case_id"]))
    raw = json.dumps({"review_run_id": RUN_ID, "observations": rows})
    with pytest.raises(ReviewerQualificationViolation) as exc:
        _ingest(packet, manifest, raw)
    assert exc.value.reason == REASON_DUPLICATE_ITEM


def test_ingest_rejects_a_run_id_mismatch():
    packet, manifest = _packet()
    raw = json.dumps({
        "review_run_id": "some-other-run",
        "observations": [
            _row(item["variant"], item["blind_case_id"]) for item in manifest["items"]
        ],
    })
    with pytest.raises(ReviewerQualificationViolation) as exc:
        _ingest(packet, manifest, raw)
    assert exc.value.reason == REASON_RUN_ID_MISMATCH


def test_ingest_rejects_extra_top_level_keys():
    packet, manifest = _packet()
    raw = json.dumps({
        "review_run_id": RUN_ID,
        "observations": [
            _row(item["variant"], item["blind_case_id"]) for item in manifest["items"]
        ],
        "self_assessment": "qualified",
    })
    with pytest.raises(ReviewerQualificationViolation) as exc:
        _ingest(packet, manifest, raw)
    assert exc.value.reason == REASON_RESPONSE_SHAPE


def test_ingest_rejects_a_reviewer_supplied_consistency_flag():
    packet, manifest = _packet()

    def add_flag(row, item):
        row["dimension_consistent"] = True
        return row

    with pytest.raises(ReviewerQualificationViolation) as exc:
        _ingest(packet, manifest, _response(manifest, override=add_flag))
    assert exc.value.reason == REASON_SELF_REPORTED_CONSISTENCY


def test_ingest_rejects_a_reviewer_claiming_authority():
    packet, manifest = _packet()

    def claim(row, item):
        row["qualified_judge"] = True
        return row

    with pytest.raises(ReviewerQualificationViolation) as exc:
        _ingest(packet, manifest, _response(manifest, override=claim))
    assert exc.value.reason == REASON_REVIEWER_CLAIMED_AUTHORITY


def test_ingest_rejects_a_same_family_reviewer():
    packet, manifest = _packet()
    identity = make_identity(
        reviewer_kind="model",
        provider="DeepSeek",
        model_family="deepseek",
        model_id="deepseek-pro",
        revision="2026-09",
    )
    with pytest.raises(ReviewerQualificationViolation) as exc:
        _ingest(packet, manifest, _response(manifest), identity=identity)
    assert exc.value.reason == REASON_SAME_MODEL_FAMILY


def test_ingest_rejects_an_empty_answer_model_family_list():
    packet, manifest = _packet()
    with pytest.raises(ReviewerQualificationViolation):
        _ingest(packet, manifest, _response(manifest), families=())
