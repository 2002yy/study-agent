"""长期记忆写入统一入口。

写入层级：
  app.py → memory_writer → safe_writer → 文件
  app.py → mode_manager._write_keyvalue → 状态文件

所有 memory/ 和 logs/ 下的正式写入都通过本模块，附带权限检查。
"""

from pathlib import Path
from src.safe_writer import safe_write_text, append_text_safely
from src.mode_manager import load_runtime_modes, is_memory_write_allowed

ROOT = Path(__file__).resolve().parent.parent

MEMORY_TARGETS = {
    "summary": ROOT / "memory" / "summary.md",
    "progress": ROOT / "memory" / "progress.md",
    "current_focus": ROOT / "memory" / "current_focus.md",
    "learner_profile": ROOT / "memory" / "learner_profile.md",
    "project_context": ROOT / "memory" / "project_context.md",
    "revision_notes": ROOT / "logs" / "revision_notes.md",
    "session_archive": ROOT / "logs" / "session_archive.md",
}


def _check_write_permission() -> str | None:
    modes = load_runtime_modes()
    if not is_memory_write_allowed(modes):
        if modes.safe_mode:
            return "安全模式，禁止写入"
        return f"不允许写入 (mode={modes.memory_mode})"
    return None


def write_current_focus(content: str) -> str:
    err = _check_write_permission()
    if err:
        return f"[{err}]"
    safe_write_text(MEMORY_TARGETS["current_focus"], content + "\n")
    return str(MEMORY_TARGETS["current_focus"])


def append_memory(target: str, content: str, *, learner_pending: bool = False) -> str:
    err = _check_write_permission()
    if err:
        return f"[{err}]"
    file = MEMORY_TARGETS.get(target)
    if not file:
        return f"[未知目标: {target}]"
    if learner_pending:
        content = f"### 待确认观察\n\n{content}"
    else:
        content = f"## 课后更新\n\n{content}"
    append_text_safely(file, content)
    return str(file)
