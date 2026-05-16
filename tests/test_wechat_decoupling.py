"""Guard tests to verify wechat module decoupling.

Phase 0: add guards, don't touch business logic yet.
Some assertions may be xfail until Phase 1 completes.
"""

from pathlib import Path

import pytest


def test_wechat_service_should_not_depend_on_wechat_facade_after_refactor():
    text = Path("src/wechat_service.py").read_text(encoding="utf-8")
    assert "from src.wechat import" not in text


def test_wechat_facade_should_document_compatibility_only():
    text = Path("src/wechat.py").read_text(encoding="utf-8")
    assert "Re-exports are kept here for backward compatibility" in text


@pytest.mark.xfail(
    reason="wechat_panel.py still imports generation from src.wechat; deferred to later phase"
)
def test_ui_should_not_import_generation_from_wechat_facade_after_refactor():
    text = Path("src/ui/wechat_panel.py").read_text(encoding="utf-8")
    forbidden = [
        "generate_wechat_opening",
        "generate_interactive_wechat_reply_stream",
        "normalize_interactive_wechat_reply",
    ]
    for name in forbidden:
        assert name not in text
