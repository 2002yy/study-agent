"""CL-M3-S1: the settlement audit (contract §12) as negative controls.

The contract separates two facts: a reservation is how much a run was allowed
to spend and never moves; an observation is what was later learned about that
send and can be corrected exactly once, with evidence. These tests are written
from the contract's own counter-examples - a rewrite of history, a zero that
pretends to be "unknown", a correction that names a different call, an
append-only table that a stray script can edit.

The money invariant is the one that matters most: `experiment_spend()`'s four
numbers must be identical before and after any observation. If a test here ever
fails on that assertion, the audit layer has become a second ledger and the
slice must stop.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from src.application.spend_settlement_adapter import (
    COST_LEDGER_REFUSED,
    COST_UPPER_BOUND_INVALIDATED,
    RESERVED,
    SettlementLedgerAdapter,
)
from src.domain.spend_settlement import (
    COST_BASIS_ESTIMATED,
    COST_BASIS_MEASURED_USAGE,
    SETTLEMENT_FAILED,
    SETTLEMENT_SETTLED,
    SETTLEMENT_UNRESOLVED,
    SettlementEvidenceError,
    evidence_ref,
)
from src.infrastructure.sqlite import database as schema
from src.infrastructure.sqlite.database import RuntimeDatabase, schema_version
from src.infrastructure.sqlite.spend_ledger import SpendLedger
from src.infrastructure.sqlite.spend_settlement import (
    ReservationRow,
    SettlementConflict,
    SettlementIdentityRejected,
    SpendSettlementRepository,
)
from src.llm_spend_guard import reset_spend, spend_identity

NOW = "2026-10-25T00:00:00+00:00"
EXPERIMENT = "settlement-experiment"
OTHER_EXPERIMENT = "settlement-other"
CAP_MICROS = 10_000_000

REPO_ROOT = Path(__file__).resolve().parents[1]


# -- fixtures -------------------------------------------------------------------


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "runtime.sqlite"
    RuntimeDatabase(path).initialize()
    return path


@pytest.fixture
def ledger(database):
    instance = SpendLedger(database)
    instance.ensure_experiment(
        EXPERIMENT, cap_micros=CAP_MICROS, pricing_fingerprint="pricing-v1", now=NOW
    )
    return instance


@pytest.fixture
def repository(database):
    return SpendSettlementRepository(database)


@pytest.fixture(autouse=True)
def _clean_spend(monkeypatch):
    reset_spend()
    for name in (
        "LLM_SPEND_CAP_CNY",
        "LLM_SPEND_INPUT_CNY_PER_MTOK",
        "LLM_SPEND_OUTPUT_CNY_PER_MTOK",
        "LLM_SPEND_DEFAULT_MAX_TOKENS",
        "LLM_SPEND_EXPERIMENT_ID",
        "LLM_SPEND_EXPERIMENT_CAP_CNY",
        "LLM_SPEND_LEDGER_DB",
        "LLM_EXPERIMENT_ALLOWED_MODELS",
    ):
        monkeypatch.delenv(name, raising=False)
    yield
    reset_spend()


def _reserve(ledger, key="key-1", amount=500, *, experiment=EXPERIMENT):
    return ledger.reserve(
        experiment,
        request_key=key,
        amount_micros=amount,
        purpose="chat:deep_planner",
        model="deepseek-chat",
        identity="run=run1 op=op1 inv=1",
        now=NOW,
    )


def _evidence(key="key-1", receipt="r1", kind="offline_fixture"):
    return evidence_ref(kind=kind, request_key=key, receipt=receipt)


def _settle(repository, *, key="key-1", experiment=EXPERIMENT, **overrides):
    arguments = {
        "outcome": SETTLEMENT_UNRESOLVED,
        "observed_at": NOW,
    }
    arguments.update(overrides)
    return repository.settle(experiment, key, **arguments)


def _rows(path: Path, query: str, parameters: tuple = ()) -> list[sqlite3.Row]:
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        return connection.execute(query, parameters).fetchall()


def _v29_database(path: Path) -> None:
    """Build a database that stops at 29, without touching the real constants."""

    migrations = schema.MIGRATIONS
    version = schema.SCHEMA_VERSION
    schema.MIGRATIONS = tuple(item for item in migrations if item[0] <= 29)
    schema.SCHEMA_VERSION = 29
    try:
        RuntimeDatabase(path).initialize()
    finally:
        schema.MIGRATIONS = migrations
        schema.SCHEMA_VERSION = version


# -- migration 30 ----------------------------------------------------------------


def test_a_fresh_database_reaches_schema_30_with_the_audit_table(database):
    with sqlite3.connect(database) as connection:
        assert schema_version(connection) == 30
        names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type IN ('table', 'trigger') "
                "AND name LIKE 'llm_spend_settlement%'"
            )
        }
    assert "llm_spend_settlements" in names
    assert "llm_spend_settlement_epoch" in names
    assert "llm_spend_settlements_append_only_update" in names
    assert "llm_spend_settlements_append_only_delete" in names


def test_upgrading_v29_keeps_reservations_and_excludes_them_from_the_debt_scan(
    tmp_path,
):
    path = tmp_path / "legacy.sqlite"
    _v29_database(path)
    ledger = SpendLedger(path)
    ledger.ensure_experiment(
        EXPERIMENT, cap_micros=CAP_MICROS, pricing_fingerprint="pricing-v1", now=NOW
    )
    reservation = _reserve(ledger, key="historical")
    historical_id = _rows(
        path,
        "SELECT reservation_id FROM llm_spend_reservations WHERE request_key = ?",
        ("historical",),
    )[0]["reservation_id"]

    RuntimeDatabase(path).initialize()

    repository = SpendSettlementRepository(path)
    # The row existed before the audit layer did. It is not debt.
    assert repository.unwritten() == ()
    assert repository.current(EXPERIMENT, "historical") is None
    # The money is untouched by the upgrade.
    assert ledger.experiment_spend(EXPERIMENT)["reserved_micros"] == 500
    assert reservation.request_key == "historical"
    epoch = _rows(
        path, "SELECT audited_from_reservation_id FROM llm_spend_settlement_epoch"
    )[0][0]
    assert epoch == historical_id


def test_a_new_reservation_after_the_upgrade_is_debt(tmp_path):
    path = tmp_path / "legacy.sqlite"
    _v29_database(path)
    ledger = SpendLedger(path)
    ledger.ensure_experiment(
        EXPERIMENT, cap_micros=CAP_MICROS, pricing_fingerprint="pricing-v1", now=NOW
    )
    _reserve(ledger, key="historical")
    RuntimeDatabase(path).initialize()

    _reserve(ledger, key="after-upgrade")

    repository = SpendSettlementRepository(path)
    assert repository.unwritten() == ((EXPERIMENT, "after-upgrade"),)


def test_initialising_twice_is_idempotent(database):
    RuntimeDatabase(database).initialize()
    RuntimeDatabase(database).initialize()
    with sqlite3.connect(database) as connection:
        assert schema_version(connection) == 30
        assert connection.execute(
            "SELECT COUNT(*) FROM llm_spend_settlement_epoch"
        ).fetchone()[0] == 1


def test_a_failed_migration_30_leaves_no_audit_table_behind(tmp_path):
    path = tmp_path / "interrupted.sqlite"
    _v29_database(path)

    def fail_on_second_statement(version: int, index: int) -> None:
        if version == 30 and index == 1:
            raise RuntimeError("interrupted")

    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        with pytest.raises(RuntimeError, match="interrupted"):
            schema.apply_migrations(connection, after_statement=fail_on_second_statement)
        assert schema_version(connection) == 29
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='llm_spend_settlements'"
        ).fetchone() is None

    RuntimeDatabase(path).initialize()
    with sqlite3.connect(path) as connection:
        assert schema_version(connection) == 30


def test_the_write_connection_enforces_the_foreign_key(database):
    """The FK is a storage fact, not a repository convention."""

    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            connection.execute(
                "INSERT INTO llm_spend_settlements("
                "experiment_id, request_key, revision, outcome, evidence_ref, observed_at"
                ") VALUES ('missing', 'missing', 1, 'unresolved', '', ?)",
                (NOW,),
            )


# -- cost semantics: unknown is not zero ------------------------------------------


def test_an_unknown_outcome_is_recorded_as_null_not_zero(ledger, repository):
    _reserve(ledger)
    record = _settle(repository)
    assert record.outcome == SETTLEMENT_UNRESOLVED
    assert record.cost_micros is None
    assert record.cost_basis is None
    stored = _rows(Path(repository.database_path), "SELECT * FROM llm_spend_settlements")[0]
    assert stored["cost_micros"] is None and stored["cost_basis"] is None


def test_zero_cost_is_a_fact_and_needs_a_basis(ledger, repository):
    _reserve(ledger)
    record = _settle(
        repository,
        outcome=SETTLEMENT_UNRESOLVED,
        cost_micros=0,
        cost_basis=COST_BASIS_ESTIMATED,
    )
    assert record.cost_micros == 0
    assert record.cost_basis == COST_BASIS_ESTIMATED


@pytest.mark.parametrize(
    ("cost", "basis"),
    [
        pytest.param(400, None, id="amount-without-basis"),
        pytest.param(None, COST_BASIS_ESTIMATED, id="basis-without-amount"),
    ],
)
def test_cost_and_basis_are_recorded_together(ledger, repository, cost, basis):
    _reserve(ledger)
    with pytest.raises(ValueError, match="invalid_cost_basis"):
        _settle(
            repository,
            outcome=SETTLEMENT_UNRESOLVED,
            cost_micros=cost,
            cost_basis=basis,
        )
    assert repository.history(EXPERIMENT, "key-1") == ()


@pytest.mark.parametrize(
    "cost",
    [
        pytest.param(-1, id="negative"),
        pytest.param(True, id="bool"),
        pytest.param(1.5, id="float"),
        pytest.param("400", id="string"),
    ],
)
def test_an_impossible_cost_is_refused(ledger, repository, cost):
    _reserve(ledger)
    with pytest.raises(ValueError, match="invalid_cost_micros"):
        _settle(
            repository,
            outcome=SETTLEMENT_UNRESOLVED,
            cost_micros=cost,
            cost_basis=COST_BASIS_ESTIMATED,
        )
    assert repository.history(EXPERIMENT, "key-1") == ()


# -- evidence must name this send --------------------------------------------------


def test_a_settled_observation_without_evidence_is_refused(ledger, repository):
    _reserve(ledger)
    with pytest.raises(SettlementEvidenceError) as refused:
        _settle(repository, outcome=SETTLEMENT_SETTLED, cost_micros=400,
                cost_basis=COST_BASIS_ESTIMATED)
    assert refused.value.reason == "evidence_missing"
    assert repository.history(EXPERIMENT, "key-1") == ()


def test_evidence_for_another_request_is_refused(ledger, repository):
    _reserve(ledger)
    with pytest.raises(SettlementEvidenceError) as refused:
        _settle(
            repository,
            outcome=SETTLEMENT_SETTLED,
            cost_micros=400,
            cost_basis=COST_BASIS_ESTIMATED,
            evidence_ref=_evidence(key="another-key"),
        )
    assert refused.value.reason == "evidence_not_bound_to_request"
    assert repository.history(EXPERIMENT, "key-1") == ()


@pytest.mark.parametrize(
    ("reference", "reason"),
    [
        pytest.param("provider_result:key-1#", "evidence_receipt_missing", id="no-receipt"),
        pytest.param("because-i-said-so", "evidence_kind_unknown", id="free-form"),
        pytest.param("trust_me:key-1#r1", "evidence_kind_unknown", id="unknown-kind"),
        pytest.param("provider_result:key-1#has space", "evidence_receipt_malformed",
                     id="receipt-with-space"),
    ],
)
def test_free_form_evidence_is_not_evidence(ledger, repository, reference, reason):
    _reserve(ledger)
    with pytest.raises(SettlementEvidenceError) as refused:
        _settle(
            repository,
            outcome=SETTLEMENT_SETTLED,
            cost_micros=400,
            cost_basis=COST_BASIS_ESTIMATED,
            evidence_ref=reference,
        )
    assert refused.value.reason == reason
    assert repository.history(EXPERIMENT, "key-1") == ()


def test_an_unresolved_observation_may_carry_only_this_sends_receipt(ledger, repository):
    _reserve(ledger)
    with pytest.raises(SettlementEvidenceError):
        _settle(repository, evidence_ref=_evidence(key="another-key"))


# -- idempotency and the single correction -----------------------------------------


def test_replaying_the_same_observation_adds_no_revision(ledger, repository):
    _reserve(ledger)
    first = _settle(repository)
    replay = _settle(repository, observed_at="2026-10-25T00:00:05+00:00")
    assert replay.revision == first.revision == 1
    assert replay.observed_at == first.observed_at
    assert len(repository.history(EXPERIMENT, "key-1")) == 1


def test_the_single_allowed_correction_appends_revision_two(ledger, repository):
    _reserve(ledger)
    _settle(repository)
    corrected = _settle(
        repository,
        outcome=SETTLEMENT_SETTLED,
        cost_micros=400,
        cost_basis=COST_BASIS_ESTIMATED,
        evidence_ref=_evidence(),
    )
    assert corrected.revision == 2
    history = repository.history(EXPERIMENT, "key-1")
    assert [record.outcome for record in history] == [
        SETTLEMENT_UNRESOLVED,
        SETTLEMENT_SETTLED,
    ]
    assert repository.current(EXPERIMENT, "key-1").settled is True


def test_settled_cannot_be_downgraded_to_unresolved(ledger, repository):
    _reserve(ledger)
    _settle(repository, outcome=SETTLEMENT_SETTLED, cost_micros=400,
            cost_basis=COST_BASIS_ESTIMATED, evidence_ref=_evidence())
    with pytest.raises(SettlementConflict):
        _settle(repository)
    assert len(repository.history(EXPERIMENT, "key-1")) == 1


def test_settled_cannot_be_corrected_again_with_measured_usage(ledger, repository):
    _reserve(ledger)
    _settle(repository, outcome=SETTLEMENT_SETTLED, cost_micros=400,
            cost_basis=COST_BASIS_ESTIMATED, evidence_ref=_evidence())
    with pytest.raises(SettlementConflict):
        _settle(
            repository,
            outcome=SETTLEMENT_SETTLED,
            cost_micros=450,
            cost_basis=COST_BASIS_MEASURED_USAGE,
            evidence_ref=_evidence(receipt="r2"),
        )
    assert len(repository.history(EXPERIMENT, "key-1")) == 1


def test_unresolved_cannot_become_failed(ledger, repository):
    """``failed`` needs a failure receipt, and the transition is still refused.

    A failure receipt is checked first: the observation is only well-formed with
    one. Even with it, ``unresolved -> failed`` is not a permitted correction.
    """

    _reserve(ledger)
    _settle(repository)
    with pytest.raises(SettlementConflict):
        _settle(
            repository,
            outcome=SETTLEMENT_FAILED,
            evidence_ref=_evidence(receipt="provider-error"),
        )
    assert len(repository.history(EXPERIMENT, "key-1")) == 1


def test_failed_requires_a_failure_receipt(ledger, repository):
    _reserve(ledger)
    with pytest.raises(SettlementEvidenceError) as refused:
        _settle(repository, outcome=SETTLEMENT_FAILED)
    assert refused.value.reason == "evidence_missing"
    assert repository.history(EXPERIMENT, "key-1") == ()


def test_failed_is_final(ledger, repository):
    _reserve(ledger)
    _settle(
        repository,
        outcome=SETTLEMENT_FAILED,
        evidence_ref=_evidence(receipt="provider-error"),
    )
    with pytest.raises(SettlementConflict):
        _settle(
            repository,
            outcome=SETTLEMENT_SETTLED,
            cost_micros=400,
            cost_basis=COST_BASIS_ESTIMATED,
            evidence_ref=_evidence(),
        )
    assert len(repository.history(EXPERIMENT, "key-1")) == 1


# -- identity ----------------------------------------------------------------------


def test_a_settlement_without_a_reservation_is_refused_and_writes_nothing(repository):
    with pytest.raises(SettlementIdentityRejected) as refused:
        _settle(repository)
    assert refused.value.reason == "reservation_not_found"
    assert repository.history(EXPERIMENT, "key-1") == ()


def test_a_settlement_under_another_experiment_is_refused(ledger, repository):
    _reserve(ledger)
    with pytest.raises(SettlementIdentityRejected) as refused:
        _settle(repository, experiment=OTHER_EXPERIMENT)
    assert refused.value.reason == "reservation_not_found"
    assert repository.history(OTHER_EXPERIMENT, "key-1") == ()


# -- append-only is a storage fact -------------------------------------------------


def test_a_direct_update_is_refused_by_the_store(ledger, repository, database):
    _reserve(ledger)
    _settle(repository)
    with sqlite3.connect(database) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "UPDATE llm_spend_settlements SET outcome = 'settled' "
                "WHERE request_key = 'key-1'"
            )


def test_a_direct_delete_is_refused_by_the_store(ledger, repository, database):
    _reserve(ledger)
    _settle(repository)
    with sqlite3.connect(database) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "DELETE FROM llm_spend_settlements WHERE request_key = 'key-1'"
            )


# -- concurrency -------------------------------------------------------------------


def _in_threads(calls):
    barrier = threading.Barrier(len(calls))
    results: list[tuple[str, object]] = []
    lock = threading.Lock()

    def run(call):
        barrier.wait()
        try:
            value = call()
            outcome: tuple[str, object] = ("ok", value)
        except Exception as exc:  # noqa: BLE001 - the test inspects the type
            outcome = ("error", exc)
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=run, args=(call,)) for call in calls]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    return results


def test_identical_concurrent_corrections_add_one_revision_and_both_succeed(
    ledger, database
):
    repository = SpendSettlementRepository(database)
    _reserve(ledger)
    _settle(repository)

    def settle_copy():
        return SpendSettlementRepository(database).settle(
            EXPERIMENT,
            "key-1",
            outcome=SETTLEMENT_SETTLED,
            cost_micros=400,
            cost_basis=COST_BASIS_ESTIMATED,
            evidence_ref=_evidence(),
            observed_at=NOW,
        )

    results = _in_threads([settle_copy, settle_copy])

    assert [status for status, _ in results] == ["ok", "ok"]
    history = repository.history(EXPERIMENT, "key-1")
    assert len(history) == 2
    assert [record.revision for record in history] == [1, 2]


def test_conflicting_concurrent_corrections_have_exactly_one_winner(ledger, database):
    repository = SpendSettlementRepository(database)
    _reserve(ledger)
    _settle(repository)

    def settle(receipt: str):
        return lambda: SpendSettlementRepository(database).settle(
            EXPERIMENT,
            "key-1",
            outcome=SETTLEMENT_SETTLED,
            cost_micros=400,
            cost_basis=COST_BASIS_ESTIMATED,
            evidence_ref=_evidence(receipt=receipt),
            observed_at=NOW,
        )

    results = _in_threads([settle("winner-a"), settle("winner-b")])

    statuses = sorted(status for status, _ in results)
    assert statuses == ["error", "ok"]
    error = next(value for status, value in results if status == "error")
    assert isinstance(error, SettlementConflict)
    history = repository.history(EXPERIMENT, "key-1")
    assert len(history) == 2
    assert history[-1].revision == 2


# -- money does not move -----------------------------------------------------------


def test_settlement_does_not_move_the_ledgers_four_numbers(ledger, repository):
    _reserve(ledger)
    before = ledger.experiment_spend(EXPERIMENT)
    _settle(repository)
    _settle(
        repository,
        outcome=SETTLEMENT_SETTLED,
        cost_micros=900,
        cost_basis=COST_BASIS_ESTIMATED,
        evidence_ref=_evidence(),
    )
    after = ledger.experiment_spend(EXPERIMENT)
    assert after == before


def test_settlement_does_not_change_the_reserved_row(ledger, repository, database):
    _reserve(ledger)
    def row():
        return dict(_rows(database, "SELECT * FROM llm_spend_reservations")[0])

    before = row()
    _settle(repository, outcome=SETTLEMENT_SETTLED, cost_micros=9999,
            cost_basis=COST_BASIS_ESTIMATED, evidence_ref=_evidence())
    assert row() == before


# -- the debt scan ---------------------------------------------------------------


def test_a_reservation_without_observation_is_reported_as_unwritten(ledger, repository):
    _reserve(ledger, key="key-1")
    _reserve(ledger, key="key-2")
    _settle(repository, key="key-1")
    assert repository.unwritten() == ((EXPERIMENT, "key-2"),)


def test_a_real_process_crash_between_reserve_and_observation_is_found_on_restart(
    tmp_path,
):
    """The reservation survives the process; the missing observation is the debt."""

    path = tmp_path / "crash.sqlite"
    RuntimeDatabase(path).initialize()
    script = tmp_path / "crash_worker.py"
    script.write_text(
        "import os\n"
        "from src.infrastructure.sqlite.spend_ledger import SpendLedger\n"
        f"ledger = SpendLedger(r'{path}')\n"
        "ledger.ensure_experiment('crash-exp', cap_micros=1000000,\n"
        "                         pricing_fingerprint='p', now='2026-10-25T00:00:00+00:00')\n"
        "ledger.reserve('crash-exp', request_key='crash-key', amount_micros=700,\n"
        "               purpose='c', model='m', identity='run=1',\n"
        "               now='2026-10-25T00:00:00+00:00')\n"
        "os._exit(7)\n",
        encoding="utf-8",
    )
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(REPO_ROOT)

    completed = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(REPO_ROOT),
        env=environment,
        capture_output=True,
        timeout=120,
    )

    assert completed.returncode == 7
    repository = SpendSettlementRepository(path)
    assert repository.unwritten() == (("crash-exp", "crash-key"),)
    assert repository.history("crash-exp", "crash-key") == ()


# -- the overrun is an observation, never a rewrite ---------------------------------


def test_an_observation_above_its_reservation_is_an_overrun(ledger, repository):
    _reserve(ledger, amount=500)
    _settle(
        repository,
        outcome=SETTLEMENT_SETTLED,
        cost_micros=900,
        cost_basis=COST_BASIS_MEASURED_USAGE,
        evidence_ref=_evidence(kind="provider_result"),
    )
    overruns = repository.overruns(EXPERIMENT)
    assert overruns == (
        ReservationRow(experiment_id=EXPERIMENT, request_key="key-1", amount_micros=500),
    )


def test_an_overrun_does_not_rewrite_the_reservation_or_the_cap(ledger, repository):
    _reserve(ledger, amount=500)
    before = ledger.experiment_spend(EXPERIMENT)
    _settle(
        repository,
        outcome=SETTLEMENT_SETTLED,
        cost_micros=900,
        cost_basis=COST_BASIS_MEASURED_USAGE,
        evidence_ref=_evidence(kind="provider_result"),
    )
    assert ledger.experiment_spend(EXPERIMENT) == before
    assert before["reserved_micros"] == 500
    assert before["cap_micros"] == CAP_MICROS


def test_a_cost_within_its_reservation_is_not_an_overrun(ledger, repository):
    _reserve(ledger, amount=1000)
    _settle(
        repository,
        outcome=SETTLEMENT_SETTLED,
        cost_micros=1000,
        cost_basis=COST_BASIS_ESTIMATED,
        evidence_ref=_evidence(),
    )
    assert repository.overruns(EXPERIMENT) == ()


def test_a_failed_call_whose_cost_exceeds_the_reservation_is_an_overrun(
    ledger, repository
):
    """The P1: whether the call succeeded is not the question the bound asks.

    A failed call with a known cost is money spent. Filtering ``overruns()`` by
    ``outcome = 'settled'`` let this exact shape record 900 micro-CNY against a
    500 micro-CNY reservation and leave the experiment free to reserve again.
    """

    _reserve(ledger, amount=500)
    before = ledger.experiment_spend(EXPERIMENT)
    _settle(
        repository,
        outcome=SETTLEMENT_FAILED,
        cost_micros=900,
        cost_basis=COST_BASIS_MEASURED_USAGE,
        evidence_ref=_evidence(kind="provider_result", receipt="failure-receipt"),
    )

    assert repository.overruns(EXPERIMENT) == (
        ReservationRow(experiment_id=EXPERIMENT, request_key="key-1", amount_micros=500),
    )
    # The observation is a fact about the send, not a correction to the ledger.
    assert ledger.experiment_spend(EXPERIMENT) == before


def test_a_failed_call_within_its_reservation_is_not_an_overrun(ledger, repository):
    _reserve(ledger, amount=1000)
    _settle(
        repository,
        outcome=SETTLEMENT_FAILED,
        cost_micros=900,
        cost_basis=COST_BASIS_MEASURED_USAGE,
        evidence_ref=_evidence(kind="provider_result", receipt="failure-receipt"),
    )
    assert repository.overruns(EXPERIMENT) == ()


def test_an_unresolved_cost_above_the_reservation_also_blocks(ledger, repository):
    """Outcome-independence is the fix, not a special case for ``failed``.

    An ``unresolved`` cost is normally NULL. When a caller does record an amount,
    it is a recorded amount: the same rule applies, because making the guard
    depend on the label is what produced the P1 in the first place.
    """

    _reserve(ledger, amount=500)
    _settle(
        repository,
        outcome=SETTLEMENT_UNRESOLVED,
        cost_micros=900,
        cost_basis=COST_BASIS_MEASURED_USAGE,
    )
    assert repository.overruns(EXPERIMENT) == (
        ReservationRow(experiment_id=EXPERIMENT, request_key="key-1", amount_micros=500),
    )


def test_an_unknown_cost_is_not_an_overrun(ledger, repository):
    """Unknown is not infinite: NULL stays out of the comparison."""

    _reserve(ledger, amount=500)
    _settle(repository)
    assert repository.overruns(EXPERIMENT) == ()


# -- the adapter: reserve through the ledger, settle into the audit -----------------


def _configure(monkeypatch, database: Path, *, cap: str = "10") -> None:
    monkeypatch.setenv("LLM_SPEND_LEDGER_DB", str(database.resolve()))
    monkeypatch.setenv("LLM_SPEND_EXPERIMENT_ID", EXPERIMENT)
    monkeypatch.setenv("LLM_SPEND_EXPERIMENT_CAP_CNY", cap)
    monkeypatch.setenv("LLM_SPEND_INPUT_CNY_PER_MTOK", "1")
    monkeypatch.setenv("LLM_SPEND_OUTPUT_CNY_PER_MTOK", "1")


def _identity(experiment: str = EXPERIMENT):
    return spend_identity(
        run_id="run1", operation_id="op1", invocation="1", experiment=experiment
    )


def _reserve_through(adapter, key="key-1", *, prompt_chars=1_000, max_tokens=100):
    return adapter.reserve(
        key, model="deepseek-chat", max_output_tokens=max_tokens,
        prompt_chars=prompt_chars,
    )


def test_a_missing_budget_is_refused_rather_than_treated_as_free(database):
    adapter = SettlementLedgerAdapter(SpendSettlementRepository(database))
    assert _reserve_through(adapter) == COST_LEDGER_REFUSED
    assert _rows(database, "SELECT * FROM llm_spend_reservations") == []


def test_a_real_reservation_is_persisted_once(monkeypatch, database):
    _configure(monkeypatch, database)
    adapter = SettlementLedgerAdapter(SpendSettlementRepository(database))
    with _identity():
        assert _reserve_through(adapter) == RESERVED
        assert _reserve_through(adapter) == COST_LEDGER_REFUSED
    rows = _rows(database, "SELECT * FROM llm_spend_reservations")
    assert [row["request_key"] for row in rows] == ["key-1"]
    assert rows[0]["amount_micros"] > 0


def test_settling_through_the_adapter_appends_the_observation(monkeypatch, database):
    _configure(monkeypatch, database)
    repository = SpendSettlementRepository(database)
    adapter = SettlementLedgerAdapter(repository)
    with _identity():
        assert _reserve_through(adapter) == RESERVED
        adapter.settle(
            "key-1",
            outcome=SETTLEMENT_SETTLED,
            cost_micros=400,
            cost_basis=COST_BASIS_ESTIMATED,
            evidence_ref=_evidence(),
        )
    record = repository.current(EXPERIMENT, "key-1")
    assert record is not None and record.outcome == SETTLEMENT_SETTLED


def test_settling_an_unknown_request_through_the_adapter_is_refused(database):
    adapter = SettlementLedgerAdapter(SpendSettlementRepository(database))
    with pytest.raises(SettlementIdentityRejected):
        adapter.settle("never-reserved", outcome=SETTLEMENT_UNRESOLVED, cost_micros=None)


def test_an_ambiguous_request_key_is_refused(database):
    ledger = SpendLedger(database)
    for experiment in (EXPERIMENT, OTHER_EXPERIMENT):
        ledger.ensure_experiment(
            experiment, cap_micros=CAP_MICROS, pricing_fingerprint="pricing-v1", now=NOW
        )
        ledger.reserve(
            experiment,
            request_key="shared-key",
            amount_micros=100,
            purpose="c",
            model="m",
            identity="run=1",
            now=NOW,
        )
    adapter = SettlementLedgerAdapter(SpendSettlementRepository(database))
    with pytest.raises(SettlementIdentityRejected) as refused:
        adapter.settle("shared-key", outcome=SETTLEMENT_UNRESOLVED, cost_micros=None)
    assert refused.value.reason == "ambiguous_request_key"


def test_an_overrun_blocks_further_reservations(monkeypatch, database):
    _configure(monkeypatch, database)
    repository = SpendSettlementRepository(database)
    adapter = SettlementLedgerAdapter(repository)
    with _identity():
        assert _reserve_through(adapter) == RESERVED
        adapter.settle(
            "key-1",
            outcome=SETTLEMENT_SETTLED,
            cost_micros=10_000_000,
            cost_basis=COST_BASIS_MEASURED_USAGE,
            evidence_ref=_evidence(kind="provider_result"),
        )
        assert _reserve_through(adapter, key="key-2") == COST_UPPER_BOUND_INVALIDATED
    keys = [row["request_key"] for row in _rows(database, "SELECT * FROM llm_spend_reservations")]
    assert keys == ["key-1"]


def test_an_overrun_from_a_failed_call_blocks_further_reservations(monkeypatch, database):
    """The P1 at the point where it matters: the next reserve is refused."""

    _configure(monkeypatch, database)
    repository = SpendSettlementRepository(database)
    adapter = SettlementLedgerAdapter(repository)
    with _identity():
        assert _reserve_through(adapter) == RESERVED
        adapter.settle(
            "key-1",
            outcome=SETTLEMENT_FAILED,
            cost_micros=10_000_000,
            cost_basis=COST_BASIS_MEASURED_USAGE,
            evidence_ref=_evidence(kind="provider_result", receipt="failure-receipt"),
        )
        assert _reserve_through(adapter, key="key-2") == COST_UPPER_BOUND_INVALIDATED
    keys = [row["request_key"] for row in _rows(database, "SELECT * FROM llm_spend_reservations")]
    assert keys == ["key-1"]


def test_a_cost_without_a_basis_is_refused_before_the_store(monkeypatch, database):
    _configure(monkeypatch, database)
    adapter = SettlementLedgerAdapter(SpendSettlementRepository(database))
    with _identity():
        assert _reserve_through(adapter) == RESERVED
        with pytest.raises(ValueError, match="invalid_cost_basis"):
            adapter.settle("key-1", outcome=SETTLEMENT_UNRESOLVED, cost_micros=10)
