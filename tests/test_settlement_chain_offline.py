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
from src.llm_client import effective_attempts
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


def _admission(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    admission = build_settlement_admission(model=MODEL, kind="chat", scope_id="turn-1")
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
        logical=admission.logical,
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
        logical=admission.logical,
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


def test_the_authorization_covers_the_attempts_the_transport_reserves(
    monkeypatch, tmp_path
):
    """The permit must bound what the SDK may really attempt.

    The transport reserves ``retries + 1`` attempts; a permit that authorizes
    one attempt refuses the very send it was issued for, and the refusal happens
    before the provider is reached. The earlier chain test missed this because
    its stand-in transport called ``reserve_call`` without the transport's
    attempt count.
    """

    # The provider profile must be readable before admission is built, otherwise
    # the retry budget falls back to one attempt and the mismatch cannot be seen.
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("OPENAI_MODEL_FLASH_NAME", "deepseek-chat")
    monkeypatch.setenv("OPENAI_MODEL_PRO_NAME", "deepseek-reasoner")
    admission = _admission(monkeypatch, tmp_path)
    attempts = effective_attempts()
    assert attempts >= 2, "the default provider profile retries at least once"
    calls: list[float] = []

    def completion(*, messages, timeout, task_name, **_kwargs):
        chars = serialized_request_chars(
            {"messages": messages, "model": MODEL, "max_tokens": ESTIMATE}
        )
        calls.append(
            reserve_call(
                prompt_chars=chars,
                max_tokens=ESTIMATE,
                attempts=attempts,
                purpose="chat",
                model=MODEL,
            )
        )
        return "ok"

    admitted = AdmittedCompletion(
        completion,
        logical=admission.logical,
        ledger=admission.adapter,
        model=MODEL,
        price_micros=lambda tokens: tokens,
        estimate_output_tokens=ESTIMATE,
    )
    with spend_identity(
        run_id="run-1", operation_id="op-1", invocation="1", experiment=EXPERIMENT
    ):
        assert admitted(
            messages=[{"role": "user", "content": "hi"}],
            timeout=5.0,
            task_name="op-1#r1#answer",
        ) == "ok"

    # Admitted once, not re-priced, and the retry budget was part of the permit.
    assert calls == [0.0]
    assert admission.attempts == attempts


def test_the_chain_is_absent_when_the_flag_is_off(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    monkeypatch.setenv(ASSEMBLY_FLAG, "0")
    assert build_settlement_admission(model=MODEL, kind="chat", scope_id="turn-1") is None


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

    admission = build_settlement_admission(model=MODEL, kind="chat", scope_id="turn-1")
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


def test_an_unregistered_owner_cannot_claim_the_first_reservation(monkeypatch, tmp_path):
    """P1: the permission is an adapter capability, not a settable flag."""

    _admission(monkeypatch, tmp_path)
    with spend_identity(
        run_id="run-1", operation_id="op-1", invocation="1", experiment=EXPERIMENT
    ):
        with pytest.raises(SpendAuthorizationError) as refused:
            reserve_call(
                prompt_chars=10,
                max_tokens=10,
                model=MODEL,
                request_key="forged-owner",
                settling_owner=object(),
            )
    assert refused.value.reason == "send_not_admitted"


# -- the second track: logical quota --------------------------------------------------


def _quota_caps(admission) -> tuple[int, int, int]:
    import sqlite3

    with sqlite3.connect(admission.logical_path) as connection:
        return connection.execute(
            "SELECT max_calls, max_prompt_chars, max_output_tokens "
            "FROM decision_admission_limits WHERE id = 1"
        ).fetchone()


def test_the_chat_turn_carries_the_approved_trial_quota(monkeypatch, tmp_path):
    admission = _admission(monkeypatch, tmp_path)
    assert _quota_caps(admission) == (6, 120_000, 12_000)


def test_a_research_operation_carries_its_own_quota(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    admission = build_settlement_admission(
        model=MODEL, kind="research", scope_id="op-1"
    )
    assert admission is not None
    assert _quota_caps(admission) == (12, 240_000, 24_000)


def test_the_quota_file_is_stable_for_the_same_scope(monkeypatch, tmp_path):
    first = _admission(monkeypatch, tmp_path)
    second = build_settlement_admission(
        model=MODEL, kind="chat", scope_id="turn-1"
    )
    assert second is not None
    assert first.logical_path == second.logical_path


def test_a_reopened_quota_file_cannot_be_widened(monkeypatch, tmp_path):
    from src.application.spend_admission_factory import (
        AdmissionConfigError,
        LogicalQuota,
    )

    _admission(monkeypatch, tmp_path)
    with pytest.raises(AdmissionConfigError) as refused:
        build_settlement_admission(
            model=MODEL,
            kind="chat",
            scope_id="turn-1",
            quota=LogicalQuota(99, 999_999, 99_999),
        )
    assert refused.value.reason == "logical_admission_refused"


def test_the_logical_track_stops_a_turn_before_the_cost_track(
    monkeypatch, tmp_path
):
    from src.application.spend_admission_factory import LogicalQuota
    from src.web.semantic_admission import AdmissionRefused

    _configure(monkeypatch, tmp_path)
    admission = build_settlement_admission(
        model=MODEL,
        kind="chat",
        scope_id="turn-1",
        quota=LogicalQuota(1, 120_000, 12_000),
    )
    assert admission is not None
    admitted = _admitted(admission)

    with spend_identity(
        run_id="run-1", operation_id="op-1", invocation="1", experiment=EXPERIMENT
    ):
        assert admitted(
            messages=[{"role": "user", "content": "one"}],
            timeout=5.0,
            task_name="op-1#r1#answer",
        ) == "the answer"
        with pytest.raises(AdmissionRefused) as refused:
            admitted(
                messages=[{"role": "user", "content": "two"}],
                timeout=5.0,
                task_name="op-1#r2#answer",
            )
    assert refused.value.args[0] == "budget_exhausted"
    rows = admission.settlements._connect().execute(
        "SELECT COUNT(*) FROM llm_spend_reservations"
    ).fetchone()[0]
    assert rows == 1


def test_a_cost_refusal_does_not_refund_the_logical_reservation(monkeypatch, tmp_path):
    """Order is logical then cost; a later cost refusal keeps the logical spend."""

    from src.application.spend_settlement_adapter import RESERVED
    from src.domain.spend_settlement import COST_BASIS_MEASURED_USAGE, SETTLEMENT_SETTLED
    from src.web.semantic_admission import AdmissionRefused

    _configure(monkeypatch, tmp_path)
    admission = build_settlement_admission(
        model=MODEL, kind="chat", scope_id="turn-1"
    )
    assert admission is not None

    # A previous send recorded a cost above its reservation: the experiment is
    # already known not to be bounded.
    with spend_identity(
        run_id="run-1", operation_id="op-1", invocation="1", experiment=EXPERIMENT
    ):
        assert admission.adapter.reserve(
            "pre-existing",
            model=MODEL,
            max_output_tokens=10,
            prompt_chars=10,
        ) == RESERVED
    admission.settlements.settle(
        EXPERIMENT,
        "pre-existing",
        outcome=SETTLEMENT_SETTLED,
        cost_micros=900,
        cost_basis=COST_BASIS_MEASURED_USAGE,
        evidence_ref="provider_result:pre-existing#receipt",
        observed_at="2026-10-25T00:00:01+00:00",
    )

    admitted = _admitted(admission)
    with spend_identity(
        run_id="run-1", operation_id="op-1", invocation="1", experiment=EXPERIMENT
    ):
        with pytest.raises(AdmissionRefused):
            admitted(
                messages=[{"role": "user", "content": "hi"}],
                timeout=5.0,
                task_name="op-1#r1#answer",
            )
    # The overrun blocked the cost track, but the logical reservation stands:
    # the call was admitted, then refused, and the quota is not refunded.
    usage = admission.logical.usage()
    assert usage.calls == 1
    rows = admission.settlements._connect().execute(
        "SELECT COUNT(*) FROM llm_spend_reservations WHERE request_key = ?",
        ("op-1#r1#answer",),
    ).fetchone()[0]
    assert rows == 0
