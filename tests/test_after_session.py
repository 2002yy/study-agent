import pytest
import tempfile, shutil
from pathlib import Path
from src.update_validator import validate_updates
from src.safe_writer import safe_write_text, append_text_safely


def test_validator_rejects_emotion():
    bad = {"learner_profile_update": "用户学习时很焦虑，缺乏耐心"}
    warnings = validate_updates(bad)
    assert len(warnings) >= 1


def test_validator_rejects_overclaim():
    bad = {"progress_update": "v0.6 已完成视觉增强，v0.7 已上线"}
    warnings = validate_updates(bad)
    assert len(warnings) >= 1


def test_validator_rejects_too_long():
    bad = {"current_focus_update": "x" * 600}
    warnings = validate_updates(bad)
    assert len(warnings) >= 1


def test_validator_accepts_good():
    good = {
        "progress_update": "- 完成v0.5路由开发",
        "learner_profile_update": "本轮无需更新",
        "current_focus_update": "优先：自动路由",
    }
    warnings = validate_updates(good)
    assert len(warnings) == 0


def test_writer_appends_safely(tmp_path):
    f = tmp_path / "test.md"
    safe_write_text(f, "# 初始\n内容 A")
    append_text_safely(f, "内容 B")
    content = f.read_text(encoding="utf-8")
    assert "初始" in content
    assert "内容 B" in content
    assert content.index("内容 A") < content.index("内容 B")


def test_writer_backups_before_overwrite(tmp_path):
    f = tmp_path / "test_cf.md"
    safe_write_text(f, "# 旧焦点")
    # backup goes to project's backups/memory_backups/, not tmp_path
    from src.safe_writer import BACKUP_DIR as B

    before = len(list(B.glob("test_cf_*.bak")))
    safe_write_text(f, "# 新焦点")
    after = len(list(B.glob("test_cf_*.bak")))
    assert after > before
    for b in B.glob("test_cf_*.bak"):
        b.unlink()
