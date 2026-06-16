"""LLM-based generation logic for WeChat group chat.

Split from src/wechat.py — Phase 3 decoupling.
"""

from __future__ import annotations

from src.llm_client import ModelProfile, chat, stream_chat
from src.mode_manager import load_runtime_modes
from src.performance_budget import (
    news_discussion_max_tokens,
    wechat_history_lines,
    wechat_opening_max_tokens,
    wechat_reply_max_tokens,
)
from src.role_manager import load_role
from src.wechat_format import (
    PERFORMANCE_STYLE_HINTS,
    ROLE_ID_TO_NAME,
    STYLE_PROMPTS,
    _ensure_all_roles_reply,
)
from src.wechat_prompt import load_interactive_prompt, load_system_prompt
from src.wechat_state import read_wechat_group, read_wechat_state


# ── Model profile resolution ──────────────────────────────────────────


def _resolve_model_profile(
    selected_model: str = "auto",
    performance_mode: str = "standard",
) -> ModelProfile:
    if performance_mode == "deep":
        return "pro"
    if performance_mode == "fast":
        return "flash"
    if selected_model == "pro":
        return "pro"
    return "flash"


# ── News discussion generator ─────────────────────────────────────────


def generate_wechat_news_discussion(
    news_digest: str,
    relationship_mode: str = "standard",
    performance_mode: str = "standard",
    selected_model: str = "auto",
) -> str:
    if not news_digest.strip():
        return ""

    model_profile = _resolve_model_profile(selected_model, performance_mode)
    messages = [
        {
            "role": "system",
            "content": (
                "你要根据一段当天新闻摘要，生成四位学习搭子的微信群讨论。"
                "必须由三月七、刻晴、纳西妲、流萤四位角色全部发言。"
                "每位角色都要引用或回应摘要里的具体新闻点，不能空泛安慰，不能只说套话。"
                "输出格式固定为【角色名】\\n内容。"
                "三月七偏轻松和反应，刻晴偏判断和重点，纳西妲偏分析和连接，流萤偏感受和收束。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"当前互动氛围：{relationship_mode}\n"
                f"当前性能模式：{performance_mode}\n\n"
                "请围绕下面这份新闻摘要展开群聊，不要假装用户刚刚发言。\n\n"
                f"{news_digest}"
            ),
        },
    ]
    raw = chat(
        messages,
        temperature=0.7,
        model_profile=model_profile,
        max_tokens=news_discussion_max_tokens(performance_mode),
        task_name="wechat_news_discussion",
    ).strip()
    return _ensure_all_roles_reply(raw)


# ── Interactive message builder ───────────────────────────────────────


def _build_interactive_messages(
    user_text: str,
    relationship_mode: str | None = None,
    rag_context: str = "",
) -> tuple[list[dict], bool]:
    modes = load_runtime_modes()
    if relationship_mode is None:
        relationship_mode = modes.relationship_mode

    is_first = not modes.first_reaction_done
    prompt = load_interactive_prompt()
    history = read_wechat_group()
    history_limit = wechat_history_lines(modes.performance_mode)
    history_lines = history.splitlines()[-history_limit:] if history else []

    if is_first:
        prompt += (
            "\n\n当前状态：这是这个群聊线程里用户第一次发言。"
            "请体现轻微惊讶和欢迎，但不要过度夸张。"
        )
    else:
        prompt += "\n\n当前状态：这不是第一次发言，请正常继续群聊互动。"

    if relationship_mode == "warm":
        prompt += "\n[互动氛围: warm] 更温和、更鼓励，但不进入恋爱感扮演。"
    elif relationship_mode == "close":
        prompt += (
            "\n[互动氛围: close] 可以更贴近更柔和，但不能生成成人内容，"
            "不能模拟现实恋人，不能削弱学习目标。"
        )

    if rag_context.strip() and "No relevant local documents retrieved" not in rag_context:
        prompt += (
            "\n\n[Retrieved local documents]\n"
            "下面是用户本地资料库检索到的引用片段。只有相关时才使用；"
            "如果使用，请保留引用编号，例如 [1]。\n"
            f"{rag_context.strip()}"
        )

    messages = [
        {"role": "system", "content": prompt},
        {
            "role": "user",
            "content": "【最近群聊】\n"
            + "\n".join(history_lines)
            + f"\n\n【用户刚才说】\n{user_text}\n\n请生成群聊回复。",
        },
    ]
    return messages, is_first


# ── WeChat message generation ─────────────────────────────────────────


def generate_wechat_messages(
    session_messages: list[dict],
    after_session_updates: dict[str, str],
    memory_bundle: dict[str, str],
    model_profile: ModelProfile = "flash",
    style: str = "标准",
    relationship_mode: str = "standard",
) -> str:
    if not after_session_updates:
        return ""

    context: list[str] = [
        load_system_prompt() + STYLE_PROMPTS.get(style, STYLE_PROMPTS["标准"])
    ]
    state = read_wechat_state()

    if relationship_mode == "warm":
        context.append(
            "\n[互动氛围: warm] 语气更温和、更鼓励，但仍然保持学习复盘导向。"
        )
    elif relationship_mode == "close":
        context.append(
            "\n[互动氛围: close] 可以更贴近、更温柔，但不能生成成人内容，不能模拟现实恋人，"
            "不能削弱学习目标。"
        )

    if state["user_has_joined"]:
        context.insert(0, "\n[系统说明] 用户已经在群聊里，可以直接对用户说话。")
    else:
        context.insert(0, "\n[系统说明] 当前更像课后反馈场景，不需要假定用户正在看。")

    update_keys = [
        ("session_archive_update", "本轮归档"),
        ("progress_update", "进度更新"),
        ("current_focus_update", "当前重点"),
    ]
    for key, label in update_keys:
        content = after_session_updates.get(key, "")
        if content and all(
            flag not in content for flag in ["失败", "无对话", "无需更新"]
        ):
            context.append(f"\n【{label}】\n{content[:400]}")

    if memory_bundle.get("summary.md"):
        context.append(f"\n【现有摘要参考】\n{memory_bundle['summary.md'][:300]}")

    context.append("\n【最近对话背景】")
    for msg in session_messages[-2:]:
        speaker = "用户" if msg["role"] == "user" else "Agent"
        context.append(f"{speaker}: {msg['content'][:100]}")

    messages = [
        {"role": "system", "content": "\n".join(context)},
        {
            "role": "user",
            "content": f"请生成一版 {style} 风格的微信群消息，每位角色用【角色名】开头。",
        },
    ]
    raw = chat(
        messages,
        temperature=0.6,
        model_profile=model_profile,
        max_tokens=wechat_reply_max_tokens(load_runtime_modes().performance_mode),
        task_name="wechat_after_session",
    ).strip()
    return _ensure_all_roles_reply(raw)


# ── Opening generation ────────────────────────────────────────────────


def generate_wechat_opening(
    role_hint: str = "auto",
    relationship_mode: str = "standard",
    performance_mode: str = "standard",
    selected_model: str = "auto",
) -> str:
    model_profile = _resolve_model_profile(selected_model, performance_mode)
    role_name = ROLE_ID_TO_NAME.get(role_hint, role_hint)
    role_prompt = ""
    if role_hint != "auto":
        role_prompt = load_role(role_hint)[:400]

    atmosphere_prompt = {
        "standard": "气氛自然、轻松、像学习搭子之间的日常接话。",
        "warm": "气氛更温和、更鼓励一点，但不要太煽情。",
        "close": "气氛更贴近、更有陪伴感，但依然清爽克制。",
    }.get(relationship_mode, "气氛自然、轻松。")

    system_prompt = (
        "你要生成一个微信群聊的开场片段。"
        "这是用户进入群聊前，四位角色彼此之间已经聊起来的一小段内容。"
        "必须四位角色全部发言，格式固定为【角色名】\\n内容。"
        "不要提到系统、模型、性能模式，不要出现说明文字。"
        "整体要像已经在聊，而不是正式欢迎词。"
        "四位角色不能提前知道用户会来、正在看、可能看到，不能对用户隔空说话。"
    )
    user_prompt = (
        f"当前角色偏好：{role_name}。\n"
        f"当前互动氛围：{relationship_mode}。{atmosphere_prompt}\n"
        f"当前性能模式：{performance_mode}。"
        f"{PERFORMANCE_STYLE_HINTS.get(performance_mode, PERFORMANCE_STYLE_HINTS['standard'])}\n"
        "请生成一轮四人开场群聊，让她们像刚刚已经在讨论学习、进度、状态或轻松复盘。\n"
        "如果当前角色不是自动，就让这位角色在气质上稍微更带头一点，但不要压过其他三位。\n"
        "不要出现用户，不要出现旁白，不要出现版本号，不要展开长剧情。\n"
        "禁止出现类似「如果你看到」「你要是来了」「你应该能看到」「把这里当成给你准备的地方」这类句子。"
    )
    if role_prompt:
        user_prompt += f"\n\n当前角色参考设定：\n{role_prompt}"

    opening = chat(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.8,
        model_profile=model_profile,
        max_tokens=wechat_opening_max_tokens(performance_mode),
        task_name="wechat_opening",
    ).strip()
    return _ensure_all_roles_reply(opening)


# ── Interactive reply generation ──────────────────────────────────────


def generate_interactive_wechat_reply(
    user_text: str,
    model_profile: ModelProfile = "flash",
    relationship_mode: str | None = None,
    rag_context: str = "",
    performance_mode: str | None = None,
) -> str:
    messages, _is_first = _build_interactive_messages(
        user_text,
        relationship_mode,
        rag_context,
    )
    raw = chat(
        messages,
        temperature=0.7,
        model_profile=model_profile,
        max_tokens=wechat_reply_max_tokens(performance_mode or load_runtime_modes().performance_mode),
        task_name="wechat_interactive",
    )
    return _ensure_all_roles_reply(raw.strip())


def generate_interactive_wechat_reply_stream(
    user_text: str,
    model_profile: ModelProfile = "flash",
    relationship_mode: str | None = None,
    rag_context: str = "",
    performance_mode: str | None = None,
):
    messages, is_first = _build_interactive_messages(
        user_text,
        relationship_mode,
        rag_context,
    )
    return (
        stream_chat(
            messages,
            temperature=0.7,
            model_profile=model_profile,
            max_tokens=wechat_reply_max_tokens(performance_mode or load_runtime_modes().performance_mode),
            task_name="wechat_interactive",
        ),
        is_first,
    )


def normalize_interactive_wechat_reply(content: str) -> str:
    return _ensure_all_roles_reply(content)
