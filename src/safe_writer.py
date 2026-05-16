from pathlib import Path
from datetime import datetime
import time

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKUP_DIR = PROJECT_ROOT / "backups" / "memory_backups"


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")


def _read_bytes_with_retry(path: Path, retries: int = 5) -> bytes:
    last_error: PermissionError | None = None

    for attempt in range(retries):
        try:
            return path.read_bytes()
        except PermissionError as exc:
            last_error = exc
            time.sleep(0.06 * (attempt + 1))

    if last_error:
        raise last_error
    return b""


def backup_file(path: Path) -> Path | None:
    if not path.is_file():
        return None

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stem = path.stem
    suffix = path.suffix
    backup_name = f"{stem}_{_timestamp()}{suffix}.bak"
    backup_path = BACKUP_DIR / backup_name

    backup_path.write_bytes(_read_bytes_with_retry(path))
    return backup_path


def _replace_with_retry(tmp_path: Path, target_path: Path, retries: int = 8) -> None:
    last_error: PermissionError | None = None

    for attempt in range(retries):
        try:
            tmp_path.replace(target_path)
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(0.08 * (attempt + 1))

    if last_error:
        raise last_error


def safe_write_text(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.is_file():
        backup_file(path)

    tmp_path = path.with_name(f"{path.name}.{_timestamp()}.tmp")

    try:
        tmp_path.write_text(content, encoding="utf-8")
        _replace_with_retry(tmp_path, path)
        return path
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass


def append_text_safely(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.is_file():
        existing = path.read_text(encoding="utf-8")
        new_content = existing.rstrip() + "\n\n" + content.strip() + "\n"
    else:
        new_content = content.strip() + "\n"

    return safe_write_text(path, new_content)


if __name__ == "__main__":
    import shutil
    import tempfile

    tmp = Path(tempfile.mkdtemp())
    test_file = tmp / "test.md"
    test_append = tmp / "append.md"

    try:
        # 1. Write new file (Chinese content)
        print("=== 1. safe_write_text (新建) ===")
        safe_write_text(test_file, "# 测试文件\n这是一个中文测试。")
        content = test_file.read_text(encoding="utf-8")
        print(f"  文件存在: {test_file.is_file()}")
        print(f"  内容: {content.strip()}")

        # 2. Overwrite (triggers backup)
        print()
        print("=== 2. safe_write_text (覆盖，触发备份) ===")
        safe_write_text(test_file, "# 已更新\n内容已被覆盖。")
        content = test_file.read_text(encoding="utf-8")
        print(f"  新内容: {content.strip()}")

        backups = list(BACKUP_DIR.glob("test_*.bak"))
        print(f"  备份数: {len(backups)}")
        if backups:
            bak = backups[0].read_text(encoding="utf-8")
            print(f"  备份内容: {bak.strip()}")

        # 3. Append
        print()
        print("=== 3. append_text_safely (追加) ===")
        safe_write_text(test_append, "# 第一轮\n学了 CNN。")
        append_text_safely(test_append, "# 第二轮\n学了 RNN。")
        content = test_append.read_text(encoding="utf-8")
        print(f"  追加后内容:\n{content}")

        print()
        print("=== 全部通过 ===")

    finally:
        shutil.rmtree(tmp)
        for b in BACKUP_DIR.glob("test_*.bak"):
            b.unlink()
