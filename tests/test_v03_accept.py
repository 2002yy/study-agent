import pytest
from pathlib import Path
from src.memory import read_memory_file, read_memory_bundle
from src.role_manager import list_roles, load_role
from src.config import validate
from src.router import route_request
from src.mode_manager import RuntimeModes

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_memory_files_readable():
    for name in ["agent.md", "summary.md", "current_focus.md"]:
        content = read_memory_file(name)
        assert len(content) > 0, f"{name} 不可读"


def test_memory_bundle_has_keys():
    bundle = read_memory_bundle()
    for key in ["agent.md", "summary.md", "current_focus.md"]:
        assert key in bundle


def test_role_files_loadable():
    roles = list_roles()
    assert len(roles) == 4
    for r in roles:
        prompt = load_role(r)
        assert len(prompt) > 50, f"{r} prompt 过短"


def test_config_validation_no_crash():
    errors = validate()
    assert isinstance(errors, list)


def test_router_basic():
    modes = RuntimeModes(performance_mode="standard")
    r = route_request("为什么参数共享", "auto", "auto", "auto", modes)
    assert r["role"] == "nahida"
    assert r["model_profile"] == "pro"


def test_router_manual_override():
    modes = RuntimeModes(performance_mode="standard")
    r = route_request("论文怎么改", "march7", "苏格拉底", "flash", modes)
    assert r["role"] == "march7"
    assert r["manual_override"] is True


def test_router_returns_confidence():
    modes = RuntimeModes(performance_mode="standard")
    r = route_request("hello", "auto", "auto", "auto", modes)
    assert "confidence" in r
    assert "matched_keywords" in r
