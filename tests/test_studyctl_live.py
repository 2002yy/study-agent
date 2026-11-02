from argparse import Namespace
from pathlib import Path

import pytest

from tools.studyctl_live import build_launcher_command, live_environment, plan_live, require_answer


def options(**extra):
    return Namespace(
        **{
            "budget_cny": 30.0,
            "artifact_dir": Path("artifacts/live"),
            "experiment_id": "same-budget",
            "config_path": Path("config.env"),
            "desktop_launcher": Path("launch.cmd"),
            "allow_paid": False,
            "dry_run": False,
            **extra,
        }
    )


def test_paid_check_is_not_implicitly_authorized():
    with pytest.raises(ValueError, match="allow-paid"):
        plan_live(options())


@pytest.mark.parametrize("budget", [None, 0, -1, float("nan"), float("inf")])
def test_live_check_requires_a_finite_cap(budget):
    with pytest.raises(ValueError, match="budget"):
        plan_live(options(budget_cny=budget, allow_paid=True))


def test_dry_run_only_describes_the_check_without_reading_credentials():
    result = plan_live(options(dry_run=True))
    assert result["execution"] == "not_started"
    assert result["budget_cny"] == 30
    assert "desktop_and_docker" in result["cases"]


def test_live_environment_overrides_unsafe_config_without_exposing_api_token(tmp_path):
    env = live_environment(
        {
            "LLM_PROVIDER_PROFILE": "deepseek",
            "DEEPSEEK_BASE_URL": "https://api.deepseek.com/v1",
            "LLM_SPEND_CAP_CNY": "9999",
            "LLM_MAX_RETRIES": "12",
            "VITE_STUDY_AGENT_API_TOKEN": "fake",
        },
        tmp_path,
        "same-budget",
        30,
    )
    assert env["LLM_SPEND_EXPERIMENT_CAP_CNY"] == "30"
    assert env["LLM_SPEND_EXPERIMENT_ID"] == "same-budget"
    assert Path(env["LLM_SPEND_LEDGER_DB"]).parent == tmp_path
    assert env["LLM_MAX_RETRIES"] == "0"
    assert "VITE_STUDY_AGENT_API_TOKEN" not in env


@pytest.mark.parametrize(
    "data", [{"reply": " "}, {"reply": "partial", "status": "interrupted"}]
)
def test_a_successful_http_response_without_a_completed_answer_is_not_a_pass(data):
    with pytest.raises(ValueError):
        require_answer(data)


def test_launcher_command_wraps_a_powershell_entry_instead_of_executing_it(tmp_path):
    """WinError 193: CreateProcess refuses a .ps1 as the image path."""
    command = build_launcher_command(
        tmp_path / "launch.ps1",
        tmp_path,
        tmp_path / ".env",
        "python.exe",
        18001,
        15174,
    )

    assert command[0] == "powershell.exe"
    assert command[1:5] == ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File"]
    assert command[5].endswith("launch.ps1")
    assert "-StartSearXNG" in command
    assert "-BackendPort" in command and "18001" in command


def test_launcher_command_runs_a_batch_entry_through_cmd(tmp_path):
    command = build_launcher_command(
        tmp_path / "launch.cmd",
        tmp_path,
        tmp_path / ".env",
        "python.exe",
        18001,
        15174,
    )

    assert command[:3] == ["cmd.exe", "/c", str(tmp_path / "launch.cmd")]
