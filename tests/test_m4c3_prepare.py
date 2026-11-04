"""Offline preparation must never mutate the shared budget or authorize sending."""

import hashlib
import json
import sqlite3
import sys
from pathlib import Path

import pytest

from tools.m4c3_prepare import build_manifest, ledger_snapshot, main


def test_manifest_preserves_twelve_independent_first_attempts():
    manifest = build_manifest()
    cases = manifest["cases"]
    assert [case["task_id"] for case in cases] == [
        "J01",
        "J02",
        "A01",
        "A02",
        "D01",
        "D02",
        "C01",
        "M01",
        "M02",
        "P01",
        "S01",
        "N01",
    ]
    assert len({case["invocation_key"] for case in cases}) == 12
    for case in cases:
        assert (
            case["prompt_sha256"] == hashlib.sha256(case["prompt"].encode()).hexdigest()
        )
        assert "data-acceptance" not in case["prompt"]
    assert manifest["paid_authorized"] is False
    assert manifest["blocking_gates"]
    assert all(case["offline_budget"]["kind"] == "interactive" for case in cases)
    assert all(case["offline_budget"]["max_tokens"] == 6000 for case in cases)
    frozen = Path(__file__).resolve().parents[1] / "docs/M4C3_PROMPTS_V1.json"
    assert json.loads(frozen.read_text(encoding="utf-8")) == manifest


def test_cli_never_overwrites_prior_batch_evidence(tmp_path, monkeypatch):
    output = tmp_path / "manifest.json"
    output.write_bytes(b"prior evidence")
    monkeypatch.setattr(sys, "argv", ["m4c3_prepare", "--out", str(output)])
    with pytest.raises(FileExistsError):
        main()
    assert output.read_bytes() == b"prior evidence"


def test_cli_does_not_emit_a_report_when_ledger_verification_fails(
    tmp_path, monkeypatch
):
    output = tmp_path / "manifest.json"
    ledger = tmp_path / "missing.db"
    monkeypatch.setattr(
        sys, "argv", ["m4c3_prepare", "--out", str(output), "--ledger", str(ledger)]
    )
    with pytest.raises(sqlite3.OperationalError):
        main()
    assert not output.exists()
    assert not ledger.exists()


def test_missing_ledger_is_not_created(tmp_path):
    missing = tmp_path / "missing.db"
    with pytest.raises(sqlite3.OperationalError):
        ledger_snapshot(missing, "experiment")
    assert not missing.exists()


@pytest.mark.parametrize("cap", [30_000_000, 40_000_000])
def test_read_only_snapshot_includes_wal_and_rejects_widened_cap(tmp_path, cap):
    path = tmp_path / "ledger.db"
    db = sqlite3.connect(path)
    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute(
            "CREATE TABLE llm_spend_experiments (experiment_id TEXT, cap_micros INT)"
        )
        db.execute(
            "CREATE TABLE llm_spend_reservations (experiment_id TEXT, amount_micros INT)"
        )
        db.execute("INSERT INTO llm_spend_experiments VALUES ('experiment', ?)", (cap,))
        db.execute("INSERT INTO llm_spend_reservations VALUES ('experiment', 123456)")
        db.execute("INSERT INTO llm_spend_reservations VALUES ('other', 999999)")
        db.commit()
        before = db.total_changes
        if cap == 30_000_000:
            result = ledger_snapshot(path, "experiment")
            assert result["reserved_micros"] == 123456
            assert result["remaining_micros"] == cap - 123456
            assert result["reservation_count"] == 1
        else:
            with pytest.raises(ValueError, match="cap differs"):
                ledger_snapshot(path, "experiment")
        assert db.total_changes == before
        assert (
            db.execute("SELECT COUNT(*) FROM llm_spend_reservations").fetchone()[0] == 2
        )
    finally:
        db.close()
