"""Guard tests to verify wechat module decoupling.

Phase 0: add guards, don't touch business logic yet.
Some assertions may be xfail until Phase 1 completes.
"""

from pathlib import Path


def test_wechat_service_should_not_depend_on_wechat_facade_after_refactor():
    text = Path("src/wechat_service.py").read_text(encoding="utf-8")
    assert "from src.wechat import" not in text


def test_wechat_facade_should_document_compatibility_only():
    text = Path("src/wechat.py").read_text(encoding="utf-8")
    assert "Compatibility facade for legacy imports" in text


def test_wechat_panel_should_not_import_wechat_facade():
    text = Path("src/ui/wechat_panel.py").read_text(encoding="utf-8")
    assert "from src.wechat import" not in text


def test_wechat_facade_has_no_runtime_logic():
    text = Path("src/wechat.py").read_text(encoding="utf-8")
    forbidden = [
        "def generate_wechat_opening",
        "def append_interactive_group_reply",
        "def reset_wechat_group",
        "GROUP_FILE =",
        "UNREAD_FILE =",
        "chat(",
        "stream_chat(",
    ]
    for token in forbidden:
        assert token not in text, f"Found forbidden token in wechat.py: {token}"
