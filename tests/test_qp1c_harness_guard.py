"""The archived QP-1C harness must not spend money by default.

These are offline contracts: no model client is built, no search runs, no key is
read. They lock the rules a paid rerun has to satisfy after the P1 review.
"""

from __future__ import annotations

import os
import sys

import pytest

from tools import run_qp1c_query_planning_ab as harness


def run_main(monkeypatch, argv: list[str]) -> int:
    monkeypatch.setattr(sys, "argv", ["run_qp1c", *argv])
    return harness.main()


def test_default_run_is_offline_and_spends_nothing(monkeypatch, capsys):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("paid path must not be reached without --live")

    monkeypatch.setattr(harness, "_configure_spend_guard", forbidden)
    monkeypatch.setattr(
        "src.application.spend_admission_factory.build_settlement_admission", forbidden
    )

    assert run_main(monkeypatch, []) == 0
    assert "offline" in capsys.readouterr().out


def test_live_run_requires_an_experiment_identity(monkeypatch):
    monkeypatch.setenv("STUDY_AGENT_SETTLEMENT_ADMISSION", "1")

    with pytest.raises(SystemExit, match="experiment-id"):
        run_main(monkeypatch, ["--live", "--cap-cny", "1", "--ledger", "ledger.db"])


def test_live_run_requires_an_explicit_ledger(monkeypatch):
    monkeypatch.setenv("STUDY_AGENT_SETTLEMENT_ADMISSION", "1")

    with pytest.raises(SystemExit, match="ledger"):
        run_main(
            monkeypatch,
            ["--live", "--experiment-id", "qp1c-rerun", "--cap-cny", "1"],
        )


def test_live_run_requires_admission_to_be_enabled_by_the_operator(monkeypatch):
    monkeypatch.delenv("STUDY_AGENT_SETTLEMENT_ADMISSION", raising=False)

    with pytest.raises(SystemExit, match="STUDY_AGENT_SETTLEMENT_ADMISSION"):
        run_main(
            monkeypatch,
            [
                "--live",
                "--experiment-id",
                "qp1c-rerun",
                "--cap-cny",
                "1",
                "--ledger",
                "ledger.db",
            ],
        )


def test_a_stricter_caller_cap_is_never_relaxed(monkeypatch):
    monkeypatch.setenv("LLM_SPEND_CAP_CNY", "0.5")

    assert harness._effective_cap(3.0) == "0.5"


def test_the_requested_cap_is_used_when_none_is_set(monkeypatch):
    monkeypatch.delenv("LLM_SPEND_CAP_CNY", raising=False)

    assert harness._effective_cap(3.0) == "3.0"


def test_prices_already_configured_are_kept(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_SPEND_INPUT_CNY_PER_MTOK", "9")
    monkeypatch.setenv("LLM_EXPERIMENT_ALLOWED_MODELS", "deepseek-flash")
    monkeypatch.delenv("LLM_SPEND_OUTPUT_CNY_PER_MTOK", raising=False)
    monkeypatch.delenv("LLM_SPEND_CAP_CNY", raising=False)

    harness._configure_spend_guard(
        tmp_path / "ledger.db", experiment_id="qp1c-rerun", requested_cap_cny=3.0
    )

    assert os.environ["LLM_SPEND_INPUT_CNY_PER_MTOK"] == "9"
    assert os.environ["LLM_SPEND_OUTPUT_CNY_PER_MTOK"] == harness.OUTPUT_CNY_PER_MTOK
    assert os.environ["LLM_SPEND_EXPERIMENT_ID"] == "qp1c-rerun"


def test_configure_keeps_a_stricter_caller_cap(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_SPEND_CAP_CNY", "0.5")
    monkeypatch.setenv("LLM_EXPERIMENT_ALLOWED_MODELS", "deepseek-flash")

    harness._configure_spend_guard(
        tmp_path / "ledger.db", experiment_id="qp1c-rerun", requested_cap_cny=3.0
    )

    assert os.environ["LLM_SPEND_CAP_CNY"] == "0.5"
    assert os.environ["LLM_SPEND_EXPERIMENT_CAP_CNY"] == "0.5"
