"""CL-M3-S2-B1-2d: the assembly survives the ways a turn actually ends.

Not "the happy path works", but the specific endings that can leave money and
audit disagreeing:

* a stream is abandoned by its consumer (sync and async);
* a research session times out while its worker is still inside a send;
* the settlement store fails to write after the provider answered;
* the process dies between the reservation and the observation.

Each one has a required shape: the money stays reserved, the observation is
either honest or absent-and-recoverable, and no second send is started.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from src.application.admitted_chat import admitted_completion_for, admitted_stream_chat
from src.application.spend_admission_factory import (
    ASSEMBLY_FLAG,
    build_settlement_admission,
)
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.infrastructure.sqlite.spend_settlement import SettlementUnavailable
from src.llm_spend_guard import reset_spend, reserve_call, spend_identity
from src.web.semantic_recovery import ResearchSemanticSession

EXPERIMENT = "assembly-recovery"
MODEL = "deepseek-chat"
REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    reset_spend()
    for name in (
        ASSEMBLY_FLAG,
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


def _configure(monkeypatch, database: Path) -> None:
    monkeypatch.setenv(ASSEMBLY_FLAG, "1")
    monkeypatch.setenv("LLM_SPEND_LEDGER_DB", str(database.resolve()))
    monkeypatch.setenv("LLM_SPEND_EXPERIMENT_ID", EXPERIMENT)
    monkeypatch.setenv("LLM_SPEND_EXPERIMENT_CAP_CNY", "10")
    monkeypatch.setenv("LLM_SPEND_INPUT_CNY_PER_MTOK", "1")
    monkeypatch.setenv("LLM_SPEND_OUTPUT_CNY_PER_MTOK", "1")


def _database(tmp_path: Path) -> Path:
    path = tmp_path / "runtime.sqlite"
    RuntimeDatabase(path).initialize()
    return path


def _rows(admission) -> int:
    return admission.settlements._connect().execute(
        "SELECT COUNT(*) FROM llm_spend_reservations"
    ).fetchone()[0]


# -- an abandoned consumer -----------------------------------------------------------


def test_a_sync_stream_abandoned_by_its_consumer_is_unresolved(monkeypatch, tmp_path):
    database = _database(tmp_path)
    _configure(monkeypatch, database)
    admission = build_settlement_admission(
        model=MODEL, kind="chat", scope_id="turn-1"
    )
    assert admission is not None

    def base_stream(messages, *, task_name=None, timeout=None, **kwargs):
        reserve_call(
            prompt_chars=10, max_tokens=100, model=MODEL, request_key=task_name
        )
        yield "a"
        yield "b"

    call = admitted_stream_chat(base_stream, admission, scope="turn-1")
    with spend_identity(
        run_id="run-1", operation_id="op-1", invocation="1", experiment=EXPERIMENT
    ):
        stream = call([{"role": "user", "content": "hi"}], task_name="chat")
        assert next(stream) == "a"
        stream.close()

    record = admission.settlements.current(EXPERIMENT, "turn-1#r1#chat")
    assert record is not None and record.outcome == "unresolved"
    assert record.cost_micros is None
    assert _rows(admission) == 1


def test_an_async_stream_closed_during_loop_shutdown_is_unresolved(monkeypatch, tmp_path):
    import asyncio

    from src.application.admitted_chat import admitted_async_stream_chat

    database = _database(tmp_path)
    _configure(monkeypatch, database)
    admission = build_settlement_admission(
        model=MODEL, kind="chat", scope_id="turn-1"
    )
    assert admission is not None

    async def base_stream(messages, *, task_name=None, timeout=None, **kwargs):
        reserve_call(
            prompt_chars=10, max_tokens=100, model=MODEL, request_key=task_name
        )
        yield "a"
        yield "b"

    call = admitted_async_stream_chat(base_stream, admission, scope="turn-1")

    async def consume_then_close():
        async with spend_identity_async():
            stream = call([{"role": "user", "content": "hi"}], task_name="chat")
            assert await stream.__anext__() == "a"
            await stream.aclose()

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def spend_identity_async():
        with spend_identity(
            run_id="run-1", operation_id="op-1", invocation="1",
            experiment=EXPERIMENT,
        ):
            yield

    asyncio.run(consume_then_close())

    record = admission.settlements.current(EXPERIMENT, "turn-1#r1#chat")
    assert record is not None and record.outcome == "unresolved"
    assert _rows(admission) == 1


# -- a worker that outlives its session ----------------------------------------------


def test_a_research_worker_that_outlives_the_session_starts_no_second_send(
    monkeypatch, tmp_path
):
    database = _database(tmp_path)
    _configure(monkeypatch, database)
    admission = build_settlement_admission(
        model=MODEL, kind="research", scope_id="op-1"
    )
    assert admission is not None

    calls: list[float] = []

    def slow_completion(*, messages, timeout, task_name, **kwargs):
        reserve_call(
            prompt_chars=10, max_tokens=100, model=MODEL, request_key=task_name
        )
        calls.append(time.monotonic())
        time.sleep(0.5)
        return json.dumps({"intent": "ANSWER"})

    admitted = admitted_completion_for(
        slow_completion, admission, estimate_output_tokens=100
    )
    session = ResearchSemanticSession(
        admitted,
        deadline=time.monotonic() + 0.35,
        should_cancel=lambda: False,
        task_identity=lambda stage: f"op-1#r1#{stage}",
    )

    with spend_identity(
        run_id="run-1", operation_id="op-1", invocation="1", experiment=EXPERIMENT
    ):
        with pytest.raises(TimeoutError):
            session.request("research_turn_interpretation", "x", {})

    # The worker is still running its single send; nothing else was started.
    time.sleep(1.0)
    assert len(calls) == 1
    assert _rows(admission) == 1
    record = admission.settlements.current(
        EXPERIMENT, "op-1#r1#research_turn_interpretation"
    )
    # The send did finish, so the observation is the worker's, not a duplicate.
    assert record is not None and record.settled is True


# -- the audit store fails between the send and the observation ----------------------


def test_a_failed_observation_write_leaves_recoverable_debt(monkeypatch, tmp_path):
    from src.web.semantic_admission import AdmittedCompletion

    database = _database(tmp_path)
    _configure(monkeypatch, database)
    admission = build_settlement_admission(
        model=MODEL, kind="chat", scope_id="turn-1"
    )
    assert admission is not None
    repository = admission.settlements
    real_settle = repository.settle
    attempts = {"count": 0}

    def flaky_settle(*args, **kwargs):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise SettlementUnavailable("disk full")
        return real_settle(*args, **kwargs)

    monkeypatch.setattr(repository, "settle", flaky_settle)

    def completion(*, messages, timeout, task_name, **kwargs):
        reserve_call(
            prompt_chars=10, max_tokens=100, model=MODEL, request_key=task_name
        )
        return "ok"

    admitted = AdmittedCompletion(
        completion,
        logical=admission.logical,
        ledger=admission.adapter,
        model=MODEL,
        price_micros=lambda tokens: 1,
        estimate_output_tokens=100,
    )
    with spend_identity(
        run_id="run-1", operation_id="op-1", invocation="1", experiment=EXPERIMENT
    ):
        with pytest.raises(SettlementUnavailable):
            admitted(
                messages=[{"role": "user", "content": "hi"}],
                timeout=5.0,
                task_name="op-1#r1#answer",
            )

    # The send happened and the money is reserved; the observation is missing and
    # reported as debt rather than invented.
    assert _rows(admission) == 1
    assert repository.unwritten() == ((EXPERIMENT, "op-1#r1#answer"),)

    # Reconciliation is allowed and idempotent once the store is back.
    repository.settle(
        EXPERIMENT,
        "op-1#r1#answer",
        outcome="unresolved",
        observed_at=time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
    )
    assert repository.unwritten() == ()


# -- the process dies between the reservation and the observation ---------------------


def test_a_restart_after_a_kill_finds_the_reservation_and_the_quota_usage(
    monkeypatch, tmp_path
):
    database = _database(tmp_path)
    _configure(monkeypatch, database)
    script = tmp_path / "kill_worker.py"
    script.write_text(
        "import os\n"
        "from src.application.spend_admission_factory import build_settlement_admission\n"
        "from src.llm_spend_guard import spend_identity\n"
        "admission = build_settlement_admission(\n"
        "    model='deepseek-chat', kind='research', scope_id='op-1')\n"
        "assert admission is not None\n"
        "with spend_identity(run_id='run-1', operation_id='op-1',\n"
        "                    invocation='1', experiment='assembly-recovery'):\n"
        "    verdict = admission.logical.reserve(\n"
        "        'op-1#r1#research_turn_interpretation', 10, 100)\n"
        "    assert verdict == 'reserved', verdict\n"
        "    reservation = admission.adapter.reserve(\n"
        "        'op-1#r1#research_turn_interpretation', model='deepseek-chat',\n"
        "        max_output_tokens=100, prompt_chars=10)\n"
        "    assert reservation == 'reserved', reservation\n"
        "os._exit(9)\n",
        encoding="utf-8",
    )
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(REPO_ROOT)

    completed = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(REPO_ROOT),
        env=environment,
        timeout=120,
    )
    assert completed.returncode == 9

    restarted = build_settlement_admission(
        model=MODEL, kind="research", scope_id="op-1"
    )
    assert restarted is not None
    assert restarted.settlements.unwritten() == (
        (EXPERIMENT, "op-1#r1#research_turn_interpretation"),
    )
    # The logical reservation survived too: a restart does not hand out a new
    # budget for the same operation.
    assert restarted.logical.usage().calls == 1
    assert _rows(restarted) == 1
