"""The experiment budget must cover the *real* Deep research call chain.

The ledger controls prove the storage; these prove the production wiring: a Deep
research run reserves through the planner's paid call, and raising the retry
budget raises the reservation. Provider traffic is faked, so nothing is paid.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.infrastructure.sqlite.database import RuntimeDatabase
from src.llm_spend_guard import (
    SpendLimitExceeded,
    experiment_spend,
    reset_spend,
    spend_scope,
)
from src.web.research.deep_planner import ModelDeepPlanner

EXPERIMENT = "production-wiring"


class _FakeCompletions:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(self.payload)))]
        )


class _FakeClient:
    def __init__(self, payload: dict) -> None:
        self.completions = _FakeCompletions(payload)

    def with_options(self, **_kwargs):
        return self

    @property
    def chat(self):
        return SimpleNamespace(completions=self.completions)


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
    """Resolvable provider profiles; the client itself is always faked."""

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("MODEL_FLASH_NAME", "fake-flash")
    monkeypatch.setenv("MODEL_PRO_NAME", "fake-pro")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("DEEPSEEK_MODEL_FLASH_NAME", "fake-flash")
    monkeypatch.setenv("DEEPSEEK_MODEL_PRO_NAME", "fake-pro")


def _budget(monkeypatch, tmp_path: Path, *, cap="10", experiment=EXPERIMENT):
    database = tmp_path / f"{experiment}.db"
    RuntimeDatabase(database).initialize()
    monkeypatch.setenv("LLM_SPEND_LEDGER_DB", str(database.resolve()))
    monkeypatch.setenv("LLM_SPEND_EXPERIMENT_ID", experiment)
    monkeypatch.setenv("LLM_SPEND_EXPERIMENT_CAP_CNY", cap)
    monkeypatch.setenv("LLM_SPEND_INPUT_CNY_PER_MTOK", "1")
    monkeypatch.setenv("LLM_SPEND_OUTPUT_CNY_PER_MTOK", "1")
    return database


def test_the_deep_planner_paid_call_is_charged_to_the_bound_run(monkeypatch, tmp_path):
    """The production chain (planner -> llm_client.chat -> guard) must reserve.

    This is the control the review asked for: it starts at the planner, not at
    ``reserve_call``, so a missing identity in production would fail here.
    """

    _budget(monkeypatch, tmp_path)
    fake = _FakeClient({"sub_questions": ["photoshop 自动化接口"]})
    monkeypatch.setattr("src.llm_client.get_client", lambda **_: fake)
    _provider_env(monkeypatch)

    planner = ModelDeepPlanner()
    with spend_scope(
        run_id="web_lookup_run42",
        operation_id="op42",
        purpose="deep_research",
        experiment=EXPERIMENT,
    ):
        raw = planner.plan("photoshop", {})

    # plan() returns the parsed sub-questions; the point is that the paid call
    # behind it went through the guard.
    assert raw == ["photoshop 自动化接口"]
    assert len(fake.completions.calls) == 1
    spend = experiment_spend(EXPERIMENT)
    assert spend is not None
    assert spend["calls"] == 1
    assert spend["reserved_micros"] > 0


def test_an_exhausted_budget_stops_the_planner_before_any_request(monkeypatch, tmp_path):
    _budget(monkeypatch, tmp_path, cap="0.0000001")
    fake = _FakeClient({"sub_questions": []})
    monkeypatch.setattr("src.llm_client.get_client", lambda **_: fake)
    _provider_env(monkeypatch)

    planner = ModelDeepPlanner()
    with pytest.raises(SpendLimitExceeded):
        with spend_scope(
            run_id="web_lookup_run43",
            operation_id="op43",
            purpose="deep_research",
            experiment=EXPERIMENT,
        ):
            planner.plan("photoshop", {})
    assert fake.completions.calls == []


def test_a_paid_call_without_a_scope_is_refused(monkeypatch, tmp_path):
    """Fail-closed stays: an unnamed call must not be charged to the experiment."""

    from src.llm_spend_guard import SpendConfigurationError, reserve_call

    _budget(monkeypatch, tmp_path)
    with pytest.raises(SpendConfigurationError):
        reserve_call(prompt_chars=100, max_tokens=10, attempts=1, purpose="chat:llm_router")


def test_raising_the_retry_budget_raises_the_reservation(monkeypatch, tmp_path):
    """The reservation must follow the retries the SDK will really use."""

    from src.llm_client import _build_request_kwargs

    _provider_env(monkeypatch)

    def reserve_with(experiment: str, request_max_retries: int | None) -> int:
        _budget(monkeypatch, tmp_path, experiment=experiment)
        with spend_scope(
            run_id=f"run-{experiment}",
            operation_id="op",
            purpose="p",
            experiment=experiment,
        ):
            _build_request_kwargs(
                messages=[{"role": "user", "content": "x" * 1_000}],
                temperature=0.0,
                model_profile="flash",
                provider_profile="deepseek",
                task_name="llm_router",
                max_tokens=100,
                timeout=5.0,
                response_format=None,
                stream=False,
                request_max_retries=request_max_retries,
            )
        return experiment_spend(experiment)["reserved_micros"]

    default = reserve_with("retry-default", None)
    six = reserve_with("retry-six", 5)
    # 6 attempts versus the provider's configured attempts (2 retries -> 3): 2x.
    assert six > default
    assert six == default * 2


_CHILD = """
import sys, time
sys.path.insert(0, r"{root}")
from src.llm_spend_guard import SpendLimitExceeded, reserve_call, spend_identity
deadline = float(sys.argv[2])
while time.time() < deadline:
    time.sleep(0.001)
try:
    with spend_identity(
        run_id=sys.argv[3], operation_id="op", invocation="1", experiment=sys.argv[4]
    ):
        reserve_call(
            prompt_chars=1000, max_tokens=100, attempts=1,
            purpose="race", model="m", request_key=sys.argv[1],
        )
except SpendLimitExceeded:
    print("REFUSED")
else:
    print("RESERVED")
"""


def test_two_processes_racing_the_same_boundary_start_together(tmp_path, monkeypatch):
    """A real race: both children start at the same instant, one may win.

    The earlier version ran the children one after another, which proved
    persistence but not that ``BEGIN IMMEDIATE`` serialises a genuine race.
    """

    import os
    import time

    root = Path(__file__).resolve().parents[1]
    database = tmp_path / "race.db"
    RuntimeDatabase(database).initialize()
    # monkeypatch, not os.environ: a leaked experiment id would silently change
    # what every later test in the same session is measuring.
    monkeypatch.setenv("LLM_SPEND_LEDGER_DB", str(database.resolve()))
    monkeypatch.setenv("LLM_SPEND_EXPERIMENT_ID", "race-experiment")
    monkeypatch.setenv("LLM_SPEND_EXPERIMENT_CAP_CNY", "0.0021")
    monkeypatch.setenv("LLM_SPEND_INPUT_CNY_PER_MTOK", "1")
    monkeypatch.setenv("LLM_SPEND_OUTPUT_CNY_PER_MTOK", "1")
    reset_spend()

    # 0.0021 CNY cap; each reservation is 0.0011, so exactly one of the two fits.
    from src.llm_spend_guard import reserve_call

    with spend_scope(
        run_id="warm", operation_id="op", purpose="warm", experiment="race-experiment"
    ):
        pass
    script = _CHILD.format(root=str(root))
    deadline = time.time() + 2.0
    env = {**os.environ, "PYTHONPATH": str(root)}
    children = [
        subprocess.Popen(
            [sys.executable, "-c", script, f"race-{index}", str(deadline), f"run-{index}", "race-experiment"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        for index in (1, 2)
    ]
    outcomes = []
    for child in children:
        out, err = child.communicate(timeout=120)
        assert child.returncode == 0, err
        outcomes.append(out.strip().splitlines()[-1])
    assert sorted(outcomes) == ["REFUSED", "RESERVED"], outcomes
    spend = experiment_spend("race-experiment")
    assert spend["reserved_micros"] <= spend["cap_micros"]
    assert spend["calls"] == 1
    del reserve_call
