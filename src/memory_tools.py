"""记忆管理工具 — 搜索、回滚、编辑、diff、清理、归档"""

import shutil
from datetime import datetime
from pathlib import Path
from src.memory import read_memory_bundle, read_memory_file
from src.safe_writer import safe_write_text
from src.backup_manager import list_backups, restore_backup

MEMORY_DIR = Path(__file__).resolve().parent.parent / "memory"
ARCHIVE_DIR = MEMORY_DIR / "archives"
PROJECTS_DIR = MEMORY_DIR / "projects"


def search_memory(keyword: str) -> list[dict]:
    bundle = read_memory_bundle()
    results = []
    for name, content in bundle.items():
        if content.startswith("[文件不存在"):
            continue
        lines = content.split("\n")
        for i, line in enumerate(lines):
            if keyword.lower() in line.lower():
                ctx = lines[max(0, i - 1) : min(len(lines), i + 2)]
                results.append(
                    {"file": name, "line": i + 1, "context": " | ".join(ctx)[:120]}
                )
    return results


def edit_memory(file_name: str, content: str) -> str:
    target = MEMORY_DIR / file_name
    safe_write_text(target, content)
    return str(target)


def last_backup_info() -> dict | None:
    backups = list_backups()
    return backups[0] if backups else None


def rollback_last() -> str:
    backups = list_backups()
    if not backups:
        return "无可用备份"
    return restore_backup(backups[0]["name"])


def diff_with_backup(file_name: str) -> str:
    """比较当前文件与最近备份的差异"""
    current = read_memory_file(file_name)
    backups = list_backups()
    match = None
    orig = file_name.rsplit(".", 1)[0]
    for b in backups:
        if b["original"] == file_name:
            match = b
            break
    if not match:
        return f"无 {file_name} 的备份可供比较"
    from src.backup_manager import BACKUP_DIR

    old = (BACKUP_DIR / match["name"]).read_text(encoding="utf-8")
    added = sum(1 for l in current.split("\n") if l not in old.split("\n"))
    removed = sum(1 for l in old.split("\n") if l not in current.split("\n"))
    return f"+{added}/-{removed} 行 | 备份时间: {match['time']}"


def clean_progress(keep_lines: int = 50) -> str:
    """截断 progress.md，仅保留最近 N 行"""
    content = read_memory_file("progress.md")
    if content.startswith("[文件不存在"):
        return "progress.md 不存在"
    lines = content.split("\n")
    if len(lines) <= keep_lines:
        return f"无需清理 ({len(lines)} 行)"
    truncated = "\n".join(lines[-keep_lines:])
    safe_write_text(MEMORY_DIR / "progress.md", truncated + "\n")
    return f"已截断 progress.md: {len(lines)} -> {keep_lines} 行"


def archive_file(file_name: str) -> str:
    """归档 memory 文件到 archives/"""
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    content = read_memory_file(file_name)
    if content.startswith("[文件不存在"):
        return f"{file_name} 不存在"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    arch = ARCHIVE_DIR / f"{file_name.rsplit('.', 1)[0]}_{ts}.md"
    safe_write_text(arch, content)
    # Write empty template to original
    safe_write_text(
        MEMORY_DIR / file_name, f"# {file_name}\n\n（已归档至 archives/）\n"
    )
    return f"已归档: {arch}"


def ensure_project_dir(project: str) -> str:
    """确保按项目分目录存在"""
    d = PROJECTS_DIR / project
    d.mkdir(parents=True, exist_ok=True)
    return str(d)
