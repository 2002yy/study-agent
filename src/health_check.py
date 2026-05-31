from __future__ import annotations

import os
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CACHE_TTL = 300
_cached_report: tuple[float, str] | None = None


def _check_writable(path: Path) -> bool:
    probe = path

    while not probe.exists():
        if probe.parent == probe:
            return False
        probe = probe.parent

    return os.access(probe, os.W_OK)


def _ensure_memory_files() -> list[str]:
    """Create minimal template memory files if they don't exist yet.

    Returns a list of newly-created file names.
    """
    memory_dir = PROJECT_ROOT / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)

    templates = {
        "summary.md": "# 项目摘要\n\n（等待首次使用后自动更新）\n",
        "current_focus.md": "# 当前焦点\n\n> 首次启动 — 尚无记录。\n",
        "learner_profile.md": "# 学习者档案\n\n> 首次启动 — 尚无记录。\n",
        "progress.md": "# 学习进度\n\n## 当前项目\n\n（新项目 — 等待首次使用）\n\n## 当前阶段\n\nv0.8.0\n",
        "project_context.md": "# 项目上下文\n\n## 项目\n\nStudy Agent\n",
        "task_board.md": "# 任务看板\n\n| 状态 | 任务 | 优先级 |\n|------|------|--------|\n| 待办 | — | — |\n",
        "index.md": "# 记忆索引\n\n- [summary](summary.md)\n",
    }

    created: list[str] = []
    for name, content in templates.items():
        path = memory_dir / name
        if not path.is_file():
            path.write_text(content, encoding="utf-8")
            created.append(name)
    return created


def light_health_report() -> list[str]:
    issues = []
    if not (PROJECT_ROOT / "app.py").is_file():
        issues.append("app.py missing")
    if not (PROJECT_ROOT / "src" / "config.py").is_file():
        issues.append("src/config.py missing")
    if not (PROJECT_ROOT / "memory" / "summary.md").is_file():
        issues.append("memory/summary.md missing")
    return issues


def run_health_check() -> list[dict]:
    checks = [
        ("app.py", (PROJECT_ROOT / "app.py").is_file(), "error"),
        ("src/config.py", (PROJECT_ROOT / "src" / "config.py").is_file(), "error"),
        ("memory/summary.md", (PROJECT_ROOT / "memory" / "summary.md").is_file(), "warn"),
        ("memory/current_focus.md", (PROJECT_ROOT / "memory" / "current_focus.md").is_file(), "warn"),
        ("memory/learner_profile.md", (PROJECT_ROOT / "memory" / "learner_profile.md").is_file(), "warn"),
        ("roles/march7.md", (PROJECT_ROOT / "roles" / "march7.md").is_file(), "warn"),
        ("roles/keqing.md", (PROJECT_ROOT / "roles" / "keqing.md").is_file(), "warn"),
        ("roles/nahida.md", (PROJECT_ROOT / "roles" / "nahida.md").is_file(), "warn"),
        ("roles/firefly.md", (PROJECT_ROOT / "roles" / "firefly.md").is_file(), "warn"),
        ("logs/sessions writable", _check_writable(PROJECT_ROOT / "logs" / "sessions"), "warn"),
        ("backups/memory_backups writable", _check_writable(PROJECT_ROOT / "backups" / "memory_backups"), "info"),
    ]
    return [{"name": name, "ok": ok, "level": level} for name, ok, level in checks]


def health_report(force_refresh: bool = False) -> str:
    global _cached_report
    now = time.time()
    if not force_refresh and _cached_report and now - _cached_report[0] < _CACHE_TTL:
        return _cached_report[1]

    results = run_health_check()
    failed = [item for item in results if not item["ok"]]
    lines = [
        "# Health Report",
        "",
        f"Total: {len(results)}",
        f"Passed: {len(results) - len(failed)}",
        f"Failed: {len(failed)}",
        "",
    ]
    if failed:
        for item in failed:
            lines.append(f"- [{item['level']}] {item['name']}")
    else:
        lines.append("- OK")

    report = "\n".join(lines)
    _cached_report = (now, report)
    return report
