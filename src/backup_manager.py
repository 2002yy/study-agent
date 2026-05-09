import shutil
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKUP_DIR = PROJECT_ROOT / "backups" / "memory_backups"
MEMORY_DIR = PROJECT_ROOT / "memory"


def list_backups() -> list[dict]:
    if not BACKUP_DIR.is_dir():
        return []
    backups = []
    for f in sorted(
        BACKUP_DIR.glob("*.bak"), key=lambda p: p.stat().st_mtime, reverse=True
    ):
        stem = f.stem  # e.g. "current_focus_20260507_000101.md"
        # Extract original filename
        parts = stem.rsplit("_", 2)
        original = parts[0] + ".md" if len(parts) >= 3 else stem
        backups.append(
            {
                "path": f,
                "original": original,
                "name": f.name,
                "time": datetime.fromtimestamp(f.stat().st_mtime).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "size": f.stat().st_size,
            }
        )
    return backups


def restore_backup(backup_name: str) -> str:
    backup_path = BACKUP_DIR / backup_name
    if not backup_path.is_file():
        raise FileNotFoundError(f"备份文件不存在: {backup_name}")

    stem = backup_path.stem
    parts = stem.rsplit("_", 2)
    original_name = parts[0] + ".md" if len(parts) >= 3 else stem + ".md"
    target = MEMORY_DIR / original_name

    # Backup current before restore
    if target.is_file():
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        pre_restore = BACKUP_DIR / f"{parts[0]}_{ts}_pre_restore.md.bak"
        shutil.copy2(target, pre_restore)

    shutil.copy2(backup_path, target)
    return str(target)


if __name__ == "__main__":
    backups = list_backups()
    print(f"备份目录: {BACKUP_DIR}")
    print(f"备份数量: {len(backups)}")
    print()
    if not backups:
        print("暂无备份。写入一次课后更新后会产生备份。")
        print()
        print("用法:")
        print("  python -m src.backup_manager          # 查看备份列表")
        print("  python -m src.backup_manager restore <文件名>  # 恢复")
    else:
        print("最近备份:")
        for b in backups[:5]:
            print(f"  {b['name']}")
            print(
                f"    原始文件: {b['original']}  时间: {b['time']}  大小: {b['size']}B"
            )
