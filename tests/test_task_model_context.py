import pytest

from src import memory
from src.mode_manager import RuntimeModes, build_runtime_profile
from src.model_stats import suggest_model_by_rules
from src.router import route_request


@pytest.mark.parametrize("legacy_mode", ["fast", "standard", "deep"])
def test_auto_model_follows_task_and_explicit_choice_wins(legacy_mode):
    modes = RuntimeModes(performance_mode=legacy_mode)
    for question, expected in [("谢谢", "flash"), ("排查代码报错", "pro")]:
        result = route_request(question, "auto", "auto", "auto", modes)
        assert result["model_profile"] == expected
        override = route_request(question, "auto", "auto", "flash", modes)
        assert override["model_profile"] == "flash"
    assert suggest_model_by_rules("分析架构代码", legacy_mode) == "pro"
    assert suggest_model_by_rules("简单闲聊", legacy_mode) == "flash"
    assert build_runtime_profile(modes).preferred_model is None
    assert build_runtime_profile(modes).context_mode == "light"


@pytest.mark.parametrize("scope", ["none", "unrecognized", "", "None"])
def test_disabled_or_unknown_memory_scope_never_reads_files(monkeypatch, scope):
    monkeypatch.setattr(memory, "read_memory_file", lambda _: pytest.fail("unexpected memory read"))
    assert memory.read_memory_bundle(scope) == {}
    from src.context_builder import build_messages

    messages = build_messages(
        "question", "role", "普通", {"index.md": "private biography"}, context_mode=scope
    )
    assert "private biography" not in str(messages)


def test_explicit_memory_scopes_still_read_only_their_named_files(monkeypatch):
    reads = []
    monkeypatch.setattr(memory, "read_memory_file", lambda name: reads.append(name) or name)
    assert set(memory.read_memory_bundle("fast")) == {"index.md", "current_focus.md"}
    assert reads == ["index.md", "current_focus.md"]


def test_memory_scope_settings_persist_without_changing_speed(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from src import api
    from src.api import app
    from src.application.helpers import resolve_context_mode

    monkeypatch.setattr(api, "FRONTEND_SETTINGS_PATH", tmp_path / "frontend.yaml")
    client = TestClient(app)
    original_speed = client.get("/runtime/settings").json()["settings"]["performance_mode"]
    response = client.patch("/runtime/settings", json={"context_mode": "none"})
    assert response.status_code == 200
    assert response.json()["settings"]["context_mode"] == "none"
    assert client.get("/runtime/settings").json()["settings"]["context_mode"] == "none"
    assert response.json()["settings"]["performance_mode"] == original_speed
    assert resolve_context_mode(None) == "none"
    assert resolve_context_mode("fast") == "fast"
    assert resolve_context_mode("unknown") == "none"
    assert client.patch("/runtime/settings", json={"context_mode": "unknown"}).status_code == 400
    assert client.get("/runtime/settings").json()["settings"]["context_mode"] == "none"
    assert client.patch("/runtime/settings", json={"context_mode": ""}).status_code == 200
    assert resolve_context_mode(None) == "light"
