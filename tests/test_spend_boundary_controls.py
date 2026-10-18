"""The last three gaps of the spend ledger, each with its own control.

1. an explicit request key is *not* authorization: only work declared as part of
   the experiment may spend from it (this is what let a bare ``call_id`` from the
   research model gateway reserve the experiment budget);
2. a busy SQLite database must reach the retry loop and succeed once the lock is
   released - not be reported as an unavailable ledger;
3. a budget stop is its own outcome (``budget_exhausted``), not a model failure.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.infrastructure.sqlite.database import RuntimeDatabase
from src.infrastructure.sqlite.spend_ledger import (
    MICROS_PER_CNY,
    SpendLedger,
    SpendLedgerUnavailable,
)
from src.llm_spend_guard import (
    SpendIdentity,
    experiment_spend,
    reset_spend,
    reserve_call,
    spend_identity,
    spend_scope,
)
from src.web.research.model_gateway import ResearchModelGateway

EXPERIMENT = "boundary-experiment"


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    reset_spend()
    for name in (
        "LLM_SPEND_CAP_CNY",
        "LLM_SPEND_INPUT_CNY_PER_MTOK",
        "LLM_SPEND_OUTPUT_CNY_PER_MTOK",
        "LLM_SPEND_DEFAULT_MAX_TOKENS",
        "LLM_SPEND_EXPERIMENT_ID",
        "LLM_SPEND_EXPERIMENT_CAP_CNY",
        "LLM_SPEND_LEDGER_DB",
    ):
        monkeypatch.delenv(name, raising=False)
    yield
    reset_spend()


def _provider_env(monkeypatch) -> None:
    """Resolvable provider settings; the client itself is always injected."""

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("MODEL_FLASH_NAME", "fake-flash")
    monkeypatch.setenv("MODEL_PRO_NAME", "fake-pro")


def _budget(monkeypatch, tmp_path: Path, *, cap="10", experiment=EXPERIMENT) -> Path:
    database = tmp_path / f"{experiment}.db"
    RuntimeDatabase(database).initialize()
    monkeypatch.setenv("LLM_SPEND_LEDGER_DB", str(database.resolve()))
    monkeypatch.setenv("LLM_SPEND_EXPERIMENT_ID", experiment)
    monkeypatch.setenv("LLM_SPEND_EXPERIMENT_CAP_CNY", cap)
    monkeypatch.setenv("LLM_SPEND_INPUT_CNY_PER_MTOK", "1")
    monkeypatch.setenv("LLM_SPEND_OUTPUT_CNY_PER_MTOK", "1")
    return database


class _RecordingClient:
    """A provider client that records every request instead of sending one."""

    def __init__(self) -> None:
        self.requests: list[dict] = []

    def with_options(self, **_kwargs):
        return self

    @property
    def chat(self):
        return SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content='{"ok": true}'), finish_reason="stop"
                )
            ],
            usage=None,
        )


def _call_gateway(gateway: ResearchModelGateway):
    return gateway.complete_structured(
        logical_call_id="lead-discovery:1",
        purpose="lead_discovery",
        messages=[{"role": "user", "content": "question"}],
        audit_payload={"query": "question"},
        response_schema_version="lead-discovery-v1",
        parse=lambda raw: raw,
    )


# -- 1. authorization --------------------------------------------------------
def test_a_structured_call_without_declared_work_sends_nothing(monkeypatch, tmp_path):
    """Blocker 1: a bare call id must not be able to spend the experiment budget."""

    _budget(monkeypatch, tmp_path)
    _provider_env(monkeypatch)
    client = _RecordingClient()
    gateway = ResearchModelGateway(client=client, model_name="fake-flash")

    result = _call_gateway(gateway)

    assert result.status == "unavailable"
    assert client.requests == [], "no request may be sent without authorized work"
    # Nothing was reserved for the experiment either.
    with pytest.raises(Exception):
        experiment_spend(EXPERIMENT)


def test_the_same_call_is_charged_once_the_work_is_declared(monkeypatch, tmp_path):
    _budget(monkeypatch, tmp_path)
    _provider_env(monkeypatch)
    client = _RecordingClient()
    gateway = ResearchModelGateway(client=client, model_name="fake-flash")

    with spend_scope(
        run_id="web_lookup_run7",
        operation_id="op7",
        purpose="active_research",
        experiment=EXPERIMENT,
    ):
        result = _call_gateway(gateway)

    assert result.status == "completed"
    assert len(client.requests) == 1
    spend = experiment_spend(EXPERIMENT)
    assert spend["calls"] == 1
    assert spend["reserved_micros"] > 0


def test_a_budget_stop_is_reported_as_budget_exhausted(monkeypatch, tmp_path):
    """P1: a spend stop is not a model/parse failure and must not be retried."""

    _budget(monkeypatch, tmp_path, cap="0.0000001")
    _provider_env(monkeypatch)
    client = _RecordingClient()
    gateway = ResearchModelGateway(client=client, model_name="fake-flash", max_attempts=3)

    with spend_scope(
        run_id="web_lookup_run8",
        operation_id="op8",
        purpose="active_research",
        experiment=EXPERIMENT,
    ):
        result = _call_gateway(gateway)

    assert result.status == "unavailable"
    assert result.reason == "budget_exhausted"
    assert result.reason != "model_call_attempts_exhausted"
    assert client.requests == []
    # The stop is not retried as if it were a provider failure.
    assert len(result.audits) == 1
    assert result.audits[0].error_type == "SpendLimitExceeded"


# -- 2. a busy database ------------------------------------------------------
def _locker(database: Path, hold_seconds: float, started: threading.Event) -> threading.Thread:
    def hold() -> None:
        connection = sqlite3.connect(str(database), timeout=30.0)
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "INSERT INTO runtime_meta(key, value) VALUES('ledger-lock', '1')"
            " ON CONFLICT(key) DO UPDATE SET value = '1'"
        )
        started.set()
        time.sleep(hold_seconds)
        connection.commit()
        connection.close()

    thread = threading.Thread(target=hold, daemon=True)
    thread.start()
    return thread


def _seeded_ledger(database: Path) -> SpendLedger:
    ledger = SpendLedger(database)
    ledger.ensure_experiment(
        EXPERIMENT,
        cap_micros=10 * MICROS_PER_CNY,
        pricing_fingerprint="pricing",
        now="2026-10-19T00:00:00+00:00",
    )
    return ledger


def test_a_busy_database_is_retried_until_the_lock_is_released(tmp_path):
    """The retry loop must actually see a locked database and then succeed."""

    database = tmp_path / "busy.db"
    RuntimeDatabase(database).initialize()
    _seeded_ledger(database)
    started = threading.Event()
    thread = _locker(database, 0.4, started)
    assert started.wait(timeout=10)

    ledger = SpendLedger(database, busy_timeout_ms=50, busy_retries=20)
    reservation = ledger.reserve(
        EXPERIMENT,
        request_key="after-the-lock",
        amount_micros=1_000,
        purpose="chat:x",
        model="m",
        identity="i",
        now="2026-10-19T00:00:01+00:00",
    )
    thread.join(timeout=10)

    assert reservation.amount_micros == 1_000
    assert ledger.experiment_spend(EXPERIMENT)["reserved_micros"] == 1_000


def test_a_lock_held_past_the_retry_budget_fails_closed(tmp_path):
    database = tmp_path / "busy-long.db"
    RuntimeDatabase(database).initialize()
    _seeded_ledger(database)
    started = threading.Event()
    thread = _locker(database, 5.0, started)
    assert started.wait(timeout=10)

    ledger = SpendLedger(database, busy_timeout_ms=20, busy_retries=1)
    with pytest.raises(SpendLedgerUnavailable) as excinfo:
        ledger.reserve(
            EXPERIMENT,
            request_key="never",
            amount_micros=1_000,
            purpose="chat:x",
            model="m",
            identity="i",
            now="2026-10-19T00:00:01+00:00",
        )
    assert "busy" in str(excinfo.value)
    thread.join(timeout=10)


# -- 3. the guard's own contract ---------------------------------------------
def test_an_authorized_identity_is_required_even_with_an_explicit_key(monkeypatch, tmp_path):
    _budget(monkeypatch, tmp_path)
    from src.llm_spend_guard import SpendConfigurationError

    with pytest.raises(SpendConfigurationError):
        reserve_call(
            prompt_chars=100,
            max_tokens=10,
            attempts=1,
            purpose="research:lead_discovery",
            model="m",
            request_key="gateway:lead-discovery:1",
        )
    # ...and the declared work may spend.
    with spend_identity(
        run_id="run1", operation_id="op1", invocation="1", experiment=EXPERIMENT
    ):
        reserve_call(
            prompt_chars=100,
            max_tokens=10,
            attempts=1,
            purpose="research:lead_discovery",
            model="m",
            request_key="gateway:lead-discovery:1",
        )
    assert experiment_spend(EXPERIMENT)["calls"] == 1


def test_an_identity_for_another_experiment_is_refused(monkeypatch, tmp_path):
    _budget(monkeypatch, tmp_path)
    from src.llm_spend_guard import SpendConfigurationError

    with pytest.raises(SpendConfigurationError):
        reserve_call(
            prompt_chars=100,
            max_tokens=10,
            attempts=1,
            purpose="research:lead_discovery",
            model="m",
            request_key="gateway:lead-discovery:1",
            identity=SpendIdentity(
                run_id="run1", operation_id="op1", invocation="1", experiment="other"
            ),
        )
