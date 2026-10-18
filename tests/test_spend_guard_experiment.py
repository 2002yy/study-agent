"""Durable experiment budget seen from the guard: dual caps and fail-closed.

The ledger's own controls live in ``tests/test_spend_ledger_persistence.py``.
These cover the contract the guard must keep: both budgets apply, an
unidentified or unwritable call is refused instead of charged, and a process
without an experiment budget behaves exactly as before.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.infrastructure.sqlite.database import RuntimeDatabase
from src.infrastructure.sqlite.spend_ledger import SpendLedgerError
from src.llm_spend_guard import (
    SpendConfigurationError,
    SpendIdentity,
    SpendLedgerConflict,
    SpendLimitExceeded,
    compose_request_key,
    experiment_spend,
    reserve_call,
    reset_spend,
    spend_identity,
    spent_cny,
)

EXPERIMENT = "guard-experiment"


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


def _configure(monkeypatch, tmp_path: Path, *, cap="0.001", input_price="1", output_price="1"):
    database = tmp_path / "runtime.db"
    RuntimeDatabase(database).initialize()
    monkeypatch.setenv("LLM_SPEND_LEDGER_DB", str(database.resolve()))
    monkeypatch.setenv("LLM_SPEND_EXPERIMENT_ID", EXPERIMENT)
    monkeypatch.setenv("LLM_SPEND_EXPERIMENT_CAP_CNY", cap)
    monkeypatch.setenv("LLM_SPEND_INPUT_CNY_PER_MTOK", input_price)
    monkeypatch.setenv("LLM_SPEND_OUTPUT_CNY_PER_MTOK", output_price)
    return database


def _authorized(
    *, run_id: str = "run1", operation_id: str = "op1", experiment: str = EXPERIMENT
) -> SpendIdentity:
    """An identity the experiment declared as its own work."""

    return SpendIdentity(
        run_id=run_id,
        operation_id=operation_id,
        invocation="1",
        experiment=experiment,
    )


def _reserve(prompt_chars=1_000, max_tokens=100, *, key="run1|op1|llm|1"):
    return reserve_call(
        prompt_chars=prompt_chars,
        max_tokens=max_tokens,
        attempts=1,
        purpose="chat:deep_planner",
        model="deepseek-flash",
        request_key=key,
        identity=_authorized(),
    )


def test_without_an_experiment_budget_nothing_is_written(monkeypatch):
    monkeypatch.setenv("LLM_SPEND_CAP_CNY", "1")
    monkeypatch.setenv("LLM_SPEND_INPUT_CNY_PER_MTOK", "1")
    monkeypatch.setenv("LLM_SPEND_OUTPUT_CNY_PER_MTOK", "1")
    assert _reserve() > 0
    assert experiment_spend() is None  # no experiment identity at all


def test_an_unidentified_call_is_refused_not_charged(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    with pytest.raises(SpendConfigurationError):
        reserve_call(
            prompt_chars=1_000, max_tokens=100, attempts=1, purpose="chat:deep_planner"
        )
    assert spent_cny() == 0.0


def test_the_durable_budget_stops_the_call_at_its_cap(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path, cap="0.0015")
    _reserve(key="run1|op1|llm|1")
    with pytest.raises(SpendLimitExceeded):
        _reserve(key="run1|op1|llm|2")
    spend = experiment_spend(EXPERIMENT)
    assert spend is not None and spend["reserved_micros"] <= spend["cap_micros"]


def test_both_caps_apply_and_the_tighter_one_wins(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path, cap="10")
    # A tiny *process* cap still stops the call even though the experiment has room.
    monkeypatch.setenv("LLM_SPEND_CAP_CNY", "0.0015")
    _reserve(key="run1|op1|llm|1")
    with pytest.raises(SpendLimitExceeded):
        _reserve(key="run1|op1|llm|2")
    # ...and the experiment cap stops it even when the process cap is generous.
    # A different cap means a different experiment: the id is immutable by design.
    reset_spend()
    monkeypatch.setenv("LLM_SPEND_CAP_CNY", "10")
    monkeypatch.setenv("LLM_SPEND_EXPERIMENT_ID", "guard-experiment-tight")
    monkeypatch.setenv("LLM_SPEND_EXPERIMENT_CAP_CNY", "0.0015")
    reserve_call(
        prompt_chars=1_000,
        max_tokens=100,
        attempts=1,
        purpose="chat:deep_planner",
        model="deepseek-flash",
        request_key="run1|op1|llm|1",
        identity=_authorized(experiment="guard-experiment-tight"),
    )
    with pytest.raises(SpendLimitExceeded):
        reserve_call(
            prompt_chars=1_000,
            max_tokens=100,
            attempts=1,
            purpose="chat:deep_planner",
            model="deepseek-flash",
            request_key="run1|op1|llm|2",
            identity=_authorized(experiment="guard-experiment-tight"),
        )
    # 1500 micro-CNY cap, 1100 reserved by the first call: the second call needs
    # 1100 more, so it is refused with 400 still nominally left - the cap stops
    # the call that would cross it, not only the call that would empty it.
    tight = experiment_spend("guard-experiment-tight")
    assert tight["reserved_micros"] == 1100
    assert tight["remaining_micros"] == 400


def test_an_unwritable_ledger_refuses_instead_of_falling_back(monkeypatch, tmp_path):
    # A directory is not a database: the ledger cannot be opened or migrated.
    monkeypatch.setenv("LLM_SPEND_LEDGER_DB", str((tmp_path / "not-a-file").resolve()))
    monkeypatch.setenv("LLM_SPEND_EXPERIMENT_ID", EXPERIMENT)
    monkeypatch.setenv("LLM_SPEND_EXPERIMENT_CAP_CNY", "10")
    monkeypatch.setenv("LLM_SPEND_INPUT_CNY_PER_MTOK", "1")
    monkeypatch.setenv("LLM_SPEND_OUTPUT_CNY_PER_MTOK", "1")
    with pytest.raises(Exception) as excinfo:
        _reserve()
    assert not isinstance(excinfo.value, AssertionError)
    # Crucially: the process mirror did not silently absorb the call either.
    assert spent_cny() == 0.0


def test_a_relative_ledger_path_is_a_configuration_error(monkeypatch):
    monkeypatch.setenv("LLM_SPEND_LEDGER_DB", "relative/runtime.db")
    monkeypatch.setenv("LLM_SPEND_EXPERIMENT_ID", EXPERIMENT)
    monkeypatch.setenv("LLM_SPEND_EXPERIMENT_CAP_CNY", "10")
    monkeypatch.setenv("LLM_SPEND_INPUT_CNY_PER_MTOK", "1")
    monkeypatch.setenv("LLM_SPEND_OUTPUT_CNY_PER_MTOK", "1")
    with pytest.raises(SpendConfigurationError):
        _reserve()


def test_the_experiment_cap_cannot_be_widened_by_a_later_process(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path, cap="0.0015")
    _reserve(key="run1|op1|llm|1")
    # A new process (fresh mirror) that configured a bigger cap must be refused.
    reset_spend()
    monkeypatch.setenv("LLM_SPEND_EXPERIMENT_CAP_CNY", "10")
    with pytest.raises(SpendLedgerConflict):
        _reserve(key="run1|op1|llm|2")


def test_changing_prices_is_detected_instead_of_reusing_the_budget(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path, cap="10")
    _reserve(key="run1|op1|llm|1")
    reset_spend()
    monkeypatch.setenv("LLM_SPEND_INPUT_CNY_PER_MTOK", "99")
    with pytest.raises(SpendLedgerConflict):
        _reserve(key="run1|op1|llm|2")


def test_an_explicit_key_without_authorized_work_cannot_spend(monkeypatch, tmp_path):
    """Blocker 1: a bare request_key is not authorization.

    A structured call that names a key but belongs to no declared experiment work
    must not reserve anything - otherwise any non-empty string could spend the
    experiment budget.
    """

    _configure(monkeypatch, tmp_path)
    with pytest.raises(SpendConfigurationError):
        reserve_call(
            prompt_chars=1_000,
            max_tokens=100,
            attempts=1,
            purpose="research:claim_plan",
            model="deepseek-flash",
            request_key="gateway:call:1",
        )
    assert spent_cny() == 0.0
    # No row was created for the experiment either: an unauthorized call must not
    # even bring the experiment budget into existence.
    with pytest.raises(SpendLedgerError):
        experiment_spend(EXPERIMENT)


def test_work_declared_for_another_experiment_cannot_spend(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    with pytest.raises(SpendConfigurationError):
        reserve_call(
            prompt_chars=1_000,
            max_tokens=100,
            attempts=1,
            purpose="chat:deep_planner",
            model="deepseek-flash",
            request_key="run1|op1|llm|1",
            identity=SpendIdentity(
                run_id="run1", operation_id="op1", invocation="1", experiment="someone-else"
            ),
        )
    assert spent_cny() == 0.0


def test_the_bound_identity_composes_a_distinct_key_per_run():
    with spend_identity(
        run_id="run-a", operation_id="op1", invocation="1", experiment=EXPERIMENT
    ):
        first = compose_request_key(purpose="chat:deep_planner")
    with spend_identity(
        run_id="run-b", operation_id="op1", invocation="1", experiment=EXPERIMENT
    ):
        second = compose_request_key(purpose="chat:deep_planner")
    assert first != second
    assert "run-a" in first and "run-b" in second


def test_the_chat_entry_point_refuses_before_any_request(monkeypatch, tmp_path):
    from src.llm_client import _build_request_kwargs

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("DEEPSEEK_MODEL_FLASH_NAME", "deepseek-flash")
    monkeypatch.setenv("DEEPSEEK_MODEL_PRO_NAME", "deepseek-v4-pro")
    _configure(monkeypatch, tmp_path, cap="0.0000005", input_price="1000", output_price="0")
    with pytest.raises(SpendLimitExceeded):
        with spend_identity(
            run_id="run1", operation_id="op1", invocation="1", experiment=EXPERIMENT
        ):
            _build_request_kwargs(
                messages=[{"role": "user", "content": "x" * 100}],
                temperature=0.0,
                model_profile="flash",
                provider_profile="deepseek",
                task_name="llm_router",
                max_tokens=10,
                timeout=5.0,
                response_format=None,
                stream=False,
                request_key="run1|op1|llm_router|1",
            )


def test_the_vision_entry_point_refuses_before_any_request(monkeypatch, tmp_path):
    from src.application.attachment_vision import describe_image_with_deepseek

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("DEEPSEEK_MODEL_FLASH_NAME", "deepseek-flash")
    monkeypatch.setenv("DEEPSEEK_MODEL_PRO_NAME", "deepseek-v4-pro")
    _configure(monkeypatch, tmp_path, cap="0.0001", input_price="1", output_price="1")
    image = tmp_path / "shot.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 4096)
    with pytest.raises(SpendLimitExceeded):
        with spend_identity(
            run_id="run1", operation_id="op1", invocation="1", experiment=EXPERIMENT
        ):
            describe_image_with_deepseek(image, request_key="run1|op1|vision|1")
