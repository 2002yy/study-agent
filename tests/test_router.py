from __future__ import annotations

from src.mode_manager import RuntimeModes
from src.router import route_request

VALID_MODES = {"普通", "苏格拉底", "费曼", "项目"}


def _modes() -> RuntimeModes:
    return RuntimeModes(performance_mode="fast")


def test_explicit_valid_mode_is_honored():
    route = route_request(
        user_input="我想理解数据库索引",
        selected_role="auto",
        selected_mode="苏格拉底",
        selected_model="auto",
        runtime_modes=_modes(),
    )
    assert route["mode"] == "苏格拉底"


def test_invalid_selected_mode_falls_back_to_auto_with_warning():
    route = route_request(
        user_input="我想理解数据库索引",
        selected_role="auto",
        selected_mode="苏格拉底?",  # illegal / mojibake-style value
        selected_model="auto",
        runtime_modes=_modes(),
    )
    # Must not leak the illegal value through to the engine.
    assert route["mode"] in VALID_MODES
    assert "invalid" in route["reason"].lower()
