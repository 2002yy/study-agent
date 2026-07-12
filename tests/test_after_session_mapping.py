from __future__ import annotations

from src.after_session import after_session_to_memory_updates


def test_maps_real_candidates_and_drops_placeholders():
    generated = {
        "progress_update": "理解了 B+Tree 减少扫描范围",
        "learner_profile_update": "偏好先举例再定义",
        "current_focus_update": "数据库索引的边界",
        "revision_notes_update": "（本轮无需更新）",
        "session_archive_update": "",
        "role_updates": "ignored",
    }
    updates = after_session_to_memory_updates(generated)
    targets = {u["target"]: u for u in updates}
    assert set(targets) == {"progress", "learner_profile", "current_focus"}
    assert targets["progress"]["append"] is True
    assert targets["current_focus"]["append"] is False
    assert targets["current_focus"]["content"] == "数据库索引的边界"
    assert all(u["learner_pending"] is False for u in updates)


def test_drops_parenthesized_and_failure_placeholders():
    generated = {
        "progress_update": "（无对话记录）",
        "learner_profile_update": "（LLM 调用失败，请稍后重试）",
        "current_focus_update": "（JSON 解析失败，需要人工检查）",
        "revision_notes_update": "（本轮无需更新）",
        "session_archive_update": "（占位）",
    }
    assert after_session_to_memory_updates(generated) == []


def test_returns_empty_when_all_blank():
    assert after_session_to_memory_updates({}) == []
