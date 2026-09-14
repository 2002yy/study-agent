"""Deterministic tests for the frozen-artifact answer A/B refusal path."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.run_frozen_answer_ab import (
    SCHEMA_VERSION,
    classify_answer_input,
    load_frozen_case,
    run_ab,
)

HISTORICAL = Path(
    "docs/research_quality/RQ1C_BOUNDED_QUALIFICATION_RUNTIME.4d1ed67.json"
)
PARTIAL_CASE = "rq1c-historical-current-node-modules"


def _case(*relations: str, gate: str = "partial") -> dict:
    return {
        "case_id": "case-x",
        "question": "q",
        "gate": {"status": gate},
        "brief": {
            "eligible_evidence": [
                {"evidence_id": f"e{index}", "relation": relation}
                for index, relation in enumerate(relations)
            ]
        },
        "answer": {
            "text": "fail-closed copy",
            "validation": {"phases": {"answer_claim_binding": {"outcome": "rejected"}}},
        },
        "sources": [{"title": "t", "url": "https://example.test", "source_role": "primary"}],
    }


def test_classification_treats_lead_only_evidence_as_blocked() -> None:
    """gate=partial with only lead rows is still a blocked answer input."""

    result = classify_answer_input(_case("lead", "lead"))

    assert result["gate_status"] == "partial"
    assert result["lead_row_count"] == 2
    assert result["binding_row_count"] == 0
    assert result["answer_input_class"] == "blocked_no_binding_rows"


def test_classification_marks_supports_rows_as_substantive() -> None:
    result = classify_answer_input(_case("supports", "lead"))

    assert result["binding_row_count"] == 1
    assert result["answer_input_class"] == "substantive"


def test_historical_partial_artifact_is_answer_blocked() -> None:
    """The real 4d1ed67 PARTIAL case has no binding rows, so it cannot host an A/B."""

    if not HISTORICAL.exists():  # untracked diagnostic artifact
        pytest.skip("historical artifact not present")

    _data, case = load_frozen_case(HISTORICAL, PARTIAL_CASE)
    result = classify_answer_input(case)

    assert result["gate_status"] == "partial"
    assert result["binding_row_count"] == 0
    assert result["answer_input_class"] == "blocked_no_binding_rows"


def test_run_ab_refuses_to_fake_a_partial_experiment(tmp_path: Path) -> None:
    artifact_path = tmp_path / "artifact.json"
    artifact_path.write_text(
        json.dumps({"git_sha": "a" * 40, "cases": [_case("lead")]}), encoding="utf-8"
    )
    output = tmp_path / "ab.json"

    artifact = run_ab(
        artifact_path=artifact_path,
        case_id="case-x",
        output_path=output,
        repeats=3,
        answer_timeout_seconds=90.0,
        deadline_seconds=240.0,
        allow_blocked_replay=False,
    )

    assert artifact["status"] == "refused_not_substantive"
    assert artifact["qualification_evidence"] is False
    assert artifact["arms"] == {}
    assert "release gate would replace" in artifact["refusal_reason"]
    assert artifact["web_context_source"] == "reconstructed_from_bounded_sources"
    assert output.exists()
    written = json.loads(output.read_text(encoding="utf-8"))
    assert written["status"] == "refused_not_substantive"


def test_frozen_case_lookup_fails_closed(tmp_path: Path) -> None:
    artifact_path = tmp_path / "artifact.json"
    artifact_path.write_text(json.dumps({"cases": []}), encoding="utf-8")

    with pytest.raises(ValueError):
        load_frozen_case(artifact_path, "missing")


def test_schema_marks_the_tool_as_diagnostic_only() -> None:
    assert SCHEMA_VERSION == "rq1c-frozen-answer-ab-v1"
    source = Path("tools/run_frozen_answer_ab.py").read_text(encoding="utf-8")
    assert '"qualification_evidence": False' in source
    assert "not byte-identical" in source
