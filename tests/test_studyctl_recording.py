"""Inspect a real committed B5 recording offline without running its producer."""

import ast
import hashlib
import json
from pathlib import Path

import pytest

from tests.test_studyctl import invoke, repo as repo
from tools import studyctl, studyctl_recording

ARTIFACT = (
    Path(__file__).resolve().parents[1]
    / "docs/research_quality/B5_ACTIVE_SEARXNG_SMOKE.json"
)
RUN_ID = "b5_active_searxng_smoke"


def inspect(repo, artifact, capsys, *args):
    return invoke(
        capsys,
        "--repo",
        str(repo),
        "research",
        "inspect",
        "--run",
        RUN_ID,
        "--artifact",
        str(artifact),
        *args,
    )


def test_real_committed_recording_is_partial_and_preserves_exact_facts(repo, capsys):
    original = ARTIFACT.read_bytes()
    result = inspect(repo, ARTIFACT, capsys)
    data = result["data"]
    assert result["status"] == "PARTIAL" and result["exit_code"] == 3
    assert data["artifact_sha256"] == hashlib.sha256(original).hexdigest()
    assert (
        data["recorded_status"] == "partial"
        and data["recorded_gate_status"] == "partial"
    )
    assert data["recorded_stop_reason"] == "evidence_budget_exhausted"
    assert data["recorded_summary"]["candidates"]["count"] == 7
    assert data["recorded_summary"]["metrics"]["read_count"] == 0
    assert data["recorded_summary"]["gate"]["eligible_evidence_count"] == 0
    assert (
        data["events"] == []
        and data["coverage"]["citation_support"] == "insufficient_evidence"
    )
    assert data["identity_source"].endswith("(correlation only)")
    assert "brief_excerpt" not in json.dumps(data) and "question" not in data
    assert ARTIFACT.read_bytes() == original
    assert result["head_sha"] == studyctl.git(studyctl.ROOT, "rev-parse", "HEAD")


def test_schema_matches_existing_producer_without_importing_live_runtime():
    producer = ARTIFACT.parents[2] / "tools/run_research_active_smoke.py"
    tree = ast.parse(producer.read_text(encoding="utf-8"))
    schema = next(
        node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(name, ast.Name) and name.id == "SMOKE_SCHEMA_VERSION"
            for name in node.targets
        )
    )
    assert schema == studyctl_recording.RECORDING_SCHEMA


@pytest.fixture
def recording(tmp_path):
    path = tmp_path / "recording.json"
    path.write_bytes(ARTIFACT.read_bytes())
    return path


@pytest.mark.parametrize(
    "change",
    [
        "wrong_run",
        "foreign_run",
        "old_schema",
        "bad_json",
        "duplicate",
        "bad_section",
        "negative_count",
        "boolean_count",
        "nan",
    ],
)
def test_invalid_recording_is_blocked_without_fabricated_events(
    repo, recording, capsys, change
):
    data = json.loads(recording.read_bytes())
    if change == "wrong_run":
        data["ui_progress"]["run_id"] = "another-run"
    elif change == "foreign_run":
        data["run"]["id"] = "another-run"
    elif change == "old_schema":
        data["schema_version"] = "obsolete"
    elif change == "bad_section":
        data["search"] = []
    elif change in {"negative_count", "boolean_count"}:
        data["metrics"]["read_count"] = -1 if change == "negative_count" else True
    if change == "bad_json":
        recording.write_text("secret-bad-json", encoding="utf-8")
    elif change == "duplicate":
        recording.write_text(
            '{"schema_version":"obsolete",' + json.dumps(data)[1:], encoding="utf-8"
        )
    elif change == "nan":
        recording.write_text(json.dumps(data)[:-1] + ',"unused":NaN}', encoding="utf-8")
    else:
        recording.write_text(json.dumps(data), encoding="utf-8")
    result = inspect(repo, recording, capsys)
    assert result["status"] == "BLOCKED" and not result["data"].get("events")
    assert "secret-bad-json" not in json.dumps(result)


def test_missing_summaries_are_unknown_rather_than_zero(repo, recording, capsys):
    data = json.loads(recording.read_bytes())
    del data["search"]
    del data["metrics"]["read_count"]
    recording.write_text(json.dumps(data), encoding="utf-8")
    result = inspect(repo, recording, capsys)
    assert result["status"] == "PARTIAL"
    assert result["data"]["recorded_summary"]["metrics"]["read_count"] is None
    assert result["data"]["coverage"]["search"] == "insufficient_evidence"


def test_completed_summary_still_cannot_supply_missing_citation_support(
    repo, recording, capsys
):
    data = json.loads(recording.read_bytes())
    data["run"].update(status="completed", stop_reason="evidence_gate_pass")
    data["gate"]["stop_reason"] = "evidence_gate_pass"
    data["gate"]["status"] = "pass"
    data["brief_excerpt"] = {"summary": "secret-answer-claims-success"}
    recording.write_text(json.dumps(data), encoding="utf-8")
    result = inspect(repo, recording, capsys)
    assert result["status"] == "PARTIAL" and not result["data"]["events"]
    assert "secret-answer" not in json.dumps(result)


def test_conflicting_recorded_stop_reasons_are_shown_without_reconciliation(
    repo, recording, capsys
):
    data = json.loads(recording.read_bytes())
    data["gate"]["stop_reason"] = "evidence_gate_pass"
    recording.write_text(json.dumps(data), encoding="utf-8")
    result = inspect(repo, recording, capsys)
    assert "conflicting_recorded_stop_reasons" in result["data"]["missing_evidence"]
    assert result["data"]["recorded_stop_reason"] == "evidence_budget_exhausted"


def test_source_selector_requires_exactly_one_input(repo, capsys):
    result = inspect(repo, ARTIFACT, capsys, "--database", "not-used.sqlite")
    assert result["exit_code"] == 2


def test_budget_blocks_oversized_input(repo, recording, capsys, monkeypatch):
    monkeypatch.setattr(studyctl_recording, "MAX_RECORDING_BYTES", 10)
    assert inspect(repo, recording, capsys)["status"] == "BLOCKED"
