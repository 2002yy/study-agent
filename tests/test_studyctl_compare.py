"""Recorded deltas are diagnostics, not controlled quality qualification."""

import json

import pytest

from tests.test_studyctl import invoke, repo as repo
from tests.test_studyctl_recording import ARTIFACT, RUN_ID
from tools import studyctl_recording


def compare(repo, capsys, right=ARTIFACT, *extra):
    return invoke(
        capsys,
        "--repo",
        str(repo),
        "research",
        "compare",
        "--left-artifact",
        str(ARTIFACT),
        "--right-artifact",
        str(right),
        "--run",
        RUN_ID,
        *extra,
    )


def test_same_real_recording_is_explicit_and_not_quality_pass(repo, capsys):
    before = ARTIFACT.read_bytes()
    result = compare(repo, capsys)
    data = result["data"]
    assert result["command"] == "research compare"
    assert result["status"] == "PARTIAL" and result["exit_code"] == 3
    assert data["same_artifact"]
    assert all(change["delta"] == 0 for change in data["changes"])
    assert "model_identity" in data["missing_provenance"]
    assert data["left"]["recorded_stop_reason"] == "evidence_budget_exhausted"
    assert "citation_support_events_unavailable" in data["left"]["missing_evidence"]
    assert ARTIFACT.read_bytes() == before


@pytest.fixture
def right(tmp_path):
    path = tmp_path / "right.json"
    path.write_bytes(ARTIFACT.read_bytes())
    return path


def update(path, change):
    data = json.loads(path.read_bytes())
    change(data)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_right_minus_left_and_missing_values_remain_explicit(repo, capsys, right):
    def change(data):
        data["candidates"]["count"] += 2
        del data["metrics"]["read_count"]
        data["gate"]["stop_reason"] = "evidence_gate_pass"

    update(right, change)
    before = right.read_bytes()
    result = compare(repo, capsys, right)
    data = result["data"]
    changes = {row["field"]: row for row in data["changes"]}
    assert changes["candidates.count"]["delta"] == 2
    assert changes["metrics.read_count"] == {
        "field": "metrics.read_count",
        "left": 0,
        "right": None,
        "delta": None,
    }
    assert "conflicting_recorded_stop_reasons" in data["right"]["missing_evidence"]
    assert not data["same_artifact"] and result["status"] == "PARTIAL"
    assert right.read_bytes() == before


@pytest.mark.parametrize(
    "case",
    [
        "question",
        "date",
        "missing_question",
        "missing_date",
        "schema",
        "identity",
        "bad_count",
        "bad_json",
    ],
)
def test_incompatible_records_block_without_counter_output(repo, capsys, right, case):
    def change(data):
        if case == "question":
            data["question"] = "secret-other-question"
        elif case == "date":
            data["reference_date"] = "2026-10-21"
        elif case == "missing_question":
            data.pop("question")
        elif case == "missing_date":
            data.pop("reference_date")
        elif case == "schema":
            data["schema_version"] = "obsolete"
        elif case == "identity":
            data["ui_progress"]["run_id"] = "foreign-run"
        elif case == "bad_count":
            data["metrics"]["read_count"] = False

    update(right, change)
    if case == "bad_json":
        right.write_text("secret-malformed-json", encoding="utf-8")
    result = compare(repo, capsys, right)
    assert result["status"] == "BLOCKED" and result["exit_code"] == 3
    assert not result["data"].get("changes") and "secret-" not in json.dumps(result)


def test_context_comparison_does_not_emit_question(repo, capsys):
    question = json.loads(ARTIFACT.read_bytes())["question"]
    result = compare(repo, capsys)
    assert question not in json.dumps(result)
    assert len(result["data"]["context_sha256"]) == 64


def test_missing_arguments_never_default_to_live_inputs(repo, capsys):
    result = invoke(capsys, "--repo", str(repo), "research", "compare")
    assert result["exit_code"] == 2


def test_oversized_recording_uses_existing_input_budget(repo, capsys, monkeypatch):
    monkeypatch.setattr(studyctl_recording, "MAX_RECORDING_BYTES", 1)
    assert compare(repo, capsys)["status"] == "BLOCKED"


def test_dry_run_does_not_publish_or_mutate(repo, capsys, tmp_path):
    output = tmp_path / "not-written.json"
    before = ARTIFACT.read_bytes()
    result = compare(repo, capsys, ARTIFACT, "--dry-run", "--output", str(output))
    assert result["status"] == "PARTIAL" and not output.exists()
    assert ARTIFACT.read_bytes() == before
