"""Paid-run hard cap: reservations happen before the request, and fail closed."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.llm_spend_guard import (
    SpendConfigurationError,
    SpendLimitExceeded,
    remaining_cny,
    reserve_call,
    reset_spend,
    spent_cny,
)


@pytest.fixture(autouse=True)
def _clean_ledger(monkeypatch):
    reset_spend()
    for name in ("LLM_SPEND_CAP_CNY", "LLM_SPEND_INPUT_CNY_PER_MTOK",
                 "LLM_SPEND_OUTPUT_CNY_PER_MTOK", "LLM_SPEND_DEFAULT_MAX_TOKENS",
                 "LLM_SPEND_EXPERIMENT_ID", "LLM_SPEND_EXPERIMENT_CAP_CNY",
                 "LLM_SPEND_LEDGER_DB", "LLM_EXPERIMENT_ALLOWED_MODELS"):
        monkeypatch.delenv(name, raising=False)
    yield
    reset_spend()


def _configure(monkeypatch, cap="10", input_price="2", output_price="8"):
    monkeypatch.setenv("LLM_SPEND_CAP_CNY", cap)
    monkeypatch.setenv("LLM_SPEND_INPUT_CNY_PER_MTOK", input_price)
    monkeypatch.setenv("LLM_SPEND_OUTPUT_CNY_PER_MTOK", output_price)


def test_without_a_cap_nothing_is_reserved():
    assert reserve_call(prompt_chars=10_000, max_tokens=1_000, attempts=3) == 0.0
    assert spent_cny() == 0.0
    assert remaining_cny() is None


def test_a_cap_without_pricing_fails_closed(monkeypatch):
    monkeypatch.setenv("LLM_SPEND_CAP_CNY", "10")
    with pytest.raises(SpendConfigurationError):
        reserve_call(prompt_chars=10, max_tokens=10, attempts=1)


def test_reservations_accumulate_and_stop_before_the_cap(monkeypatch):
    _configure(monkeypatch, cap="0.0015", input_price="1", output_price="1")
    reserve_call(prompt_chars=1_000, max_tokens=100, attempts=1)  # 0.0011 CNY
    assert spent_cny() == pytest.approx(0.0011)
    with pytest.raises(SpendLimitExceeded):
        reserve_call(prompt_chars=1_000, max_tokens=100, attempts=1)


def test_retries_are_charged_up_front(monkeypatch):
    _configure(monkeypatch, cap="1", input_price="0", output_price="1")
    single = reserve_call(prompt_chars=0, max_tokens=1_000, attempts=1)
    reset_spend()
    triple = reserve_call(prompt_chars=0, max_tokens=1_000, attempts=3)
    assert triple == pytest.approx(single * 3)


def test_chat_request_builder_enforces_the_cap(monkeypatch):
    from src.llm_client import _build_request_kwargs

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("DEEPSEEK_MODEL_FLASH_NAME", "deepseek-flash")
    monkeypatch.setenv("DEEPSEEK_MODEL_PRO_NAME", "deepseek-v4-pro")
    _configure(monkeypatch, cap="0.0000005", input_price="1000", output_price="0")

    with pytest.raises(SpendLimitExceeded):
        _build_request_kwargs(
            messages=[{"role": "user", "content": "x" * 100}],
            temperature=0.0, model_profile="flash", provider_profile="deepseek",
            task_name="llm_router", max_tokens=10, timeout=5.0,
            response_format=None, stream=False,
        )


def test_vision_call_reserves_before_any_request(monkeypatch, tmp_path: Path):
    from src.application.attachment_vision import describe_image_with_deepseek

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("DEEPSEEK_MODEL_FLASH_NAME", "deepseek-flash")
    monkeypatch.setenv("DEEPSEEK_MODEL_PRO_NAME", "deepseek-v4-pro")
    _configure(monkeypatch, cap="0.001", input_price="1", output_price="1")

    image = tmp_path / "shot.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 4096)

    # The cap is exceeded, so the guard raises *before* any provider request.
    with pytest.raises(SpendLimitExceeded):
        describe_image_with_deepseek(image)


def test_capped_request_uses_the_same_output_bound_on_wire_and_in_ledger(monkeypatch):
    from src.llm_client import _build_request_kwargs
    from src.llm_spend_guard import SpendConfigurationError

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("DEEPSEEK_MODEL_FLASH_NAME", "deepseek-flash")
    _configure(monkeypatch, cap="1", input_price="0", output_price="1")
    monkeypatch.setenv("LLM_SPEND_DEFAULT_MAX_TOKENS", "128")
    base = dict(
        messages=[{"role": "user", "content": "test"}],
        temperature=0.0, model_profile="flash", provider_profile="deepseek",
        task_name="regular_chat", max_tokens=None, timeout=5.0,
        response_format=None, stream=False,
    )
    request = _build_request_kwargs(**base)
    assert request["max_tokens"] == 128
    assert spent_cny() >= 128 / 1_000_000
    with pytest.raises(SpendConfigurationError, match="positive"):
        _build_request_kwargs(**{**base, "max_tokens": 0})
    monkeypatch.delenv("LLM_SPEND_CAP_CNY")
    assert "max_tokens" not in _build_request_kwargs(**base)


def test_tool_schemas_and_assistant_arguments_are_charged(monkeypatch):
    from src.llm_client import _build_request_kwargs, _prompt_chars

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("DEEPSEEK_MODEL_FLASH_NAME", "deepseek-flash")
    _configure(monkeypatch, cap="0.001", input_price="1", output_price="0")
    base = dict(
        temperature=0.0, model_profile="flash", provider_profile="deepseek",
        task_name="tool_planner", max_tokens=16, timeout=5.0,
        response_format=None, stream=False,
    )
    with pytest.raises(SpendLimitExceeded):
        _build_request_kwargs(
            **base, messages=[{"role": "user", "content": "hi"}],
            tools=[{"type": "function", "function": {
                "name": "query", "description": "x" * 5000,
            }}],
        )
    reset_spend()
    with pytest.raises(SpendLimitExceeded):
        _build_request_kwargs(
            **base, messages=[{"role": "assistant", "content": "",
                "tool_calls": [{"id": "c1", "type": "function", "function": {
                    "name": "query", "arguments": "x" * 5000,
                }}]}],
        )
    assert _prompt_chars([{"role": "assistant", "tool_calls": [
        {"function": {"arguments": "x" * 100}}]}]) > 100


def test_tool_loop_rejects_oversized_schema_before_provider_call(monkeypatch):
    from src.llm_client import run_tool_loop
    from types import SimpleNamespace

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("DEEPSEEK_MODEL_FLASH_NAME", "deepseek-flash")
    _configure(monkeypatch, cap="0.001", input_price="1", output_price="0")
    sends = []
    class Fake:
        def create(self, **kwargs):
            sends.append(kwargs)
            raise AssertionError("budget check should run first")

    monkeypatch.setattr("src.llm_client.get_client", lambda **_: SimpleNamespace(
        chat=SimpleNamespace(completions=Fake()),
    ))
    with pytest.raises(SpendLimitExceeded):
        run_tool_loop(
            [{"role": "user", "content": "short"}],
            tools=[{"type": "function", "function": {
                "name": "huge", "description": "x" * 5000,
            }}],
            execute_tool=lambda name, args: {},
            model_profile="flash", provider_profile="deepseek",
        )
    assert sends == []
