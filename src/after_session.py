import json
import time
from src.llm_client import chat
from src.text_utils import strip_code_fences
from src.log_utils import get_logger
from src.task_events import TaskEventCallback, emit_task_event

SECTION_KEYS = [
    "progress_update",
    "learner_profile_update",
    "current_focus_update",
    "revision_notes_update",
    "session_archive_update",
    "role_updates",
]

SYSTEM_PROMPT = """你是一个学习系统的课后更新生成器。根据本轮对话，生成以下六部分更新建议。

请严格输出一个 JSON 对象，格式如下：

{
  "progress_update": "本轮完成了什么；当前进度推进到哪里；下次从哪里继续",
  "learner_profile_update": "本轮暴露的薄弱点；新发现的学习偏好；常见误区",
  "current_focus_update": "当前最优先任务；暂缓任务；明确禁止乱动的边界",
  "revision_notes_update": "哪些讲义/文档/代码需要补充；哪些地方以后要重讲",
  "session_archive_update": "本轮关键结论；重要决策；可归档的旧信息",
  "role_updates": {
    "march7": "三月七对本轮用户表现的观察：是否有启动困难、哪个瞬间想通了、下次可以从什么有趣角度切入",
    "keqing": "刻晴对本轮的观察：用户是否在次要问题上花太多时间、哪个目标需要压紧、下一步最优先",
    "nahida": "纳西妲对本轮的观察：用户是否混淆了概念层级、可以用什么类比帮用户理清结构",
    "firefly": "流萤对本轮的观察：用户是否有疲惫感、哪个卡住点其实已接近突破、下次收尾时可以说哪句话"
  }

规则：
1. 必须是合法 JSON，不要输出 markdown 代码块标记
2. 每个字段值是一个字符串，用分号分隔多个要点
3. 如果某部分无更新内容，写"本轮无需更新"
4. 不要重复对话原文，要提炼总结
5. 不要记录敏感信息，不要过度推断用户状态"""


def _build_markdown_preview(raw: str) -> str:
    if not raw or not raw.strip():
        return "（JSON 解析失败，且无有效输出）"

    lines = raw.strip().splitlines()
    preview_lines = [
        "### 课后更新（自动解析失败，以下为原始输出预览）",
        "",
        "> 模型未输出合法 JSON，已将原始文本转为可读预览。请人工确认并整理。",
        "",
    ]
    max_lines = 40
    shown = lines[:max_lines]
    for line in shown:
        preview_lines.append(line.strip() if line.strip() else "")
    if len(lines) > max_lines:
        preview_lines.append("")
        preview_lines.append(f"*(...共 {len(lines)} 行，已截断)*")

    return "\n".join(preview_lines)


def _extract_json_braces(text: str) -> dict | None:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or start >= end:
        return None
    candidate = text[start:end + 1]
    try:
        data = json.loads(candidate)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return None


def _parse_json(text: str) -> dict[str, str]:
    cleaned = strip_code_fences(text)

    try:
        data = json.loads(cleaned)
        if not isinstance(data, dict):
            raise ValueError("not a dict")
    except Exception:
        data = _extract_json_braces(text)
        if data is None:
            return {}

    result = {}
    for key in SECTION_KEYS:
        result[key] = str(data.get(key, "（本轮无需更新）"))
    return result


def generate_after_session_updates(
    session_messages: list[dict],
    memory_bundle: dict[str, str],
    role: str,
    mode: str,
    model_profile: str = "pro",
    event_callback: TaskEventCallback | None = None,
) -> dict[str, str]:
    started_at = time.perf_counter()
    emit_task_event(
        event_callback,
        "after_session",
        "started",
        data={
            "message_count": len(session_messages),
            "role": role,
            "mode": mode,
            "model_profile": model_profile,
        },
        started_at=started_at,
    )
    empty_result = {k: "（无对话记录）" for k in SECTION_KEYS}

    if not session_messages:
        emit_task_event(
            event_callback,
            "after_session",
            "completed",
            message="empty_session",
            started_at=started_at,
        )
        return empty_result

    context_lines = [SYSTEM_PROMPT]

    if memory_bundle:
        for filename, label in [
            ("progress.md", "当前进度"),
            ("learner_profile.md", "学习者档案"),
            ("current_focus.md", "当前焦点"),
        ]:
            content = memory_bundle.get(filename, "")
            if content and not content.startswith("[文件不存在"):
                context_lines.append(f"\n【参考：{label}】\n{content}")

    context_lines.append("\n【本轮对话】")
    for m in session_messages:
        role_name = "用户" if m["role"] == "user" else "Agent"
        context_lines.append(f"{role_name}: {m['content']}")

    full_prompt = "\n".join(context_lines)

    messages = [
        {"role": "system", "content": full_prompt},
        {
            "role": "user",
            "content": f"请为以上对话生成课后更新，输出 JSON。角色: {role}，模式: {mode}。",
        },
    ]

    try:
        emit_task_event(
            event_callback,
            "after_session",
            "progress",
            message="calling_llm",
            started_at=started_at,
        )
        raw = chat(
            messages,
            temperature=None,
            model_profile=model_profile,
            task_name="after_session",
        )
    except Exception as e:
        get_logger().warning("after_session chat failed: %s", e)
        emit_task_event(
            event_callback,
            "after_session",
            "failed",
            message=str(e),
            data={"error_type": type(e).__name__},
            started_at=started_at,
        )
        return {key: "（LLM 调用失败，请稍后重试）" for key in SECTION_KEYS}
    parsed = _parse_json(raw)

    if not parsed:
        preview = _build_markdown_preview(raw)
        emit_task_event(
            event_callback,
            "after_session",
            "completed",
            message="json_parse_failed",
            data={"parsed": False},
            started_at=started_at,
        )
        return {
            "progress_update": "（JSON 解析失败，需要人工检查）",
            "learner_profile_update": "（JSON 解析失败，需要人工检查）",
            "current_focus_update": "（JSON 解析失败，需要人工检查）",
            "revision_notes_update": "（JSON 解析失败，需要人工检查）",
            "session_archive_update": preview,
        }

    # Fill any missing keys
    for key in SECTION_KEYS:
        if key not in parsed:
            parsed[key] = "（本轮无需更新）"

    emit_task_event(
        event_callback,
        "after_session",
        "completed",
        data={"parsed": True, "section_count": len(parsed)},
        started_at=started_at,
    )
    return parsed


def apply_role_updates(role_updates: dict) -> list[str]:
    """将角色观察写入 roles/*.md 的「对用户当前印象」区"""
    from pathlib import Path
    from src.safe_writer import safe_write_text

    ROOT = Path(__file__).resolve().parent.parent
    updated = []
    for role_id, observation in role_updates.items():
        if not observation or observation == "本轮无需更新":
            continue
        target = ROOT / "roles" / f"{role_id}.md"
        if not target.is_file():
            continue
        content = target.read_text(encoding="utf-8")
        marker = "### 对用户当前印象"
        new_content = f"{marker}\n\n{observation}"
        if marker in content:
            # Replace existing impression
            idx = content.index(marker)
            end = content.find("\n### ", idx + len(marker))
            if end == -1:
                end = len(content)
            content = content[:idx] + new_content + content[end:]
        else:
            content += "\n\n" + new_content
        safe_write_text(target, content.strip() + "\n")
        updated.append(role_id)
    return updated
