import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from src import llm_spend_guard as spend
from src.infrastructure.sqlite.spend_ledger import SpendAdmissionRefused, SpendLedger
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.interactive_repair_budget import (
    InteractiveRepairBudget,
    current_repair_budget,
    repair_budget_scope,
)


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    for key in (
        "LLM_SPEND_CAP_CNY",
        "LLM_SPEND_EXPERIMENT_ID",
        "LLM_SPEND_EXPERIMENT_CAP_CNY",
        "LLM_SPEND_LEDGER_DB",
        "LLM_SPEND_INPUT_CNY_PER_MTOK",
        "LLM_SPEND_OUTPUT_CNY_PER_MTOK",
        "LLM_EXPERIMENT_ALLOWED_MODELS",
        "STUDY_AGENT_SETTLEMENT_ADMISSION",
    ):
        monkeypatch.delenv(key, raising=False)
    spend.reset_spend()
    yield
    spend.reset_spend()


def policy(**overrides):
    return InteractiveRepairBudget(
        **(
            dict(
                thread_id="thread",
                component_id="scene",
                source_revision=1,
                source_sha256="a" * 64,
            )
            | overrides
        )
    )


def configure(monkeypatch, tmp_path, cap="30"):
    monkeypatch.setenv("LLM_SPEND_EXPERIMENT_ID", "approved")
    monkeypatch.setenv("LLM_SPEND_EXPERIMENT_CAP_CNY", cap)
    monkeypatch.setenv("LLM_SPEND_INPUT_CNY_PER_MTOK", "1")
    monkeypatch.setenv("LLM_SPEND_OUTPUT_CNY_PER_MTOK", "1")
    monkeypatch.setenv("LLM_EXPERIMENT_ALLOWED_MODELS", "priced-model")
    path = tmp_path / "shared.db"
    monkeypatch.setenv("LLM_SPEND_LEDGER_DB", str(path))
    RuntimeDatabase(path).initialize()
    ledger = SpendLedger(path)
    ledger.ensure_experiment(
        "approved",
        cap_micros=int(float(cap) * 1000000),
        pricing_fingerprint=spend._pricing_fingerprint(),
        now="now",
    )
    return ledger


def reserve(key, tokens=600000, attempts=1):
    return spend.reserve_call(
        prompt_chars=0,
        max_tokens=tokens,
        attempts=attempts,
        model="priced-model",
        request_key=key,
        identity=spend.SpendIdentity(run_id=key, experiment="approved"),
    )


def test_no_configuration_refuses_repairs_but_ordinary_chat_is_unchanged():
    assert reserve("normal") == 0
    with repair_budget_scope(policy()), pytest.raises(spend.SpendConfigurationError):
        reserve("repair")
    assert current_repair_budget() is None
    assert reserve("normal-again") == 0


@pytest.mark.parametrize("missing", ["ledger", "experiment", "price", "model"])
def test_repair_cannot_create_or_invent_an_authorized_budget(
    monkeypatch, tmp_path, missing
):
    configure(monkeypatch, tmp_path)
    if missing == "ledger":
        path = tmp_path / "missing.db"
        monkeypatch.setenv("LLM_SPEND_LEDGER_DB", str(path))
    elif missing == "experiment":
        monkeypatch.setenv("LLM_SPEND_EXPERIMENT_ID", "not-approved")
    elif missing == "price":
        monkeypatch.delenv("LLM_SPEND_OUTPUT_CNY_PER_MTOK")
    else:
        monkeypatch.delenv("LLM_EXPERIMENT_ALLOWED_MODELS")
    with repair_budget_scope(policy()), pytest.raises(spend.SpendConfigurationError):
        reserve("blocked")
    if missing == "ledger":
        assert not path.exists()


def test_repair_call_cap_refuses_before_reservation(monkeypatch, tmp_path):
    ledger = configure(monkeypatch, tmp_path)
    with (
        repair_budget_scope(policy()),
        pytest.raises(SpendAdmissionRefused, match="call_cost"),
    ):
        reserve("too-large", tokens=1000001)
    assert ledger.experiment_spend("approved")["calls"] == 0


def test_revision_capabilities_and_restart_do_not_reset_the_component_group(
    monkeypatch, tmp_path
):
    ledger = configure(monkeypatch, tmp_path)
    with repair_budget_scope(policy()):
        assert reserve("one") == 0.6
    spend.reset_spend()  # A new server process must not regain the component quota.
    with repair_budget_scope(
        policy(source_revision=2, source_sha256="b" * 64, capabilities=("three",))
    ):
        assert reserve("two") == 0.6
    with (
        repair_budget_scope(policy(source_revision=3)),
        pytest.raises(SpendAdmissionRefused, match="call_limit"),
    ):
        reserve("three")
    assert ledger.experiment_spend("approved")["calls"] == 2
    stored = ledger.reserved_send("approved", "two")
    assert stored is not None
    metadata = json.loads(stored.identity)
    assert metadata["source_revision"] == 2
    assert metadata["source_sha256"] == "b" * 64
    assert metadata["capabilities"] == ["three"]
    with repair_budget_scope(policy(component_id="other")):
        assert reserve("other") == 0.6


def test_total_and_existing_global_caps_both_apply(monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path)
    with repair_budget_scope(policy(total_cny=1)):
        reserve("one")
        with pytest.raises(SpendAdmissionRefused, match="total_cost"):
            reserve("two")
    monkeypatch.setenv("LLM_SPEND_CAP_CNY", "0.7")
    with (
        repair_budget_scope(policy(component_id="other")),
        pytest.raises(spend.SpendLimitExceeded),
    ):
        reserve("global")


def test_sdk_retry_attempts_consume_the_call_limit(monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path)
    with repair_budget_scope(policy()):
        assert reserve("two-attempts", tokens=200000, attempts=2) == 0.4
        with pytest.raises(SpendAdmissionRefused, match="call_limit"):
            reserve("third-attempt", tokens=100000)


def test_guard_is_atomic_across_independent_ledger_connections(monkeypatch, tmp_path):
    ledger = configure(monkeypatch, tmp_path)
    chosen = policy()

    def attempt(number):
        try:
            ledger.reserve(
                "approved",
                request_key=str(number),
                amount_micros=600000,
                purpose=chosen.purpose,
                model="priced-model",
                identity=chosen.reservation_identity(str(number), "chat", 1),
                now="now",
                admission_guard=chosen.admission_guard(600000, 1),
            )
            return True
        except SpendAdmissionRefused:
            return False

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(attempt, range(4)))
    assert sum(results) == 2
    assert ledger.experiment_spend("approved")["reserved_micros"] == 1200000


def test_nested_scope_cannot_replace_policy():
    with repair_budget_scope(policy()), pytest.raises(ValueError, match="nested"):
        with repair_budget_scope(policy(component_id="another")):
            pass


def test_pre_reserved_send_cannot_bypass_the_repair_group(monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path)
    reserve("ordinary")
    authorization = spend.authorize_send(
        experiment_id="approved",
        request_key="ordinary",
        model="priced-model",
        prompt_chars=0,
        max_tokens=600000,
        attempts=1,
    )
    with (
        repair_budget_scope(policy()),
        spend.pre_reserved_send(authorization),
        pytest.raises(
            spend.SpendAuthorizationError, match="repair_reservation_missing"
        ),
    ):
        reserve("ordinary")


def test_repair_pre_reservation_is_not_double_charged(monkeypatch, tmp_path):
    ledger = configure(monkeypatch, tmp_path)
    with repair_budget_scope(policy()):
        reserve("repair")
        authorization = spend.authorize_send(
            experiment_id="approved",
            request_key="repair",
            model="priced-model",
            prompt_chars=0,
            max_tokens=600000,
            attempts=1,
        )
        with spend.pre_reserved_send(authorization):
            assert reserve("repair") == 0
    assert ledger.experiment_spend("approved")["calls"] == 1
