"""Map legacy learning-closure results into current memory update candidates.

The old standalone after-session model generator and role-file writer are
retired. ``LearningClosureService`` owns generation and durable commits.
"""

from __future__ import annotations


_AFTER_SESSION_TARGETS = {
    "progress_update": ("progress", True),
    "learner_profile_update": ("learner_profile", True),
    "current_focus_update": ("current_focus", False),
    "revision_notes_update": ("revision_notes", True),
    "session_archive_update": ("session_archive", True),
}

_PLACEHOLDER_MARKERS = (
    "（本轮无需更新）",
    "（无对话记录）",
    "（LLM 调用失败",
    "（JSON 解析失败",
)


def after_session_to_memory_updates(generated: dict[str, str]) -> list[dict]:
    """Keep real legacy-format candidates; discard failure/empty placeholders."""
    updates: list[dict] = []
    for key, (target, append) in _AFTER_SESSION_TARGETS.items():
        content = str(generated.get(key, "")).strip()
        if not content or any(marker in content for marker in _PLACEHOLDER_MARKERS):
            continue
        if content.startswith("（") and content.endswith("）"):
            continue
        updates.append(
            {
                "target": target,
                "content": content,
                "append": append,
                "learner_pending": False,
            }
        )
    return updates
