import hashlib
import json

import pytest

from tools.m4c3_prepare import TASKS
from tools.m4c3_results import browser_environment, evaluate_artifacts


def test_browser_child_keeps_windows_paths_without_provider_secrets(monkeypatch):
    monkeypatch.setenv("SYSTEMDRIVE", "C:")
    monkeypatch.setenv("PROGRAMDATA", "C:/ProgramData")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-test-key")
    env = browser_environment({"M4C3_RAW_DIR": "fixture"})
    assert env["SYSTEMDRIVE"] == "C:"
    assert env["PROGRAMDATA"] == "C:/ProgramData"
    assert "DEEPSEEK_API_KEY" not in env


def corpus(tmp_path, mode="paid"):
    def save(path, data):
        path.write_text(json.dumps(data), encoding="utf-8")

    cases = [{"task_id": task, "status": "completed", "sent": True} for task in TASKS]
    save(tmp_path / "report.json", {"mode": mode, "cases": cases})
    html = b"<p>artifact</p>"
    (tmp_path / "document.html").write_bytes(html)
    item = {
        "case_id": "J01",
        "task_id": "J01",
        "file": "document.html",
        "sha256": hashlib.sha256(html).hexdigest(),
    }
    save(
        tmp_path / "index.json",
        {"purpose": "m4c3_first_generation", "generation_mode": mode, "cases": [item]},
    )
    for width in (1280, 390):
        directory = tmp_path / f"sandbox-{width}"
        directory.mkdir()
        save(
            directory / "report.json",
            {
                "source_generation_mode": mode,
                "historical_replay_only": False,
                "cases": [
                    item
                    | {
                        "viewport": {"width": width},
                        "screenshot": "page.png",
                        "checks": [{"status": "indeterminate"}],
                        "usability": [{"status": "pass"}],
                    }
                ],
            },
        )
    return tmp_path


def test_missing_semantic_evidence_is_not_counted_as_a_model_failure(tmp_path):
    result = evaluate_artifacts(corpus(tmp_path), render=False)
    assert result["counts"] == {
        "passed": 0,
        "failed": 11,
        "indeterminate": 1,
        "not_run": 0,
    }
    assert result["first_generation_success_rate"] is None
    assert result["success_rate_lower_bound"] == 0
    assert result["success_rate_upper_bound"] == 1 / 12


def test_fake_transport_cannot_establish_real_model_quality(tmp_path):
    result = evaluate_artifacts(corpus(tmp_path, "fake_http"), render=False)
    assert result["real_model_quality_data"] is False
    assert result["first_generation_success_rate"] is None
    assert result["success_rate_upper_bound"] is None


def test_one_missing_viewport_cannot_be_treated_as_a_pass(tmp_path):
    corpus(tmp_path)
    (tmp_path / "sandbox-390/report.json").unlink()
    with pytest.raises(ValueError, match="both viewport"):
        evaluate_artifacts(tmp_path, render=False)


def test_a_desktop_copy_cannot_substitute_for_mobile_observation(tmp_path):
    corpus(tmp_path)
    (tmp_path / "sandbox-390/report.json").write_bytes(
        (tmp_path / "sandbox-1280/report.json").read_bytes()
    )
    with pytest.raises(ValueError, match="stale browser evidence"):
        evaluate_artifacts(tmp_path, render=False)


def test_reused_browser_evidence_must_match_current_html_bytes(tmp_path):
    corpus(tmp_path)
    (tmp_path / "document.html").write_bytes(b"different HTML")
    with pytest.raises(ValueError, match="source document changed"):
        evaluate_artifacts(tmp_path, render=False)


def test_unsent_tasks_leave_the_batch_incomplete(tmp_path):
    corpus(tmp_path)
    path = tmp_path / "report.json"
    data = json.loads(path.read_text())
    data["cases"][0]["sent"] = False
    path.write_text(json.dumps(data))
    result = evaluate_artifacts(tmp_path, render=False)
    assert result["batch_complete"] is False
    assert result["counts"]["not_run"] == 1
    assert result["first_generation_success_rate"] is None
