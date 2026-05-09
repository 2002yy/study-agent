from __future__ import annotations

from functools import lru_cache
from pathlib import Path

MEMORY_DIR = Path(__file__).resolve().parent.parent / "memory"

MEMORY_FILES = [
    "current_focus.md",
    "summary.md",
    "learner_profile.md",
    "progress.md",
    "project_context.md",
    "task_board.md",
    "agent.md",
    "system_detail.md",
]

CONTEXT_FILE_GROUPS = {
    "light": ["summary.md", "current_focus.md", "learner_profile.md"],
    "deep": [
        "summary.md",
        "current_focus.md",
        "learner_profile.md",
        "progress.md",
        "project_context.md",
        "task_board.md",
    ],
    "archive": MEMORY_FILES,
}


def _file_signature(path: Path) -> str:
    if not path.is_file():
        return "missing"
    stat = path.stat()
    return f"{stat.st_mtime_ns}:{stat.st_size}"


@lru_cache(maxsize=64)
def _read_text_file_cached(path_str: str, signature: str) -> str:
    path = Path(path_str)
    if not path.is_file():
        return f"[missing: {path.name}]"
    return path.read_text(encoding="utf-8").strip()


def read_text_file(path: Path) -> str:
    return _read_text_file_cached(str(path), _file_signature(path))


def read_memory_file(name: str) -> str:
    return read_text_file(MEMORY_DIR / name)


def extract_core_section(text: str, max_lines: int = 12) -> str:
    lines = [line.rstrip() for line in text.splitlines()]
    if len(lines) <= max_lines:
        return text.strip()
    return "\n".join(lines[:max_lines]).strip()


def read_memory_bundle(context_mode: str = "archive") -> dict[str, str]:
    file_list = CONTEXT_FILE_GROUPS.get(context_mode, CONTEXT_FILE_GROUPS["archive"])
    bundle: dict[str, str] = {}
    for name in file_list:
        content = read_memory_file(name)
        if context_mode == "light" and name == "learner_profile.md":
            content = extract_core_section(content)
        bundle[name] = content
    return bundle
