"""Current-main integration controls; providers are faked, money is never spent."""

import asyncio
import sqlite3
from types import SimpleNamespace

import pytest

from src.infrastructure.sqlite import database as schema
from src.infrastructure.sqlite.spend_ledger import SpendLedger, SpendLedgerConflict
from src.llm_client import chat
from src.llm_spend_guard import experiment_spend, spend_scope
from tests.test_spend_production_wiring import (
    EXPERIMENT,
    _budget,
    _clean as _clean,
    _provider_env,
)


def test_current_main_v24_upgrades_to_v26_without_losing_chat_data(
    tmp_path, monkeypatch
):
    """Start from the real main v24 schema rather than a fabricated v25 baseline."""
    path = tmp_path / "main-v24.db"
    with monkeypatch.context() as patch:
        patch.setattr(
            schema, "MIGRATIONS",
            tuple(item for item in schema.MIGRATIONS if item[0] <= 24),
        )
        schema.RuntimeDatabase(path).initialize()

    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT value FROM runtime_meta WHERE key='schema_version'"
        ).fetchone()[0] == "24"
        assert "attachment_refs" not in {
            row[1] for row in connection.execute("PRAGMA table_info(chat_turns)")
        }
        connection.execute(
            "INSERT INTO chat_threads(id, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ("existing-thread", "active", "2026-10-23", "2026-10-23"),
        )
        connection.execute(
            "INSERT INTO chat_turns("
            "id, thread_id, user_message, assistant_message, status, "
            "created_at, updated_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "existing-turn", "existing-thread",
                "preserve the original question",
                "preserve the original answer", "completed",
                "2026-10-23", "2026-10-23",
            ),
        )

    schema.RuntimeDatabase(path).initialize()
    schema.RuntimeDatabase(path).initialize()  # repeat upgrade must be safe

    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT value FROM runtime_meta WHERE key='schema_version'"
        ).fetchone()[0] == "26"
        assert connection.execute(
            "SELECT version, status FROM runtime_migrations "
            "WHERE version IN (25, 26) ORDER BY version"
        ).fetchall() == [(25, "completed"), (26, "completed")]
        assert connection.execute(
            "SELECT user_message, assistant_message, status, attachment_refs "
            "FROM chat_turns WHERE id = ?", ("existing-turn",)
        ).fetchone() == (
            "preserve the original question",
            "preserve the original answer", "completed", "[]",
        )
        assert connection.execute(
            "SELECT id FROM chat_threads WHERE id = ?", ("existing-thread",)
        ).fetchone() == ("existing-thread",)
        tables = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {"llm_spend_experiments", "llm_spend_reservations"} <= tables

    ledger = SpendLedger(path)
    ledger.ensure_experiment(
        "migration-regression", cap_micros=1_000_000,
        pricing_fingerprint="frozen-pricing", now="2026-10-24",
    )
    args = {
        "request_key": "one-send", "amount_micros": 200_000,
        "purpose": "migration-test", "model": "fake-provider",
        "identity": "existing-thread/existing-turn", "now": "2026-10-24",
    }
    reserved = ledger.reserve("migration-regression", **args)
    assert reserved.remaining_micros == 800_000
    with pytest.raises(SpendLedgerConflict):
        ledger.reserve("migration-regression", **args)


def test_v25_upgrade_failure_rolls_back_and_backup_remains_usable(
    tmp_path, monkeypatch
):
    path = tmp_path / "current-main.db"
    migrations = schema.MIGRATIONS
    with monkeypatch.context() as patch:
        patch.setattr(schema, "MIGRATIONS", tuple(x for x in migrations if x[0] <= 25))
        schema.RuntimeDatabase(path).initialize()
    backup = tmp_path / "before-upgrade.db"
    with sqlite3.connect(path) as source, sqlite3.connect(backup) as destination:
        source.execute("CREATE TABLE integration_marker(value TEXT)")
        source.execute("INSERT INTO integration_marker VALUES('keep-current-main')")
        source.commit()
        source.backup(destination)

    def fail_after_first_table(version, index):
        if version == 26 and index == 0:
            raise RuntimeError("injected ledger migration failure")

    with sqlite3.connect(path) as connection:
        with pytest.raises(RuntimeError, match="injected ledger"):
            schema.apply_migrations(connection, after_statement=fail_after_first_table)
        assert (
            connection.execute(
                "SELECT value FROM runtime_meta WHERE key='schema_version'"
            ).fetchone()[0]
            == "25"
        )
        assert (
            connection.execute(
                "SELECT name FROM sqlite_master WHERE name LIKE 'llm_spend_%'"
            ).fetchall()
            == []
        )
        assert (
            connection.execute("SELECT value FROM integration_marker").fetchone()[0]
            == "keep-current-main"
        )

    schema.RuntimeDatabase(path).initialize()
    with sqlite3.connect(path) as connection:
        assert (
            connection.execute(
                "SELECT value FROM runtime_meta WHERE key='schema_version'"
            ).fetchone()[0]
            == "26"
        )
    with sqlite3.connect(backup) as connection:
        assert (
            connection.execute(
                "SELECT value FROM runtime_meta WHERE key='schema_version'"
            ).fetchone()[0]
            == "25"
        )
        assert (
            connection.execute("SELECT value FROM integration_marker").fetchone()[0]
            == "keep-current-main"
        )
    # Downgrade is explicitly rejected: recover old code from its pre-upgrade
    # backup, never erase submitted reservations by dropping ledger tables.
    with monkeypatch.context() as patch:
        patch.setattr(schema, "SCHEMA_VERSION", 25)
        with pytest.raises(RuntimeError, match="newer than supported"):
            schema.RuntimeDatabase(path).initialize()


@pytest.mark.parametrize("failure", [TimeoutError, asyncio.CancelledError])
def test_submitted_failure_keeps_reservation_and_replay_does_not_resend(
    tmp_path, monkeypatch, failure
):
    path = _budget(monkeypatch, tmp_path)
    _provider_env(monkeypatch)
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        raise failure("injected after submission")

    fake = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    monkeypatch.setattr("src.llm_client.get_client", lambda **_: fake)
    with spend_scope(
        run_id="integration-run", operation_id="integration-op", experiment=EXPERIMENT
    ):
        with pytest.raises((RuntimeError, asyncio.CancelledError)):
            chat(
                [{"role": "user", "content": "offline integration"}],
                provider_profile="deepseek",
                request_key="submitted-once",
                max_tokens=16,
            )
        reserved = experiment_spend(EXPERIMENT)
        assert reserved["calls"] == 1 and reserved["reserved_micros"] > 0
        with pytest.raises(SpendLedgerConflict):
            chat(
                [{"role": "user", "content": "offline integration"}],
                provider_profile="deepseek",
                request_key="submitted-once",
                max_tokens=16,
            )
    assert len(calls) == 1
    assert SpendLedger(path).experiment_spend(EXPERIMENT) == reserved
