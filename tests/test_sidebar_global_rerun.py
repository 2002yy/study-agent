"""Tests for sidebar global rerun behavior.

Verifies that global-affecting sidebar operations use full-page rerun
instead of fragment-scoped rerun, and that settings changes clear stale routes.
"""

from pathlib import Path


def test_sidebar_has_rerun_app():
    text = Path("src/ui/sidebar.py").read_text(encoding="utf-8")
    assert "def _rerun_app():" in text
    assert "st.rerun()" in text


def test_sidebar_has_settings_changed_pure_function():
    text = Path("src/ui/sidebar.py").read_text(encoding="utf-8")
    assert "def _settings_changed(" in text


def test_no_fragment_rerun_in_sidebar():
    """All global-affecting operations must use _rerun_app, not fragment rerun."""
    text = Path("src/ui/sidebar.py").read_text(encoding="utf-8")
    assert 'st.rerun(scope="fragment")' not in text


def test_apply_settings_uses_rerun_app():
    text = Path("src/ui/sidebar.py").read_text(encoding="utf-8")
    lines = text.splitlines()
    apply_idx = None
    for i, line in enumerate(lines):
        if "if apply_settings:" in line.strip():
            apply_idx = i
            break
    assert apply_idx is not None, "apply_settings branch not found"
    found = any("_rerun_app()" in lines[j] for j in range(apply_idx, apply_idx + 50))
    assert found, "apply_settings block does not call _rerun_app()"


def test_apply_settings_clears_current_route():
    text = Path("src/ui/sidebar.py").read_text(encoding="utf-8")
    lines = text.splitlines()
    apply_idx = None
    for i, line in enumerate(lines):
        if "if apply_settings:" in line.strip():
            apply_idx = i
            break
    assert apply_idx is not None
    block = "\n".join(lines[apply_idx : apply_idx + 50])
    assert "anything_changed" in block
    assert "current_route" in block


def test_settings_changed_no_change():
    from src.ui.sidebar import _settings_changed

    assert not _settings_changed(
        "wechat", "march7", "auto", "flash", "standard", "standard",
        "wechat", "march7", "auto", "flash", "standard", "standard",
    )


def test_settings_changed_entry_mode():
    from src.ui.sidebar import _settings_changed

    assert _settings_changed(
        "single", "march7", "auto", "flash", "standard", "standard",
        "wechat", "march7", "auto", "flash", "standard", "standard",
    )


def test_settings_changed_role():
    from src.ui.sidebar import _settings_changed

    assert _settings_changed(
        "wechat", "keqing", "auto", "flash", "standard", "standard",
        "wechat", "march7", "auto", "flash", "standard", "standard",
    )


def test_settings_changed_mode():
    from src.ui.sidebar import _settings_changed

    assert _settings_changed(
        "wechat", "march7", "论文", "flash", "standard", "standard",
        "wechat", "march7", "auto", "flash", "standard", "standard",
    )


def test_settings_changed_model():
    from src.ui.sidebar import _settings_changed

    assert _settings_changed(
        "wechat", "march7", "auto", "pro", "standard", "standard",
        "wechat", "march7", "auto", "flash", "standard", "standard",
    )


def test_settings_changed_performance():
    from src.ui.sidebar import _settings_changed

    assert _settings_changed(
        "wechat", "march7", "auto", "flash", "deep", "standard",
        "wechat", "march7", "auto", "flash", "standard", "standard",
    )


def test_settings_changed_atmosphere():
    from src.ui.sidebar import _settings_changed

    assert _settings_changed(
        "wechat", "march7", "auto", "flash", "standard", "warm",
        "wechat", "march7", "auto", "flash", "standard", "standard",
    )
