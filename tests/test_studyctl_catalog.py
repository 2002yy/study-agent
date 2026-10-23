"""Read-only run discovery with snapshot-bound pagination and no answer bodies."""

import hashlib
import json
import sqlite3

import pytest

from src.domain.runtime_entities import WebLookupRun
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.web_lookup_repository import WebLookupRepository
from tests.test_studyctl import invoke, repo as repo
from tests.test_studyctl_research import snapshot as snapshot
from tools.studyctl_research import encode_cursor


def catalog(repo, snapshot, capsys, *args):
    return invoke(
        capsys,
        "--repo",
        str(repo),
        "research",
        "list",
        "--database",
        str(snapshot),
        *args,
    )


def test_catalog_reads_only_metadata_and_keeps_snapshot_unchanged(
    repo, snapshot, capsys, monkeypatch
):
    with sqlite3.connect(snapshot) as connection:
        connection.execute(
            "UPDATE web_lookup_runs SET research_context='private-invalid-json', query='private-question', source_block='private-answer'"
        )
    before = snapshot.read_bytes()
    files = set(snapshot.parent.iterdir())
    monkeypatch.setattr(
        RuntimeDatabase, "connect", lambda *args: pytest.fail("product writer opened")
    )
    result = catalog(repo, snapshot, capsys)
    assert result["command"] == "research list" and result["exit_code"] == 0
    assert result["data"]["runs"][0]["id"] == "inspect-run"
    assert not result["data"]["has_more"] and result["data"]["next_cursor"] is None
    assert "private-" not in json.dumps(result)
    assert snapshot.read_bytes() == before and set(snapshot.parent.iterdir()) == files


def test_catalog_walks_all_pages_once_in_binary_id_order(repo, snapshot, capsys):
    repository = WebLookupRepository(RuntimeDatabase(snapshot))
    for name in ["Z-run", "a-run", "A-run", "中文-run"]:
        repository.create(WebLookupRun(id=name))
    collected, cursor = [], ""
    digests = set()
    while True:
        result = catalog(repo, snapshot, capsys, "--limit", "2", "--cursor", cursor)
        assert result["exit_code"] == 0
        data = result["data"]
        digests.add(data["snapshot_sha256"])
        collected += [row["id"] for row in data["runs"]]
        if not data["has_more"]:
            assert data["next_cursor"] is None
            break
        cursor = data["next_cursor"]
        assert len(collected) < 6
    assert collected == sorted(["inspect-run", "Z-run", "a-run", "A-run", "中文-run"])
    assert len(digests) == 1


def test_changed_snapshot_rejects_old_cursor(repo, snapshot, capsys):
    repository = WebLookupRepository(RuntimeDatabase(snapshot))
    repository.create(WebLookupRun(id="z-run"))
    first = catalog(repo, snapshot, capsys, "--limit", "1")
    cursor = first["data"]["next_cursor"]
    assert cursor
    repository.create(WebLookupRun(id="another-run"))
    result = catalog(repo, snapshot, capsys, "--cursor", cursor)
    assert result["status"] == "BLOCKED" and result["exit_code"] == 3


@pytest.mark.parametrize(
    "cursor", ["not-base64", "W10=", "e30=", "secret-client-argument", "a" * 2049]
)
def test_invalid_cursor_is_sanitized_argument_error(repo, snapshot, capsys, cursor):
    result = catalog(repo, snapshot, capsys, "--cursor", cursor)
    assert result["exit_code"] == 2 and not result["data"].get("runs")
    assert cursor not in json.dumps(result)


@pytest.mark.parametrize("limit", ["0", "-1", "101", "nan"])
def test_invalid_page_limits_do_not_read_snapshot(repo, tmp_path, capsys, limit):
    result = catalog(repo, tmp_path / "absent.sqlite", capsys, "--limit", limit)
    assert result["exit_code"] == 2


def test_empty_catalog_is_explicit(repo, snapshot, capsys):
    with sqlite3.connect(snapshot) as connection:
        connection.execute("DELETE FROM web_lookup_runs")
    result = catalog(repo, snapshot, capsys)
    assert result["status"] == "PASS" and result["data"]["runs"] == []
    assert not result["data"]["has_more"]


def test_missing_database_argument_is_not_an_implicit_live_database(repo, capsys):
    result = invoke(capsys, "--repo", str(repo), "research", "list")
    assert result["exit_code"] == 2


def test_bad_metadata_is_not_silently_skipped(repo, snapshot, capsys):
    with sqlite3.connect(snapshot) as connection:
        connection.execute("UPDATE web_lookup_runs SET id=''")
    result = catalog(repo, snapshot, capsys)
    assert result["status"] == "BLOCKED"


def test_catalog_dry_run_does_not_write_report(repo, snapshot, capsys):
    output = snapshot.parent / "not-written.json"
    result = catalog(repo, snapshot, capsys, "--dry-run", "--output", str(output))
    assert result["exit_code"] == 0 and not output.exists()


@pytest.mark.parametrize("boundary", ["missing-run", "zzzz-after-last", "INSPECT-RUN"])
def test_unknown_snapshot_cursor_boundary_is_rejected(repo, snapshot, capsys, boundary):
    before = snapshot.read_bytes()
    cursor = encode_cursor(hashlib.sha256(before).hexdigest(), boundary)
    result = catalog(repo, snapshot, capsys, "--cursor", cursor)
    assert result["exit_code"] == 2
    assert result["errors"][0]["code"] == "invalid_catalog_cursor"
    assert not result["data"].get("runs")
    assert snapshot.read_bytes() == before
    assert cursor not in json.dumps(result)
