"""Actual file-write and backup guarantees, independent of legacy LLM helpers."""

from __future__ import annotations

from src import safe_writer


def test_append_preserves_existing_content_and_creates_backup(tmp_path, monkeypatch):
    backups = tmp_path / "backups"
    monkeypatch.setattr(safe_writer, "BACKUP_DIR", backups)
    target = tmp_path / "progress.md"

    safe_writer.safe_write_text(target, "# 初始\n内容 A")
    safe_writer.append_text_safely(target, "内容 B")

    content = target.read_text(encoding="utf-8")
    assert content.index("内容 A") < content.index("内容 B")
    snapshots = list(backups.glob("progress_*.bak"))
    assert len(snapshots) == 1
    assert snapshots[0].read_text(encoding="utf-8") == "# 初始\n内容 A"


def test_overwrite_backups_original_before_replacing(tmp_path, monkeypatch):
    backups = tmp_path / "backups"
    monkeypatch.setattr(safe_writer, "BACKUP_DIR", backups)
    target = tmp_path / "current_focus.md"

    safe_writer.safe_write_text(target, "# 旧焦点")
    safe_writer.safe_write_text(target, "# 新焦点")

    assert target.read_text(encoding="utf-8") == "# 新焦点"
    snapshots = list(backups.glob("current_focus_*.bak"))
    assert len(snapshots) == 1
    assert snapshots[0].read_text(encoding="utf-8") == "# 旧焦点"
