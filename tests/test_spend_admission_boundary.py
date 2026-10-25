"""CL-M3-S2-A: the paid-entry boundary - one reservation, one check, one send.

Three properties are tested here, each with a failure shape that is invisible to
unit tests of the pieces:

1. **One send reserves once.** The admission layer reserves; the transport (which
   also knows how to reserve) must not reserve a second time under its own key.
   Otherwise one answer is charged twice, and both charges look individually
   correct.
2. **The overrun check and the reservation are one decision.** A check performed
   before the write transaction reads a stale snapshot; an overrun observation
   that commits in between is invisible and the reservation is written anyway.
   The test forces that ordering with a second connection holding an uncommitted
   overrun, not with a thread lock.
3. **Evidence has a declared strength.** A fixture proves that a caller can type;
   it must not confirm a completion in a production adapter. A host receipt is
   accepted, and is labelled as host-attested rather than provider-billed.
"""

from __future__ import annotations

import secrets
import sqlite3
import threading
from pathlib import Path

import pytest

from src.application.spend_settlement_adapter import (
    COST_UPPER_BOUND_INVALIDATED,
    RESERVED,
    SettlementLedgerAdapter,
)
from src.domain.spend_settlement import (
    COST_BASIS_ESTIMATED,
    COST_BASIS_MEASURED_USAGE,
    EVIDENCE_LEVEL_HOST_ATTESTED,
    EVIDENCE_LEVEL_TEST_ONLY,
    SETTLEMENT_SETTLED,
    SettlementEvidenceError,
    evidence_level,
    evidence_ref,
)
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.infrastructure.sqlite.spend_ledger import (
    SpendAdmissionRefused,
    SpendLedger,
)
from src.infrastructure.sqlite.spend_settlement import SpendSettlementRepository
from src.llm_spend_guard import (
    SendAuthorization,
    SpendAuthorizationError,
    authorize_send,
    pre_reserved_send,
    reset_spend,
    reserve_call,
    serialized_request_chars,
    spend_identity,
)
from src.web.semantic_admission import AdmittedCall, AdmittedCompletion, SETTLED

NOW = "2026-10-25T00:00:00+00:00"
EXPERIMENT = "admission-experiment"
CAP_MICROS = 10_000_000


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


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "runtime.sqlite"
    RuntimeDatabase(path).initialize()
    return path


@pytest.fixture
def ledger(database):
    instance = SpendLedger(database, busy_timeout_ms=8_000)
    instance.ensure_experiment(
        EXPERIMENT, cap_micros=CAP_MICROS, pricing_fingerprint="p", now=NOW
    )
    return instance


def _reserve(ledger, key="key-1", amount=500, **kwargs):
    return ledger.reserve(
        EXPERIMENT,
        request_key=key,
        amount_micros=amount,
        purpose="chat:deep_planner",
        model="deepseek-chat",
        identity="run=run1 op=op1 inv=1",
        now=NOW,
        **kwargs,
    )


def _configure(monkeypatch, database: Path) -> None:
    monkeypatch.setenv("LLM_SPEND_LEDGER_DB", str(database.resolve()))
    monkeypatch.setenv("LLM_SPEND_EXPERIMENT_ID", EXPERIMENT)
    monkeypatch.setenv("LLM_SPEND_EXPERIMENT_CAP_CNY", "10")
    monkeypatch.setenv("LLM_SPEND_INPUT_CNY_PER_MTOK", "1")
    monkeypatch.setenv("LLM_SPEND_OUTPUT_CNY_PER_MTOK", "1")


def _identity():
    return spend_identity(
        run_id="run1", operation_id="op1", invocation="1", experiment=EXPERIMENT
    )


def _count(path: Path, table: str, where: str = "1=1", parameters: tuple = ()) -> int:
    with sqlite3.connect(path) as connection:
        return connection.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {where}", parameters
        ).fetchone()[0]


# -- 2. the check and the write are one decision -----------------------------------


def test_the_guard_refuses_inside_the_reservation_transaction(ledger, database):
    def refuse(connection, experiment_id):
        assert experiment_id == EXPERIMENT
        return "cost_upper_bound_invalidated"

    with pytest.raises(SpendAdmissionRefused) as refused:
        _reserve(ledger, key="key-2", amount=100, admission_guard=refuse)

    assert refused.value.reason == "cost_upper_bound_invalidated"
    assert _count(database, "llm_spend_reservations") == 0


def test_an_overrun_committed_during_the_reservation_window_still_blocks(
    ledger, database
):
    """The P1 race, forced with two real connections.

    Connection B holds an uncommitted overrun for ``key-1``. The reserving thread
    starts while B still holds the write lock, so any check made *outside* the
    transaction reads the old state and lets the reservation through. The guard
    inside ``BEGIN IMMEDIATE`` waits for B, then sees the committed row.
    """

    _reserve(ledger, key="key-1", amount=500)
    repository = SpendSettlementRepository(database)
    blocker = sqlite3.connect(database, timeout=10.0)
    blocker.execute("PRAGMA foreign_keys = ON")
    blocker.execute("BEGIN IMMEDIATE")
    blocker.execute(
        "INSERT INTO llm_spend_settlements("
        "experiment_id, request_key, revision, outcome, cost_micros, cost_basis, "
        "evidence_ref, observed_at"
        ") VALUES (?, ?, 1, 'settled', ?, ?, ?, ?)",
        (
            EXPERIMENT,
            "key-1",
            900,
            COST_BASIS_MEASURED_USAGE,
            "provider_result:key-1#receipt",
            NOW,
        ),
    )

    results: list[tuple[str, object]] = []
    started = threading.Event()

    def reserve_while_blocked():
        try:
            started.set()
            _reserve(ledger, key="key-2", amount=100,
                    admission_guard=repository.admission_guard)
            results.append(("ok", None))
        except Exception as exc:  # noqa: BLE001 - the test inspects the type
            results.append(("error", exc))

    thread = threading.Thread(target=reserve_while_blocked)
    thread.start()
    assert started.wait(timeout=5)
    # Give the thread time to reach the check (or the write) before B commits.
    thread.join(timeout=0.4)
    blocker.commit()
    blocker.close()
    thread.join(timeout=20)

    assert not thread.is_alive()
    assert [status for status, _ in results] == ["error"]
    error = results[0][1]
    assert isinstance(error, SpendAdmissionRefused)
    assert error.reason == "cost_upper_bound_invalidated"
    assert _count(
        database, "llm_spend_reservations", "request_key = ?", ("key-2",)
    ) == 0
    assert _count(database, "llm_spend_settlements") == 1


def test_without_the_guard_the_same_window_admits_the_reservation(ledger, database):
    """The negative control for the test above: the race is real, not assumed."""

    _reserve(ledger, key="key-1", amount=500)
    blocker = sqlite3.connect(database, timeout=10.0)
    blocker.execute("BEGIN IMMEDIATE")
    blocker.execute(
        "INSERT INTO llm_spend_settlements("
        "experiment_id, request_key, revision, outcome, cost_micros, cost_basis, "
        "evidence_ref, observed_at"
        ") VALUES (?, 'key-1', 1, 'settled', 900, 'measured_usage', ?, ?)",
        (EXPERIMENT, "provider_result:key-1#receipt", NOW),
    )
    errors: list[Exception] = []

    def reserve_while_blocked():
        try:
            _reserve(ledger, key="key-2", amount=100)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    thread = threading.Thread(target=reserve_while_blocked)
    thread.start()
    thread.join(timeout=0.4)
    blocker.commit()
    blocker.close()
    thread.join(timeout=20)

    # No guard means the pre-transaction state is what counts: the reservation is
    # admitted even though the overrun is committed before it lands.
    assert errors == []
    assert _count(
        database, "llm_spend_reservations", "request_key = ?", ("key-2",)
    ) == 1


# -- 1. one send reserves once -------------------------------------------------------


def test_a_pre_reserved_send_does_not_reserve_a_second_time(monkeypatch, database):
    _configure(monkeypatch, database)
    repository = SpendSettlementRepository(database)
    adapter = SettlementLedgerAdapter(repository)
    with _identity():
        assert adapter.reserve(
            "send-1", model="deepseek-chat", max_output_tokens=100, prompt_chars=1000
        ) == RESERVED
        assert _count(database, "llm_spend_reservations") == 1
        authorization = adapter.claim_send_authorization("send-1")
        assert authorization is not None
        # The transport reserves too, unless it presents the authorization.
        with pre_reserved_send(authorization):
            assert reserve_call(prompt_chars=10, max_tokens=10, model="deepseek-chat") == 0.0
        assert _count(database, "llm_spend_reservations") == 1


def test_an_authorization_cannot_be_claimed_twice(monkeypatch, database):
    _configure(monkeypatch, database)
    adapter = SettlementLedgerAdapter(SpendSettlementRepository(database))
    with _identity():
        assert adapter.reserve(
            "send-1", model="deepseek-chat", max_output_tokens=100, prompt_chars=1000
        ) == RESERVED
    assert adapter.claim_send_authorization("send-1") is not None
    assert adapter.claim_send_authorization("send-1") is None


def test_a_send_without_a_reservation_has_no_authorization(monkeypatch, database):
    _configure(monkeypatch, database)
    adapter = SettlementLedgerAdapter(SpendSettlementRepository(database))
    assert adapter.claim_send_authorization("never-reserved") is None
    with pytest.raises(SpendAuthorizationError) as refused:
        with pre_reserved_send(
            SendAuthorization(
                experiment_id=EXPERIMENT,
                request_key="never-reserved",
                model="deepseek-chat",
                prompt_chars=100,
                max_tokens=100,
                attempts=1,
                reserved_cny=0.001,
                token="deadbeef",
            )
        ):
            pass
    assert refused.value.reason == "send_authorization_forged"


def test_a_forged_authorization_cannot_authorize_a_send(monkeypatch, database):
    _configure(monkeypatch, database)
    adapter = SettlementLedgerAdapter(SpendSettlementRepository(database))
    with _identity():
        assert adapter.reserve(
            "send-1", model="deepseek-chat", max_output_tokens=100, prompt_chars=1000
        ) == RESERVED
    genuine = adapter.claim_send_authorization("send-1")
    assert genuine is not None
    forged = SendAuthorization(
        experiment_id=genuine.experiment_id,
        request_key=genuine.request_key,
        model=genuine.model,
        prompt_chars=genuine.prompt_chars + 10_000,
        max_tokens=genuine.max_tokens,
        attempts=genuine.attempts,
        reserved_cny=genuine.reserved_cny,
        token=genuine.token,
    )
    with pytest.raises(SpendAuthorizationError) as refused:
        with pre_reserved_send(forged):
            pass
    assert refused.value.reason == "send_authorization_forged"


def test_an_authorization_cannot_be_signed_for_a_missing_reservation(
    monkeypatch, database
):
    """P1-1: the signature must be based on a committed row, not on arguments."""

    _configure(monkeypatch, database)
    with pytest.raises(SpendAuthorizationError) as refused:
        authorize_send(
            experiment_id=EXPERIMENT,
            request_key="never-reserved",
            model="deepseek-chat",
            prompt_chars=100,
            max_tokens=100,
            attempts=1,
        )
    assert refused.value.reason == "reservation_not_found"


def test_an_authorization_cannot_name_a_model_the_reservation_did_not_pay_for(
    monkeypatch,
    database,
):
    _configure(monkeypatch, database)
    adapter = SettlementLedgerAdapter(SpendSettlementRepository(database))
    with _identity():
        assert adapter.reserve(
            "send-1", model="deepseek-chat", max_output_tokens=100, prompt_chars=1000
        ) == RESERVED
    with pytest.raises(SpendAuthorizationError) as refused:
        authorize_send(
            experiment_id=EXPERIMENT,
            request_key="send-1",
            model="a-cheaper-model",
            prompt_chars=100,
            max_tokens=100,
            attempts=1,
        )
    assert refused.value.reason == "reservation_mismatch"


def test_one_authorization_admits_one_transport_check(monkeypatch, database):
    """P1-2: the scope admits one send, not "as many as the caller loops"."""

    _configure(monkeypatch, database)
    adapter = SettlementLedgerAdapter(SpendSettlementRepository(database))
    with _identity():
        assert adapter.reserve(
            "send-1", model="deepseek-chat", max_output_tokens=100, prompt_chars=1000
        ) == RESERVED
    authorization = adapter.claim_send_authorization("send-1")
    assert authorization is not None
    with pre_reserved_send(authorization):
        assert reserve_call(prompt_chars=10, max_tokens=10, model="deepseek-chat") == 0.0
        with pytest.raises(SpendAuthorizationError) as refused:
            reserve_call(prompt_chars=10, max_tokens=10, model="deepseek-chat")
    assert refused.value.reason == "send_authorization_consumed"
    assert _count(database, "llm_spend_reservations") == 1


def test_consumption_runs_under_the_guard_lock(monkeypatch, database):
    """The check and the add share the guard lock, observably.

    A timed race cannot be forced reliably under the GIL (the window is a set
    lookup), so this asserts the mechanism the race depends on: while another
    holder owns the guard lock, an authorization cannot be consumed at all.
    """

    import src.llm_spend_guard as guard

    _configure(monkeypatch, database)
    adapter = SettlementLedgerAdapter(SpendSettlementRepository(database))
    with _identity():
        assert adapter.reserve(
            "send-1", model="deepseek-chat", max_output_tokens=100, prompt_chars=1000
        ) == RESERVED
    authorization = adapter.claim_send_authorization("send-1")
    assert authorization is not None

    completed = threading.Event()

    def consume():
        with pre_reserved_send(authorization):
            pass
        completed.set()

    thread = threading.Thread(target=consume)
    with guard._lock:
        thread.start()
        assert not completed.wait(0.3), "consumed without acquiring the guard lock"
    thread.join(timeout=10)
    assert completed.is_set()


def test_concurrent_entry_consumes_the_authorization_exactly_once(
    monkeypatch, database
):
    """Consumption is atomic: verification alone must not decide the winner.

    Each round releases several threads at once and requires exactly one to enter.
    A single round is a weak probe - the check and the add are microseconds apart
    - so the test repeats the race; a non-atomic implementation loses at least one
    round with overwhelming probability.
    """

    _configure(monkeypatch, database)
    adapter = SettlementLedgerAdapter(SpendSettlementRepository(database))

    for round_index in range(20):
        key = f"race-{round_index}"
        with _identity():
            assert adapter.reserve(
                key, model="deepseek-chat", max_output_tokens=100, prompt_chars=1000
            ) == RESERVED
        authorization = adapter.claim_send_authorization(key)
        assert authorization is not None

        barrier = threading.Barrier(8)
        outcomes: list[str] = []
        lock = threading.Lock()

        def enter(auth=authorization, gate=barrier):
            gate.wait(timeout=10)
            try:
                with pre_reserved_send(auth):
                    outcome = "ok"
            except SpendAuthorizationError:
                outcome = "consumed"
            with lock:
                outcomes.append(outcome)

        threads = [threading.Thread(target=enter) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)

        assert outcomes.count("ok") == 1, f"round {round_index}: {outcomes}"


def test_the_transport_still_reserves_when_no_outer_layer_holds_the_key(
    monkeypatch, database
):
    _configure(monkeypatch, database)
    with _identity():
        reserve_call(prompt_chars=10, max_tokens=10, request_key="send-2",
                     model="deepseek-chat")
    assert _count(database, "llm_spend_reservations") == 1


def test_a_second_key_inside_an_authorized_send_is_refused(monkeypatch, database):
    _configure(monkeypatch, database)
    adapter = SettlementLedgerAdapter(SpendSettlementRepository(database))
    with _identity():
        assert adapter.reserve(
            "send-1", model="deepseek-chat", max_output_tokens=100, prompt_chars=1000
        ) == RESERVED
    authorization = adapter.claim_send_authorization("send-1")
    assert authorization is not None
    with pytest.raises(SpendAuthorizationError) as refused:
        with pre_reserved_send(authorization):
            reserve_call(prompt_chars=10, max_tokens=10, request_key="send-2",
                         model="deepseek-chat")
    assert refused.value.reason == "send_authorization_key_mismatch"
    assert _count(
        database, "llm_spend_reservations", "request_key = ?", ("send-2",)
    ) == 0


class _Logical:
    def reserve(self, request_id, prompt_chars, output_tokens):
        return "reserved"


def test_an_admitted_completion_charges_the_answer_once(monkeypatch, database):
    """The whole A1 shape: adapter + transport in one call, one row.

    The transport prices its serialized request; the admission layer reserved a
    bound that has to cover it, otherwise this call is refused rather than
    double-reserved.
    """

    _configure(monkeypatch, database)
    repository = SpendSettlementRepository(database)
    adapter = SettlementLedgerAdapter(repository)
    seen: list[str] = []

    def completion(*, messages, timeout, task_name, **_kwargs):
        # This is what src/llm_client does for every paid request: it prices the
        # serialized request, not just the message bodies.
        transport_chars = serialized_request_chars(
            {
                "messages": messages,
                "model": "deepseek-chat",
                "max_tokens": 100,
                "task_name": task_name,
            }
        )
        reserve_call(
            prompt_chars=transport_chars,
            max_tokens=100,
            purpose="chat:answer",
            model="deepseek-chat",
        )
        seen.append(task_name)
        return "the answer"

    admitted = AdmittedCompletion(
        completion,
        logical=_Logical(),
        ledger=adapter,
        model="deepseek-chat",
        price_micros=lambda tokens: tokens * 2,
        estimate_output_tokens=100,
    )
    with _identity():
        assert admitted(messages=[{"role": "user", "content": "q"}],
                        timeout=5.0, task_name="op1#r1#answer") == "the answer"

    assert seen == ["op1#r1#answer"]
    assert _count(database, "llm_spend_reservations") == 1
    assert _count(database, "llm_spend_settlements") == 1
    assert admitted.calls == [AdmittedCall("op1#r1#answer", SETTLED, 200)]


def test_an_authorization_only_covers_the_request_it_was_issued_for(
    monkeypatch, database
):
    """P1-2: the outer reservation must cover the transport's real request."""

    _configure(monkeypatch, database)
    adapter = SettlementLedgerAdapter(SpendSettlementRepository(database))
    cases = [
        ({"prompt_chars": None}, "send_authorization_bound_exceeded"),
        ({"max_tokens": None}, "send_authorization_bound_exceeded"),
        ({"attempts": 2}, "send_authorization_bound_exceeded"),
        ({"model": "a-cheaper-model"}, "send_authorization_model_mismatch"),
    ]
    for index, (overrides, reason) in enumerate(cases):
        key = f"probe-{index}"
        with _identity():
            assert adapter.reserve(
                key, model="deepseek-chat", max_output_tokens=100, prompt_chars=1000
            ) == RESERVED
        authorization = adapter.claim_send_authorization(key)
        assert authorization is not None
        arguments = {
            "prompt_chars": 10,
            "max_tokens": 100,
            "model": "deepseek-chat",
        }
        if overrides.get("prompt_chars", "absent") is None:
            arguments["prompt_chars"] = authorization.prompt_chars + 1
        if overrides.get("max_tokens", "absent") is None:
            arguments["max_tokens"] = authorization.max_tokens + 1
        if "attempts" in overrides:
            arguments["attempts"] = overrides["attempts"]
        if "model" in overrides:
            arguments["model"] = overrides["model"]
        with pytest.raises(SpendAuthorizationError) as refused:
            with pre_reserved_send(authorization):
                reserve_call(**arguments)
        assert refused.value.reason == reason
        # Refused before the transport sent: only the reservations we made exist.
        assert _count(database, "llm_spend_reservations") == index + 1


def test_the_admission_bound_is_measured_like_the_transport(monkeypatch, database):
    """One accounting function: messages plus the transport's own overhead."""

    _configure(monkeypatch, database)
    adapter = SettlementLedgerAdapter(SpendSettlementRepository(database))
    messages = [{"role": "user", "content": "查" * 300}]
    with _identity():
        assert adapter.reserve(
            "send-1",
            model="deepseek-chat",
            max_output_tokens=100,
            prompt_chars=10_000,
        ) == RESERVED
    authorization = adapter.claim_send_authorization("send-1")
    assert authorization is not None
    real = serialized_request_chars(
        {"messages": messages, "model": "deepseek-chat", "max_tokens": 100}
    )
    assert real <= authorization.prompt_chars
    with pre_reserved_send(authorization):
        assert reserve_call(prompt_chars=real, max_tokens=100, model="deepseek-chat") == 0.0


def test_the_retry_budget_is_what_the_reservation_paid_for(monkeypatch, database):
    """P2: retries are priced into the reservation and bounded by it.

    The adapter's configured attempt count is what the ledger charged and what
    the authorization admits. A transport that would retry more is refused -
    widening the authorization instead would under-reserve the worst case.
    """

    _configure(monkeypatch, database)
    adapter = SettlementLedgerAdapter(SpendSettlementRepository(database), attempts=2)
    with _identity():
        assert adapter.reserve(
            "send-1", model="deepseek-chat", max_output_tokens=100, prompt_chars=1000
        ) == RESERVED
    authorization = adapter.claim_send_authorization("send-1")
    assert authorization is not None and authorization.attempts == 2
    with pre_reserved_send(authorization):
        assert reserve_call(
            prompt_chars=10, max_tokens=10, attempts=2, model="deepseek-chat"
        ) == 0.0

    with _identity():
        assert adapter.reserve(
            "send-2", model="deepseek-chat", max_output_tokens=100, prompt_chars=1000
        ) == RESERVED
    single = adapter.claim_send_authorization("send-2")
    assert single is not None
    with pytest.raises(SpendAuthorizationError) as refused:
        with pre_reserved_send(single):
            reserve_call(
                prompt_chars=10, max_tokens=10, attempts=3, model="deepseek-chat"
            )
    assert refused.value.reason == "send_authorization_bound_exceeded"
    assert _count(database, "llm_spend_reservations") == 2


def test_an_authorization_cannot_exceed_the_reserved_amount(monkeypatch, database):
    """P1-1 (R3): bounds must be payable by the row, not just signed over."""

    _configure(monkeypatch, database)
    with _identity():
        reserve_call(
            prompt_chars=10, max_tokens=10, model="deepseek-chat", request_key="raw-1"
        )

    with pytest.raises(SpendAuthorizationError) as refused:
        authorize_send(
            experiment_id=EXPERIMENT,
            request_key="raw-1",
            model="deepseek-chat",
            prompt_chars=10_000_000,
            max_tokens=100,
            attempts=1,
        )
    assert refused.value.reason == "authorization_exceeds_reservation"

    # Bounds the row can pay for are still accepted.
    accepted = authorize_send(
        experiment_id=EXPERIMENT,
        request_key="raw-1",
        model="deepseek-chat",
        prompt_chars=10,
        max_tokens=10,
        attempts=1,
    )
    assert accepted.reserved_cny > 0


def test_the_same_reservation_cannot_be_authorized_twice(monkeypatch, database):
    """One row, one credential - a second signature is not a second budget."""

    _configure(monkeypatch, database)
    with _identity():
        reserve_call(
            prompt_chars=10, max_tokens=10, model="deepseek-chat", request_key="raw-2"
        )
    authorize_send(
        experiment_id=EXPERIMENT,
        request_key="raw-2",
        model="deepseek-chat",
        prompt_chars=10,
        max_tokens=10,
        attempts=1,
    )
    with pytest.raises(SpendAuthorizationError) as refused:
        authorize_send(
            experiment_id=EXPERIMENT,
            request_key="raw-2",
            model="deepseek-chat",
            prompt_chars=10,
            max_tokens=10,
            attempts=1,
        )
    assert refused.value.reason == "send_already_authorized"


def test_a_historical_reservation_cannot_be_authorized_after_a_restart(
    monkeypatch, database
):
    """P1 (R4): the capability comes from the write, not from the row.

    A new process can read every old reservation. If that were enough to sign a
    credential, "a retry is a new send with a new key" would be false after every
    crash.
    """

    _configure(monkeypatch, database)
    with _identity():
        reserve_call(
            prompt_chars=10, max_tokens=10, model="deepseek-chat", request_key="raw-3"
        )
    reset_spend()  # a new process: no in-memory record of that write

    with pytest.raises(SpendAuthorizationError) as refused:
        authorize_send(
            experiment_id=EXPERIMENT,
            request_key="raw-3",
            model="deepseek-chat",
            prompt_chars=10,
            max_tokens=10,
            attempts=1,
        )
    assert refused.value.reason == "reservation_not_issued_here"
    assert _count(
        database, "llm_spend_reservations", "request_key = ?", ("raw-3",)
    ) == 1


def test_an_authorization_refuses_prices_that_changed_since_the_reservation(
    monkeypatch, database
):
    """P2 (R4): the price identity is part of the authorization, not ambient."""

    _configure(monkeypatch, database)
    with _identity():
        reserve_call(
            prompt_chars=10, max_tokens=10, model="deepseek-chat", request_key="raw-4"
        )
    monkeypatch.setenv("LLM_SPEND_INPUT_CNY_PER_MTOK", "2")

    with pytest.raises(SpendAuthorizationError) as refused:
        authorize_send(
            experiment_id=EXPERIMENT,
            request_key="raw-4",
            model="deepseek-chat",
            prompt_chars=10,
            max_tokens=10,
            attempts=1,
        )
    assert refused.value.reason == "pricing_mismatch"


def test_an_authorization_does_not_cross_a_process_restart(monkeypatch, database):
    """Recovery rule: authorizations are process-local and die with the process.

    The reservation does not: it stays in the ledger and shows up as
    ``settlement_unwritten`` until the turn is reconciled. A retry after a crash
    is a new send and needs a new key - never a replay of the old credential.
    """

    import src.llm_spend_guard as guard

    _configure(monkeypatch, database)
    repository = SpendSettlementRepository(database)
    adapter = SettlementLedgerAdapter(repository)
    with _identity():
        assert adapter.reserve(
            "send-1", model="deepseek-chat", max_output_tokens=100, prompt_chars=1000
        ) == RESERVED
    authorization = adapter.claim_send_authorization("send-1")
    assert authorization is not None

    monkeypatch.setattr(guard, "_AUTHORIZATION_SECRET", secrets.token_bytes(32))

    with pytest.raises(SpendAuthorizationError) as refused:
        with pre_reserved_send(authorization):
            pass
    assert refused.value.reason == "send_authorization_forged"
    # The money fact survives the process; only the credential does not.
    assert repository.unwritten() == ((EXPERIMENT, "send-1"),)
    assert repository.current(EXPERIMENT, "send-1") is None


# -- 3. evidence strength ------------------------------------------------------------


def test_evidence_levels_are_declared():
    assert evidence_level("offline_fixture") == EVIDENCE_LEVEL_TEST_ONLY
    assert evidence_level("worker_receipt") == EVIDENCE_LEVEL_HOST_ATTESTED
    assert evidence_level("provider_result") == EVIDENCE_LEVEL_HOST_ATTESTED


def test_a_production_adapter_refuses_offline_fixture_evidence(
    monkeypatch, database
):
    _configure(monkeypatch, database)
    repository = SpendSettlementRepository(database)
    adapter = SettlementLedgerAdapter(repository)
    with _identity():
        assert adapter.reserve(
            "send-1", model="deepseek-chat", max_output_tokens=100, prompt_chars=1000
        ) == RESERVED
        with pytest.raises(SettlementEvidenceError) as refused:
            adapter.settle(
                "send-1",
                outcome=SETTLEMENT_SETTLED,
                cost_micros=100,
                cost_basis=COST_BASIS_ESTIMATED,
                evidence_ref=evidence_ref(
                    kind="offline_fixture", request_key="send-1", receipt="r1"
                ),
            )
    assert refused.value.reason == "evidence_fixture_not_allowed"
    assert _count(database, "llm_spend_settlements") == 0


def test_a_test_harness_may_opt_into_offline_fixtures(monkeypatch, database):
    _configure(monkeypatch, database)
    repository = SpendSettlementRepository(database)
    adapter = SettlementLedgerAdapter(repository, allow_offline_fixture=True)
    with _identity():
        assert adapter.reserve(
            "send-1", model="deepseek-chat", max_output_tokens=100, prompt_chars=1000
        ) == RESERVED
        adapter.settle(
            "send-1",
            outcome=SETTLEMENT_SETTLED,
            cost_micros=100,
            cost_basis=COST_BASIS_ESTIMATED,
            evidence_ref=evidence_ref(
                kind="offline_fixture", request_key="send-1", receipt="r1"
            ),
        )
    assert _count(database, "llm_spend_settlements") == 1


def test_a_host_receipt_is_accepted_in_production(monkeypatch, database):
    _configure(monkeypatch, database)
    repository = SpendSettlementRepository(database)
    adapter = SettlementLedgerAdapter(repository)
    with _identity():
        assert adapter.reserve(
            "send-1", model="deepseek-chat", max_output_tokens=100, prompt_chars=1000
        ) == RESERVED
        adapter.settle(
            "send-1",
            outcome=SETTLEMENT_SETTLED,
            cost_micros=100,
            cost_basis=COST_BASIS_ESTIMATED,
            evidence_ref=evidence_ref(
                kind="worker_receipt", request_key="send-1", receipt="completed:abc"
            ),
        )
    record = repository.current(EXPERIMENT, "send-1")
    assert record is not None and record.settled is True


def test_the_adapter_reports_the_guard_refusal_as_an_overrun(monkeypatch, database):
    """End-to-end through the adapter: the guard's reason survives the mapping."""

    _configure(monkeypatch, database)
    ledger = SpendLedger(database)
    ledger.ensure_experiment(
        EXPERIMENT, cap_micros=CAP_MICROS, pricing_fingerprint="p", now=NOW
    )
    _reserve(ledger, key="key-1", amount=500)
    repository = SpendSettlementRepository(database)
    repository.settle(
        EXPERIMENT,
        "key-1",
        outcome=SETTLEMENT_SETTLED,
        cost_micros=900,
        cost_basis=COST_BASIS_MEASURED_USAGE,
        evidence_ref="provider_result:key-1#receipt",
        observed_at=NOW,
    )
    adapter = SettlementLedgerAdapter(repository)
    with _identity():
        assert adapter.reserve(
            "key-2", model="deepseek-chat", max_output_tokens=100, prompt_chars=1000
        ) == COST_UPPER_BOUND_INVALIDATED
    assert _count(
        database, "llm_spend_reservations", "request_key = ?", ("key-2",)
    ) == 0
