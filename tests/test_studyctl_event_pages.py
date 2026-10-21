"""Paged output must never change whole-trace coverage or cross source identity."""

import json
from pathlib import Path
import sqlite3

import pytest

from tests.test_studyctl import invoke, repo as repo
from tests.test_studyctl_research import edit, inspect, snapshot as snapshot
from tools import studyctl_research


def test_walk_pages_preserves_global_coverage_and_input(repo, snapshot, capsys):
    before = snapshot.read_bytes()
    cursor, events = "", []
    for _ in range(3):
        result = inspect(
            repo, snapshot, capsys, "--event-limit", "2", "--event-cursor", cursor
        )
        data = result["data"]
        assert result["status"] == "PASS"
        assert data["coverage_scope"] == "whole_recorded_trace"
        assert set(data["coverage"].values()) == {"recorded"}
        assert data["total_event_count"] == 5 and data["events_returned"] <= 2
        events += data["events"]
        cursor = data["next_event_cursor"]
        if not data["has_more"]:
            assert cursor is None
            break
    assert [event["sequence"] for event in events] == list(range(5))
    assert snapshot.read_bytes() == before


def test_default_caps_large_timeline_without_losing_resume_position(
    repo, snapshot, capsys
):
    def extend(context):
        trace = context["claim_engine"]["trace"]
        trace.extend({**trace[0], "sequence": index} for index in range(5, 65))

    edit(snapshot, extend)
    first = inspect(repo, snapshot, capsys)["data"]
    assert len(first["events"]) == 50 and first["total_event_count"] == 65
    second = inspect(
        repo, snapshot, capsys, "--event-cursor", first["next_event_cursor"]
    )["data"]
    assert len(second["events"]) == 15 and not second["has_more"]
    assert [event["sequence"] for event in first["events"] + second["events"]] == list(
        range(65)
    )


@pytest.mark.parametrize(
    "cursor", ["secret-invalid-cursor", "e30=", "W10=", "a" * 4097]
)
def test_invalid_cursor_is_parameter_error_without_echo(repo, snapshot, capsys, cursor):
    result = inspect(repo, snapshot, capsys, "--event-cursor", cursor)
    assert (
        result["exit_code"] == 2
        and result["errors"][0]["code"] == "invalid_event_cursor"
    )
    assert cursor not in json.dumps(result)


def test_catalog_cursor_cannot_be_used_as_event_cursor(repo, snapshot, capsys):
    cursor = studyctl_research.encode_cursor("a" * 64, "inspect-run")
    assert inspect(repo, snapshot, capsys, "--event-cursor", cursor)["exit_code"] == 2


def test_changed_snapshot_blocks_event_cursor(repo, snapshot, capsys):
    first = inspect(repo, snapshot, capsys, "--event-limit", "1")
    with sqlite3.connect(snapshot) as connection:
        connection.execute("UPDATE web_lookup_runs SET stage='changed'")
    result = inspect(
        repo, snapshot, capsys, "--event-cursor", first["data"]["next_event_cursor"]
    )
    assert result["status"] == "BLOCKED" and result["exit_code"] == 3


def test_cursor_for_other_run_is_blocked(repo, snapshot, capsys):
    data = inspect(repo, snapshot, capsys)["data"]
    cursor = studyctl_research.event_cursor(data["snapshot_sha256"], "another-run", 0)
    assert (
        inspect(repo, snapshot, capsys, "--event-cursor", cursor)["status"] == "BLOCKED"
    )


def test_cursor_with_missing_sequence_cannot_skip_unknown_data(repo, snapshot, capsys):
    data = inspect(repo, snapshot, capsys)["data"]
    cursor = studyctl_research.event_cursor(data["snapshot_sha256"], "inspect-run", 999)
    assert (
        inspect(repo, snapshot, capsys, "--event-cursor", cursor)["status"] == "BLOCKED"
    )


@pytest.mark.parametrize("limit", ["0", "101", "-1", "nan"])
def test_invalid_limit_does_not_open_missing_input(repo, tmp_path, capsys, limit):
    assert (
        inspect(repo, tmp_path / "missing.sqlite", capsys, "--event-limit", limit)[
            "exit_code"
        ]
        == 2
    )


def test_no_trace_is_partial_not_a_complete_empty_success(repo, snapshot, capsys):
    edit(snapshot, lambda context: context["claim_engine"].update(trace=[]))
    result = inspect(repo, snapshot, capsys)
    assert result["status"] == "PARTIAL"
    assert result["data"]["total_event_count"] == 0 and not result["data"]["has_more"]


def test_recorded_summary_cannot_claim_event_pagination(repo, capsys):
    artifact = (
        Path(__file__).resolve().parents[1]
        / "docs/research_quality/B5_ACTIVE_SEARXNG_SMOKE.json"
    )
    result = invoke(
        capsys,
        "--repo",
        str(repo),
        "research",
        "inspect",
        "--artifact",
        str(artifact),
        "--run",
        "b5_active_searxng_smoke",
        "--event-limit",
        "10",
    )
    assert (
        result["exit_code"] == 2
        and result["errors"][0]["code"] == "recording_has_no_timeline"
    )
