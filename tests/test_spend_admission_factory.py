"""CL-M3-S2-B1-2a: the assembly is off by default and refuses half a chain.

Every case here is a configuration that would look fine at import time and fail
only when money moved: no experiment, no cap, no prices, a model the experiment
does not pay for, an attempt budget of zero, a ledger path that disagrees with
the audit store. The factory's job is to refuse them before a send.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.application.spend_admission_factory import (
    ASSEMBLY_FLAG,
    AdmissionConfigError,
    SettlementAdmission,
    build_settlement_admission,
    settlement_admission_enabled,
)
from src.infrastructure.sqlite.database import RuntimeDatabase

EXPERIMENT = "factory-experiment"


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
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


def _configure(monkeypatch, tmp_path: Path) -> Path:
    database = tmp_path / "runtime.sqlite"
    RuntimeDatabase(database).initialize()
    monkeypatch.setenv(ASSEMBLY_FLAG, "1")
    monkeypatch.setenv("LLM_SPEND_LEDGER_DB", str(database.resolve()))
    monkeypatch.setenv("LLM_SPEND_EXPERIMENT_ID", EXPERIMENT)
    monkeypatch.setenv("LLM_SPEND_EXPERIMENT_CAP_CNY", "10")
    monkeypatch.setenv("LLM_SPEND_INPUT_CNY_PER_MTOK", "1")
    monkeypatch.setenv("LLM_SPEND_OUTPUT_CNY_PER_MTOK", "1")
    return database


@pytest.mark.parametrize("value", ["", "0", "no", "off", "FALSE"])
def test_anything_but_an_explicit_affirmative_is_off(monkeypatch, value):
    monkeypatch.setenv(ASSEMBLY_FLAG, value)
    assert settlement_admission_enabled() is False
    assert build_settlement_admission(model="deepseek-chat") is None


def test_an_unset_flag_builds_nothing(monkeypatch):
    assert settlement_admission_enabled() is False
    assert build_settlement_admission(model="deepseek-chat") is None


def test_a_complete_configuration_builds_a_chain(monkeypatch, tmp_path):
    database = _configure(monkeypatch, tmp_path)
    admission = build_settlement_admission(model="deepseek-chat", attempts=2)
    assert isinstance(admission, SettlementAdmission)
    assert admission.ledger_path == str(database.resolve())
    assert admission.experiment_id == EXPERIMENT
    assert admission.model == "deepseek-chat"
    assert admission.attempts == 2
    assert callable(getattr(admission.adapter, "claim_send_authorization", None))


def test_the_chain_refuses_a_missing_experiment(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    monkeypatch.delenv("LLM_SPEND_EXPERIMENT_ID")
    with pytest.raises(AdmissionConfigError) as refused:
        build_settlement_admission(model="deepseek-chat")
    assert refused.value.reason == "experiment_not_configured"


def test_the_chain_refuses_a_missing_cap(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    monkeypatch.delenv("LLM_SPEND_EXPERIMENT_CAP_CNY")
    with pytest.raises(AdmissionConfigError) as refused:
        build_settlement_admission(model="deepseek-chat")
    assert refused.value.reason == "cap_not_configured"


def test_the_chain_refuses_missing_prices(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    monkeypatch.delenv("LLM_SPEND_INPUT_CNY_PER_MTOK")
    with pytest.raises(AdmissionConfigError) as refused:
        build_settlement_admission(model="deepseek-chat")
    assert refused.value.reason == "pricing_not_configured"


def test_the_chain_refuses_an_unknown_model(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    monkeypatch.setenv("LLM_EXPERIMENT_ALLOWED_MODELS", "some-other-model")
    with pytest.raises(AdmissionConfigError) as refused:
        build_settlement_admission(model="deepseek-chat")
    assert refused.value.reason == "model_not_allowed"


@pytest.mark.parametrize("attempts", [0, -1, True, 1.5, "2"])
def test_the_chain_refuses_an_impossible_attempt_budget(monkeypatch, tmp_path, attempts):
    _configure(monkeypatch, tmp_path)
    with pytest.raises(AdmissionConfigError) as refused:
        build_settlement_admission(model="deepseek-chat", attempts=attempts)
    assert refused.value.reason == "attempts_invalid"


def test_the_chain_refuses_a_missing_model(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    with pytest.raises(AdmissionConfigError) as refused:
        build_settlement_admission(model="  ")
    assert refused.value.reason == "model_not_configured"


def test_the_chain_reports_the_audit_store_it_built(monkeypatch, tmp_path):
    database = _configure(monkeypatch, tmp_path)
    admission = build_settlement_admission(model="deepseek-chat")
    assert admission is not None
    assert Path(admission.settlements.database_path) == Path(database.resolve())
