"""The evaluation battery must refuse invalid runs instead of producing silent no-ops.

A missing env/model makes the agent burn rounds with zero searches and look like a
legitimate 0-result evaluation. This test pins the guard that fails loudly first.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path


def _battery():
    path = Path(__file__).resolve().parents[1] / "tools" / "m3_battery.py"
    spec = importlib.util.spec_from_file_location("m3_battery_under_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_invalid_when_env_file_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("STUDY_AGENT_ENV", str(tmp_path / "nope.env"))
    ok, reason = _battery().precheck()
    assert ok is False
    assert reason.startswith("env_file_missing")


def test_invalid_when_model_credentials_missing(monkeypatch, tmp_path):
    env = tmp_path / "ok.env"
    env.write_text("SEARXNG_BASE_URL=http://127.0.0.1:8080\n", encoding="utf-8")
    monkeypatch.setenv("STUDY_AGENT_ENV", str(env))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    ok, reason = _battery().precheck()
    assert ok is False
    assert reason == "model_credentials_missing"


def test_valid_with_env_file_and_key(monkeypatch, tmp_path):
    env = tmp_path / "ok.env"
    env.write_text("OPENAI_API_KEY=test-key\n", encoding="utf-8")
    monkeypatch.setenv("STUDY_AGENT_ENV", str(env))
    ok, reason = _battery().precheck()
    assert ok is True
    assert reason == "ok"


def test_main_returns_invalid_run_without_writing_traces(monkeypatch, tmp_path, capsys):
    """run_status=INVALID_RUN and a non-zero exit, with nothing persisted."""
    module = _battery()
    monkeypatch.setenv("STUDY_AGENT_ENV", str(tmp_path / "missing.env"))
    out = tmp_path / "out"
    monkeypatch.setattr(
        module.sys, "argv",
        ["m3_battery.py", "--budget", "default", "--only", "anchor-weiqi",
         "--out", str(out)],
    )
    code = module.main()
    assert code == 2
    assert out.exists() is False or not list(out.glob("*.json"))
    captured = capsys.readouterr().out
    assert "INVALID_RUN" in captured
