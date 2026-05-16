"""WeChat group chat, news search, digest generation, and group management.

This module has been split into sub-modules:
  - src/wechat_format.py        — pure text/formatting utilities
  - src/news/link_resolver.py   — URL resolution (Google News redirects)
  - src/news/article_fetcher.py — article fetching with DNS/IP security
  - src/news/rss_fetcher.py     — RSS multi-source fetching and deduplication
  - src/news/digest.py          — news digest generation and source blocks

Re-exports are kept here for backward compatibility.
"""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

from src.llm_client import ModelProfile, chat, stream_chat
from src.mode_manager import load_runtime_modes, update_wechat_join_state
from src.news.article_extractor import (
    article_method_label as _article_method_label,
    clean_article_text as _clean_article_text,  # noqa: F401
    decode_html_payload as _decode_html_payload,  # noqa: F401
    extract_article_text as _extract_article_text,  # noqa: F401
    extract_article_text_with_fallback_parser as _extract_article_text_with_fallback_parser,  # noqa: F401
)
from src.role_manager import load_role
from src.safe_writer import append_text_safely, safe_write_text
from src.text_utils import file_signature

# ── Re-exports from split modules ─────────────────────────────────────

from src.wechat_format import (  # noqa: F401
    LEGACY_OPENING_MARKERS,
    PERFORMANCE_STYLE_HINTS,
    ROLE_ID_TO_NAME,
    STYLE_PROMPTS,
    WECHAT_BLOCK_PATTERN,
    WECHAT_MISSING_ROLE_FALLBACKS,
    WECHAT_ROLE_ORDER,
    _ensure_all_roles_reply,
    _format_role_blocks,
    _is_legacy_opening,
    _message_blocks,
)
from src.news.link_resolver import (  # noqa: F401
    _display_link_host,
    _extract_resolved_url_from_google_news_html,
    _has_direct_article_link,
    _is_google_news_url,
    _news_item_url,
    resolve_news_link,
)
from src.news.article_fetcher import (  # noqa: F401
    _ARTICLE_CACHE,
    _article_fetch_priority,
    _check_dns_target_safe,
    _is_fetchable_article_url,
    enrich_news_items_with_article_text,
    fetch_article_text,
    fetch_article_text_with_method,
)
from src.news.rss_fetcher import (  # noqa: F401
    DEFAULT_NEWS_QUERY,
    NEWS_FEED_URL,
    BING_NEWS_FEED_URL,
    DOMESTIC_NEWS_FEEDS,
    _NEWS_CACHE,
    _NEWS_CACHE_TTL,
    _NEWS_CACHE_MAX_SIZE,
    _RECENT_NEWS_WINDOW_DAYS,
    _clean_news_title,
    _count_query_term_matches,
    _dedupe_and_trim_news_items,
    _fetch_query_news_items,
    _fetch_rss_items_from_url,
    _is_default_news_query,
    _is_recent_news_item,
    _news_item_sort_key,
    _parse_news_pub_date,
    _preferred_source_domains,
    _prune_cache,
    _prune_news_cache,
    _query_terms,
    _title_matches_query,
    fetch_latest_news_items,
    fetch_news_items,
    normalize_news_query,
)
from src.news.digest import (  # noqa: F401
    _display_news_title,
    _format_news_items_for_digest,
    _news_article_coverage_summary,
    format_news_source_block,
    generate_news_digest,
)

# ── File paths ────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent
GROUP_FILE = ROOT / "chat" / "wechat_group.md"
UNREAD_FILE = ROOT / "chat" / "wechat_unread.md"
STATE_FILE = ROOT / "chat" / "wechat_state.md"
ARCHIVE_DIR = ROOT / "chat" / "archive"
TEMPLATE_FILE = ROOT / "templates" / "wechat_update.md"
INTERACTIVE_TEMPLATE = ROOT / "templates" / "wechat_interactive_reply.md"


# ── File I/O helpers ──────────────────────────────────────────────────


@lru_cache(maxsize=32)
def _load_wechat_text_cached(path_str: str, signature: str) -> str:
    path = Path(path_str)
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8").strip()


def _load_text(path: Path, default: str = "") -> str:
    if not path.is_file():
        return default
    return _load_wechat_text_cached(str(path), file_signature(path))


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
    raw = chat(messages, temperature=0.7, model_profile=model_profile).strip()
    return _ensure_all_roles_reply(raw)


# ── System prompt helpers ─────────────────────────────────────────────


def _load_system_prompt() -> str:
    return _load_text(
        TEMPLATE_FILE,
        "你是微信群聊生成器。根据本轮课后更新摘要，生成四位伙伴的群聊消息。输出格式：【角色名】\\n内容",
    )


def _load_interactive_prompt() -> str:
    return _load_text(
        INTERACTIVE_TEMPLATE,
        "你是微信群聊互动生成器。根据用户消息和群聊历史生成回复。输出格式：【角色名】\\n内容",
    )


# ── Interactive message builder ───────────────────────────────────────


def _build_interactive_messages(
    user_text: str,
    relationship_mode: str | None = None,
) -> tuple[list[dict], bool]:
    modes = load_runtime_modes()
    if relationship_mode is None:
        relationship_mode = modes.relationship_mode

    is_first = not modes.first_reaction_done
    prompt = _load_interactive_prompt()
    history = read_wechat_group()
    history_lines = history.splitlines()[-40:] if history else []

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
        _load_system_prompt() + STYLE_PROMPTS.get(style, STYLE_PROMPTS["标准"])
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
    raw = chat(messages, temperature=0.6, model_profile=model_profile).strip()
    return _ensure_all_roles_reply(raw)


# ── Group / unread read helpers ───────────────────────────────────────


def read_wechat_unread() -> str:
    return _load_text(UNREAD_FILE)


def read_wechat_group() -> str:
    return _load_text(GROUP_FILE)


def has_wechat_unread() -> bool:
    unread = read_wechat_unread()
    return bool(unread and "暂无未读消息" not in unread and "暂无未读" not in unread)


def has_wechat_group_started() -> bool:
    content = read_wechat_group()
    if not _message_blocks(content):
        return False
    if _is_legacy_opening(content):
        return False
    return True


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
        "禁止出现类似“如果你看到”“你要是来了”“你应该能看到”“把这里当成给你准备的地方”这类句子。"
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
    ).strip()
    return _ensure_all_roles_reply(opening)


# ── Group lifecycle ───────────────────────────────────────────────────


def start_wechat_group_with_opening(content: str) -> str:
    normalized = _ensure_all_roles_reply(content)
    safe_write_text(GROUP_FILE, normalized + "\n")
    safe_write_text(UNREAD_FILE, "# 未读消息\n\n> 暂无未读消息。\n")
    update_wechat_join_state(
        user_has_joined=False,
        first_reaction_done=False,
        mode="interactive_group",
    )
    return normalized


def append_new_wechat_feedback(content: str) -> None:
    if not content.strip():
        return
    normalized = _ensure_all_roles_reply(content)

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    version = load_runtime_modes().current_version
    thread_id = uuid4().hex[:8]
    header = (
        "# 微信群未读消息\n\n"
        f"- 生成时间: {now}\n"
        "- 状态: unread\n"
        f"- 阶段: {version}\n"
        f"- thread_id: {thread_id}\n\n---\n\n"
    )
    safe_write_text(UNREAD_FILE, header + normalized + "\n")
    append_text_safely(GROUP_FILE, normalized + "\n")
    update_wechat_join_state(
        user_has_joined=False,
        first_reaction_done=False,
        mode="unread_feedback",
    )


def append_system_group_note(content: str) -> None:
    if not content.strip():
        return
    current = read_wechat_group()
    prefix = "" if not current.strip() else "\n\n"
    append_text_safely(GROUP_FILE, prefix + content.strip() + "\n")


def append_interactive_group_reply(content: str) -> None:
    if not content.strip():
        return
    normalized = _ensure_all_roles_reply(content)
    append_text_safely(GROUP_FILE, normalized + "\n")
    unread = read_wechat_unread()
    if has_wechat_unread():
        safe_write_text(UNREAD_FILE, unread + "\n\n" + normalized + "\n")
    else:
        safe_write_text(UNREAD_FILE, normalized + "\n")


def append_wechat_messages(content: str) -> None:
    append_new_wechat_feedback(content)


def clear_wechat_unread() -> None:
    safe_write_text(UNREAD_FILE, "# 未读消息\n\n> 暂无未读消息。\n")


def reset_wechat_group() -> None:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    if GROUP_FILE.is_file():
        old_content = GROUP_FILE.read_text(encoding="utf-8")
        archive_path = ARCHIVE_DIR / f"wechat_group_{ts}.md"
        safe_write_text(archive_path, old_content)
        safe_write_text(GROUP_FILE, "")

    if UNREAD_FILE.is_file():
        safe_write_text(UNREAD_FILE, "# 未读消息\n\n> 暂无未读消息。\n")

    update_wechat_join_state(False, False, "interactive_group")


def mark_wechat_read() -> None:
    clear_wechat_unread()


# ── State management ──────────────────────────────────────────────────


def read_wechat_state() -> dict:
    modes = load_runtime_modes()
    return {
        "user_has_joined": modes.user_has_joined,
        "first_join_done": modes.first_reaction_done,
        "mode": modes.wechat_mode,
    }


def write_wechat_state(user_has_joined: bool, first_join_done: bool, mode: str):
    update_wechat_join_state(user_has_joined, first_join_done, mode)


def append_user_group_message(user_text: str):
    ts = datetime.now().strftime("%m-%d %H:%M")
    message = f"\n\n【用户】 {ts}\n{user_text}"
    if GROUP_FILE.is_file():
        current = GROUP_FILE.read_text(encoding="utf-8")
        safe_write_text(GROUP_FILE, current + message)
    else:
        safe_write_text(GROUP_FILE, f"# 学习伙伴群\n{message}")


# ── Interactive reply generation ──────────────────────────────────────


def generate_interactive_wechat_reply(
    user_text: str,
    model_profile: ModelProfile = "flash",
    relationship_mode: str | None = None,
) -> str:
    messages, _is_first = _build_interactive_messages(user_text, relationship_mode)
    raw = chat(messages, temperature=0.7, model_profile=model_profile)
    return _ensure_all_roles_reply(raw.strip())


def generate_interactive_wechat_reply_stream(
    user_text: str,
    model_profile: ModelProfile = "flash",
    relationship_mode: str | None = None,
):
    messages, is_first = _build_interactive_messages(user_text, relationship_mode)
    return stream_chat(messages, temperature=0.7, model_profile=model_profile), is_first


def normalize_interactive_wechat_reply(content: str) -> str:
    return _ensure_all_roles_reply(content)


# ── Search / summarize ────────────────────────────────────────────────


def search_wechat(keyword: str, max_results: int = 10) -> list[dict]:
    content = read_wechat_group()
    if not content:
        return []
    results = []
    for speaker, text in _message_blocks(content):
        if keyword.lower() in text.lower():
            results.append({"speaker": speaker, "text": text.strip()[:150]})
            if len(results) >= max_results:
                break
    return results


def summarize_wechat(max_chars: int = 500) -> str:
    content = read_wechat_group()
    if not content:
        return "暂无群聊记录"
    lines = content.splitlines()
    dividers = [
        i for i, line in enumerate(lines) if "---" in line or "课后反馈" in line
    ]
    start = dividers[-1] if dividers else max(0, len(lines) - 60)
    recent = "\n".join(lines[start:])
    return recent[:max_chars] + ("..." if len(recent) > max_chars else "")


def count_wechat_messages(content: str) -> int:
    if not content.strip():
        return 0
    return len(_message_blocks(content))
