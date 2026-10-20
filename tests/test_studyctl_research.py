"""Offline inspection of real repository records; no product writers during inspect."""

from dataclasses import replace
import json
from pathlib import Path
import sqlite3

import pytest

from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.web_lookup_repository import WebLookupRepository
from src.web.research.trace import append_research_trace
from tests.test_research_memory import _run
from tests.test_studyctl import invoke, repo as repo
from tools import studyctl_research


@pytest.fixture
def snapshot(tmp_path):
    run = replace(_run(""), id="inspect-run", stop_reason="evidence_gate_pass")
    evidence_id = run.research_context["claim_engine"]["evidence"][0]["evidence_id"]
    from src.web.research.state import load_claim_engine_state

    state = load_claim_engine_state(
        run.research_context, known_evidence_ids=[evidence_id]
    ).state
    assert state is not None
    for event_type, references in (
        ("search_completed", {}),
        ("read_completed", {"evidence_id": evidence_id}),
        ("claim_linked", {"claim_id": "c1", "evidence_id": evidence_id}),
        ("gate_evaluated", {"claim_id": "c1"}),
        ("stop_allowed", {}),
    ):
        state = append_research_trace(
            state,
            timestamp="2026-10-21T00:00:00Z",
            run_id=run.id,
            event_type=event_type,
            reason="recorded_fixture_reason",
            known_evidence_ids=[evidence_id],
            **references,
        )
    context = {
        **run.research_context,
        "claim_engine": state.to_dict(),
        "final_answer": "SECRET_FINAL_ANSWER",
    }
    run = replace(run, research_context=context)
    path = tmp_path / "离线研究.sqlite"
    repository = WebLookupRepository(RuntimeDatabase(path))
    repository.create(run)
    return path


def edit(snapshot, change):
    with sqlite3.connect(snapshot) as connection:
        row = connection.execute(
            "SELECT research_context FROM web_lookup_runs"
        ).fetchone()
        context = json.loads(row[0])
        change(context)
        connection.execute(
            "UPDATE web_lookup_runs SET research_context = ?", (json.dumps(context),)
        )


def inspect(repo, snapshot, capsys, *extra):
    return invoke(
        capsys,
        "--repo",
        str(repo),
        "research",
        "inspect",
        "--run",
        "inspect-run",
        "--database",
        str(snapshot),
        *extra,
    )


def test_real_snapshot_is_unchanged_and_recorded_failure_is_not_cli_failure(
    repo, snapshot, capsys
):
    with sqlite3.connect(snapshot) as connection:
        connection.execute(
            "UPDATE web_lookup_runs SET status='failed', stop_reason='providers_failed'"
        )
    before = snapshot.read_bytes()
    files = set(snapshot.parent.iterdir())
    result = inspect(repo, snapshot, capsys)
    assert result["status"] == "PASS" and result["exit_code"] == 0
    assert result["data"]["recorded_status"] == "failed"
    assert result["data"]["recorded_stop_reason"] == "providers_failed"
    assert len(result["data"]["events"]) == 5
    assert set(result["data"]["coverage"].values()) == {"recorded"}
    assert "SECRET_FINAL_ANSWER" not in json.dumps(result)
    assert snapshot.read_bytes() == before and set(snapshot.parent.iterdir()) == files


@pytest.mark.parametrize(
    "event",
    [
        "search_completed",
        "read_completed",
        "claim_linked",
        "gate_evaluated",
        "stop_allowed",
    ],
)
def test_missing_events_never_infer_from_final_answer(repo, snapshot, capsys, event):
    edit(
        snapshot,
        lambda context: context["claim_engine"].update(
            trace=[
                item
                for item in context["claim_engine"]["trace"]
                if item["event_type"] != event
            ]
        ),
    )
    result = inspect(repo, snapshot, capsys)
    assert result["status"] == "PARTIAL" and result["exit_code"] == 3
    assert result["data"]["missing_evidence"]
    assert "SECRET_FINAL_ANSWER" not in json.dumps(result)


@pytest.mark.parametrize(
    "kind", ["absent", "old_schema", "foreign_run", "unknown_evidence"]
)
def test_corrupt_or_foreign_state_is_not_reinterpreted(repo, snapshot, capsys, kind):
    def change(context):
        if kind == "absent":
            context.pop("claim_engine")
        elif kind == "old_schema":
            context["claim_engine"]["schema_version"] = "obsolete"
        elif kind == "foreign_run":
            context["claim_engine"]["trace"][0]["run_id"] = "another-run"
        else:
            context["claim_engine"]["evidence"][0]["evidence_id"] = "foreign-evidence"

    edit(snapshot, change)
    result = inspect(repo, snapshot, capsys)
    assert result["status"] == "PARTIAL" and not result["data"]["events"]
    assert result["data"]["missing_evidence"]


@pytest.mark.parametrize(
    "kind",
    [
        "bad_json",
        "missing_run",
        "bad_database",
        "old_database",
        "oversized",
        "wal",
        "shm",
        "journal",
    ],
)
def test_invalid_snapshot_blocks_without_writes(
    repo, snapshot, capsys, monkeypatch, kind
):
    if kind == "bad_json":
        with sqlite3.connect(snapshot) as connection:
            connection.execute(
                "UPDATE web_lookup_runs SET research_context='secret-invalid-json'"
            )
    elif kind == "missing_run":
        with sqlite3.connect(snapshot) as connection:
            connection.execute("DELETE FROM web_lookup_runs")
    elif kind == "bad_database":
        snapshot.write_bytes(b"secret-invalid-database")
    elif kind == "old_database":
        with sqlite3.connect(snapshot) as connection:
            connection.execute("ALTER TABLE web_lookup_runs RENAME TO obsolete")
    elif kind == "oversized":
        monkeypatch.setattr(studyctl_research, "MAX_DATABASE_BYTES", 12)
    else:
        Path(str(snapshot) + "-" + kind).write_bytes(b"sidecar")
    before = snapshot.read_bytes()
    result = inspect(repo, snapshot, capsys)
    assert result["status"] == "BLOCKED" and result["exit_code"] == 3
    assert "secret-invalid" not in json.dumps(result)
    assert snapshot.read_bytes() == before


def test_missing_database_is_not_created(repo, tmp_path, capsys):
    path = tmp_path / "missing.sqlite"
    assert inspect(repo, path, capsys)["exit_code"] == 3
    assert not path.exists()


def test_directory_is_not_a_snapshot(repo, tmp_path, capsys):
    assert inspect(repo, tmp_path, capsys)["exit_code"] == 3


def test_symlink_cannot_hide_live_database_sidecars(repo, snapshot, capsys):
    alias = snapshot.parent / "alias.sqlite"
    try:
        alias.symlink_to(snapshot)
    except OSError:
        pytest.skip("Windows symlink privilege unavailable")
    Path(str(snapshot) + "-wal").write_bytes(b"live-wal")
    assert inspect(repo, alias, capsys)["status"] == "BLOCKED"


def test_required_source_and_run_are_arguments(repo, capsys):
    result = invoke(capsys, "--repo", str(repo), "research", "inspect")
    assert result["exit_code"] == 2


def test_inspection_does_not_initialize_or_resume(repo, snapshot, capsys, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("product writer invoked")

    monkeypatch.setattr(RuntimeDatabase, "initialize", forbidden)
    monkeypatch.setattr(RuntimeDatabase, "connect", forbidden)
    output = snapshot.parent / "not-created.json"
    result = inspect(repo, snapshot, capsys, "--dry-run", "--output", str(output))
    assert result["exit_code"] == 0 and not output.exists()


def test_unknown_stop_reason_does_not_gain_authority(repo, snapshot, capsys):
    with sqlite3.connect(snapshot) as connection:
        connection.execute("UPDATE web_lookup_runs SET stop_reason='unknown-stop'")
    result = inspect(repo, snapshot, capsys)
    assert result["status"] == "PARTIAL"
    assert not result["data"]["stop_reason_recognized"]
