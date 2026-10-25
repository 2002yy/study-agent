"""CL-M3-S2-B1-2b: an offline chat + research chain that actually closes.

No provider is called. The completion below stands in for `src.llm_client`: it
prices the serialized request exactly the way the transport does and calls
`reserve_call` - which, inside the admission scope, must *not* write a second
reservation. The assertions are the contract's: one send, one reservation, one
auditable observation, and nothing left in the debt list.

The research call runs through `ResearchSemanticSession`, so it also proves the
identity survives the thread hop and that the task name is round-scoped.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from src.application.spend_admission_factory import (
    ASSEMBLY_FLAG,
    build_settlement_admission,
)
from src.application.spend_settlement_adapter import SettlementLedgerAdapter
from src.llm_spend_guard import (
    SpendAuthorizationError,
    reset_spend,
    reserve_call,
    serialized_request_chars,
    spend_identity,
)
from src.web.semantic_admission import AdmittedCompletion
from src.web.semantic_recovery import ResearchSemanticSession

EXPERIMENT = "chain-experiment"
MODEL = "deepseek-chat"
ESTIMATE = 100


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


def _configure(monkeypatch, tmp_path: Path) -> Path:
    from src.infrastructure.sqlite.database import RuntimeDatabase

    database = tmp_path / "runtime.sqlite"
    RuntimeDatabase(database).initialize()
    monkeypatch.setenv(ASSEMBLY_FLAG, "1")
    monkeypatch.setenv("LLM_SPEND_LEDGER_DB", str(database.resolve()))
    monkeypatch.setenv("LLM_SPEND_EXPERIMENT_ID", EXPERIMENT)
    monkeypatch.setenv("LLM_SPEND_EXPERIMENT_CAP_CNY", "10")
    monkeypatch.setenv("LLM_SPEND_INPUT_CNY_PER_MTOK", "1")
    monkeypatch.setenv("LLM_SPEND_OUTPUT_CNY_PER_MTOK", "1")
    return database


class _Logical:
    def reserve(self, request_id, prompt_chars, output_tokens):
        return "reserved"


def _admission(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    admission = build_settlement_admission(model=MODEL)
    assert admission is not None
    return admission


def _completion(*, messages, timeout, task_name, **_kwargs):
    """Stand-in for the transport: price the real request, then answer."""

    chars = serialized_request_chars(
        {"messages": messages, "model": MODEL, "max_tokens": ESTIMATE}
    )
    reserve_call(
        prompt_chars=chars,
        max_tokens=ESTIMATE,
        purpose="chat",
        model=MODEL,
    )
    if task_name.endswith("#answer"):
        return "the answer"
    return json.dumps({"intent": "ANSWER"})


def _admitted(admission):
    return AdmittedCompletion(
        _completion,
        logical=_Logical(),
        ledger=admission.adapter,
        model=MODEL,
        price_micros=lambda tokens: tokens * 2,
        estimate_output_tokens=ESTIMATE,
    )


def test_one_chat_send_makes_one_reservation_and_one_observation(
    monkeypatch, tmp_path
):
    admission = _admission(monkeypatch, tmp_path)
    admitted = _admitted(admission)

    with spend_identity(
        run_id="run-1", operation_id="op-1", invocation="1", experiment=EXPERIMENT
    ):
        answer = admitted(
            messages=[{"role": "user", "content": "what is a JVM?"}],
            timeout=5.0,
            task_name="op-1#r1#answer",
        )

    assert answer == "the answer"
    assert admission.settlements.unwritten() == ()
    history = admission.settlements.history(EXPERIMENT, "op-1#r1#answer")
    assert [record.outcome for record in history] == ["settled"]
    assert history[0].evidence_ref.startswith("worker_receipt:op-1#r1#answer#")
    assert admission.settlements.reservation(EXPERIMENT, "op-1#r1#answer") is not None


def test_a_chat_send_and_a_research_round_each_close_their_own_loop(
    monkeypatch, tmp_path
):
    admission = _admission(monkeypatch, tmp_path)
    admitted = _admitted(admission)

    session = ResearchSemanticSession(
        admitted,
        deadline=time.monotonic() + 5.0,
        should_cancel=lambda: False,
        task_identity=lambda stage: f"op-1#r2#{stage}",
    )

    with spend_identity(
        run_id="run-1", operation_id="op-1", invocation="1", experiment=EXPERIMENT
    ):
        assert admitted(
            messages=[{"role": "user", "content": "hello"}],
            timeout=5.0,
            task_name="op-1#r1#answer",
        ) == "the answer"
        decision = session.request(
            "research_turn_interpretation", "interpret", {"question": "why"}
        )

    assert decision == {"intent": "ANSWER"}
    assert admission.settlements.unwritten() == ()
    reserved = admission.settlements._connect().execute(
        "SELECT request_key FROM llm_spend_reservations ORDER BY reservation_id"
    ).fetchall()
    assert [row["request_key"] for row in reserved] == [
        "op-1#r1#answer",
        "op-1#r2#research_turn_interpretation",
    ]
    for key in ("op-1#r1#answer", "op-1#r2#research_turn_interpretation"):
        assert admission.settlements.current(EXPERIMENT, key).settled is True


def test_the_transport_is_authorized_and_does_not_reserve_twice(monkeypatch, tmp_path):
    """The transport's own `reserve_call` is the second-reservation hazard."""

    admission = _admission(monkeypatch, tmp_path)
    calls: list[float] = []

    def completion(*, messages, timeout, task_name, **_kwargs):
        chars = serialized_request_chars({"messages": messages, "model": MODEL})
        calls.append(
            reserve_call(
                prompt_chars=chars, max_tokens=ESTIMATE, purpose="chat", model=MODEL
            )
        )
        return "ok"

    admitted = AdmittedCompletion(
        completion,
        logical=_Logical(),
        ledger=admission.adapter,
        model=MODEL,
        price_micros=lambda tokens: tokens,
        estimate_output_tokens=ESTIMATE,
    )
    with spend_identity(
        run_id="run-1", operation_id="op-1", invocation="1", experiment=EXPERIMENT
    ):
        admitted(
            messages=[{"role": "user", "content": "hi"}],
            timeout=5.0,
            task_name="op-1#r1#answer",
        )

    # The transport's reservation call returned "already reserved" (0.0) rather
    # than pricing the send a second time.
    assert calls == [0.0]
    rows = admission.settlements._connect().execute(
        "SELECT COUNT(*) FROM llm_spend_reservations"
    ).fetchone()[0]
    assert rows == 1


def test_the_chain_is_absent_when_the_flag_is_off(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    monkeypatch.setenv(ASSEMBLY_FLAG, "0")
    assert build_settlement_admission(model=MODEL) is None


def test_the_adapter_is_the_one_the_factory_built(monkeypatch, tmp_path):
    admission = _admission(monkeypatch, tmp_path)
    assert isinstance(admission.adapter, SettlementLedgerAdapter)


# -- experiment mode: un-wired entries fail closed, not open --------------------


def test_experiment_mode_refuses_an_unadmitted_transport_reservation(
    monkeypatch, tmp_path
):
    """A path nobody wired yet must be refused before it reaches the provider."""

    _admission(monkeypatch, tmp_path)
    with spend_identity(
        run_id="run-1", operation_id="op-1", invocation="1", experiment=EXPERIMENT
    ):
        with pytest.raises(SpendAuthorizationError) as refused:
            reserve_call(
                prompt_chars=10,
                max_tokens=10,
                model=MODEL,
                purpose="vision:image_description",
                request_key="direct-1",
            )
    assert refused.value.reason == "send_not_admitted"

    admission = build_settlement_admission(model=MODEL)
    assert admission is not None
    rows = admission.settlements._connect().execute(
        "SELECT COUNT(*) FROM llm_spend_reservations"
    ).fetchone()[0]
    assert rows == 0


def test_experiment_mode_admits_the_authorized_path(monkeypatch, tmp_path):
    admission = _admission(monkeypatch, tmp_path)
    admitted = _admitted(admission)
    with spend_identity(
        run_id="run-1", operation_id="op-1", invocation="1", experiment=EXPERIMENT
    ):
        assert admitted(
            messages=[{"role": "user", "content": "hello"}],
            timeout=5.0,
            task_name="op-1#r1#answer",
        ) == "the answer"
    assert admission.settlements.unwritten() == ()


def test_the_isolation_is_off_when_the_flag_is_off(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    monkeypatch.setenv(ASSEMBLY_FLAG, "0")
    with spend_identity(
        run_id="run-1", operation_id="op-1", invocation="1", experiment=EXPERIMENT
    ):
        reserve_call(
            prompt_chars=10, max_tokens=10, model=MODEL, request_key="direct-2"
        )
    # Off means the old path is untouched: the transport reserves for itself.
    from src.infrastructure.sqlite.spend_ledger import SpendLedger

    ledger = SpendLedger(tmp_path / "runtime.sqlite")
    assert ledger.experiment_spend(EXPERIMENT)["calls"] == 1
