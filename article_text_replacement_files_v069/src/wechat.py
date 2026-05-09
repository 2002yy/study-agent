from __future__ import annotations

import re
import time
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import quote_plus, urlparse
from urllib.request import Request, urlopen
from uuid import uuid4
import xml.etree.ElementTree as ET

from src.llm_client import ModelProfile, chat, stream_chat
from src.mode_manager import load_runtime_modes, update_wechat_join_state
from src.role_manager import load_role
from src.safe_writer import append_text_safely, safe_write_text

ROOT = Path(__file__).resolve().parent.parent
GROUP_FILE = ROOT / "chat" / "wechat_group.md"
UNREAD_FILE = ROOT / "chat" / "wechat_unread.md"
STATE_FILE = ROOT / "chat" / "wechat_state.md"
ARCHIVE_DIR = ROOT / "chat" / "archive"
TEMPLATE_FILE = ROOT / "templates" / "wechat_update.md"
INTERACTIVE_TEMPLATE = ROOT / "templates" / "wechat_interactive_reply.md"
NEWS_FEED_URL = "https://news.google.com/rss/search?q={query}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"

STYLE_PROMPTS = {
    "简短": "\n【风格要求】每条消息 1-2 句，每位不超过 60 字，总长度不超过 400 字。",
    "标准": "\n【风格要求】每条消息 2-3 句，每位不超过 100 字，总长度不超过 600 字。",
    "稍微有温度": "\n【风格要求】每条消息 2-4 句，每位不超过 120 字，总长度不超过 800 字。",
}

WECHAT_ROLE_ORDER = ["三月七", "刻晴", "纳西妲", "流萤"]
WECHAT_BLOCK_PATTERN = re.compile(r"【(.+?)】\s*(.+?)(?=\n【|\Z)", re.DOTALL)
WECHAT_MISSING_ROLE_FALLBACKS = {
    "三月七": "我这边也接住啦，这句我听到了。那我先把气氛接上，我们继续往下聊。",
    "刻晴": "我补一句重点：先把你刚刚提到的核心问题记住，接下来按最关键的一步继续推进就好。",
    "纳西妲": "从这个角度看，你刚刚那句话其实已经给了线索。顺着它往下想，通常就能把眼前这一步理清一些。",
    "流萤": "我也在。别急，我们就顺着你刚刚这句话慢慢接下去，一点点把现在的感觉和事情放稳。",
}
ROLE_ID_TO_NAME = {
    "auto": "自动",
    "march7": "三月七",
    "keqing": "刻晴",
    "nahida": "纳西妲",
    "firefly": "流萤",
}
PERFORMANCE_STYLE_HINTS = {
    "fast": "整体更轻、更快、更短，每位角色 1 到 2 句即可。",
    "standard": "整体自然平衡，每位角色 1 到 3 句。",
    "deep": "可以稍微多一点层次，但仍然保持轻盈，不要写成长文。",
}
LEGACY_OPENING_MARKERS = (
    "要是你正好看到",
    "就把这里当成轻松一点的学习搭子小群也行",
)


def _file_signature(path: Path) -> str:
    if not path.is_file():
        return "missing"
    stat = path.stat()
    return f"{stat.st_mtime_ns}:{stat.st_size}"


@lru_cache(maxsize=32)
def _load_wechat_text_cached(path_str: str, signature: str) -> str:
    path = Path(path_str)
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8").strip()


def _load_text(path: Path, default: str = "") -> str:
    if not path.is_file():
        return default
    return _load_wechat_text_cached(str(path), _file_signature(path))


def _message_blocks(content: str) -> list[tuple[str, str]]:
    return [(speaker.strip(), text.strip()) for speaker, text in WECHAT_BLOCK_PATTERN.findall(content)]


def _format_role_blocks(blocks: list[tuple[str, str]]) -> str:
    return "\n\n".join(f"【{speaker}】\n{text.strip()}" for speaker, text in blocks if text.strip()).strip()


def _ensure_all_roles_reply(content: str) -> str:
    blocks = _message_blocks(content)
    if not blocks:
        return _format_role_blocks(
            [(speaker, WECHAT_MISSING_ROLE_FALLBACKS[speaker]) for speaker in WECHAT_ROLE_ORDER]
        )

    by_speaker: dict[str, list[str]] = {}
    for speaker, text in blocks:
        if speaker not in WECHAT_ROLE_ORDER:
            continue
        by_speaker.setdefault(speaker, []).append(text.strip())

    normalized_blocks: list[tuple[str, str]] = []
    for speaker in WECHAT_ROLE_ORDER:
        parts = [part for part in by_speaker.get(speaker, []) if part]
        if parts:
            normalized_blocks.append((speaker, "\n".join(parts)))
        else:
            normalized_blocks.append((speaker, WECHAT_MISSING_ROLE_FALLBACKS[speaker]))
    return _format_role_blocks(normalized_blocks)


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


def _clean_news_title(title: str) -> str:
    return re.sub(r"\s*-\s*[^-]+$", "", title).strip()


_NEWS_CACHE: dict[str, tuple[float, list[dict]]] = {}
_NEWS_CACHE_TTL = 600
_NEWS_CACHE_MAX_SIZE = 32

_ARTICLE_CACHE: dict[str, tuple[float, str]] = {}
_ARTICLE_CACHE_TTL = 1800
_ARTICLE_CACHE_MAX_SIZE = 32


def normalize_news_query(query_text: str, max_chars: int = 120) -> str:
    query_text = re.sub(r"\s+", " ", (query_text or "").strip())
    if not query_text:
        return "最新新闻 when:1d"
    return query_text[:max_chars]


def _prune_news_cache(now: float) -> None:
    expired = [
        key for key, (created_at, _) in _NEWS_CACHE.items()
        if now - created_at >= _NEWS_CACHE_TTL
    ]
    for key in expired:
        _NEWS_CACHE.pop(key, None)

    while len(_NEWS_CACHE) >= _NEWS_CACHE_MAX_SIZE:
        oldest_key = min(_NEWS_CACHE, key=lambda key: _NEWS_CACHE[key][0])
        _NEWS_CACHE.pop(oldest_key, None)


def _prune_article_cache(now: float) -> None:
    expired = [
        key for key, (created_at, _) in _ARTICLE_CACHE.items()
        if now - created_at >= _ARTICLE_CACHE_TTL
    ]
    for key in expired:
        _ARTICLE_CACHE.pop(key, None)

    while len(_ARTICLE_CACHE) >= _ARTICLE_CACHE_MAX_SIZE:
        oldest_key = min(_ARTICLE_CACHE, key=lambda key: _ARTICLE_CACHE[key][0])
        _ARTICLE_CACHE.pop(oldest_key, None)


class ArticleTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._skip_stack: list[str] = []
        self._chunks: list[str] = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in {
            "script",
            "style",
            "noscript",
            "svg",
            "canvas",
            "form",
            "nav",
            "header",
            "footer",
            "aside",
        }:
            self._skip_stack.append(tag)

        if tag in {"p", "br", "div", "section", "article", "h1", "h2", "h3", "li"}:
            self._chunks.append("\n")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if self._skip_stack and self._skip_stack[-1] == tag:
            self._skip_stack.pop()

        if tag in {"p", "div", "section", "article", "li"}:
            self._chunks.append("\n")

    def handle_data(self, data):
        if self._skip_stack:
            return

        text = data.strip()
        if text:
            self._chunks.append(text)

    def get_text(self) -> str:
        raw = " ".join(self._chunks)
        raw = re.sub(r"[ \t]+", " ", raw)
        raw = re.sub(r"\n\s*\n\s*\n+", "\n\n", raw)
        raw = re.sub(r"\s*\n\s*", "\n", raw)
        return raw.strip()


def _is_fetchable_article_url(url: str) -> bool:
    try:
        parsed = urlparse((url or "").strip())
    except Exception:
        return False

    if parsed.scheme not in {"http", "https"}:
        return False
    if not parsed.netloc:
        return False

    host = parsed.hostname or ""
    if host in {"localhost", "127.0.0.1", "0.0.0.0"}:
        return False
    if host.startswith("192.168.") or host.startswith("10.") or host.startswith("172.16."):
        return False

    return True


def _clean_article_text(text: str, max_chars: int = 3000) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    if len(text) < 180:
        return ""

    noise_keywords = [
        "cookie",
        "cookies",
        "subscribe",
        "sign in",
        "log in",
        "广告",
        "订阅",
        "登录",
        "注册",
        "隐私政策",
        "版权所有",
    ]

    parts = re.split(r"(?<=[。！？.!?])\s+", text)
    useful_parts = []
    for part in parts:
        lower = part.lower()
        if any(keyword in lower for keyword in noise_keywords) and len(part) < 120:
            continue
        useful_parts.append(part)

    cleaned = " ".join(useful_parts).strip()
    return cleaned[:max_chars]


def fetch_article_text(
    url: str,
    timeout: int = 8,
    max_bytes: int = 350_000,
    max_chars: int = 3000,
) -> str:
    url = (url or "").strip()
    if not url or not _is_fetchable_article_url(url):
        return ""

    now = time.time()
    _prune_article_cache(now)

    cached = _ARTICLE_CACHE.get(url)
    if cached and now - cached[0] < _ARTICLE_CACHE_TTL:
        return cached[1]

    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )

    try:
        with urlopen(req, timeout=timeout) as response:
            content_type = response.headers.get("Content-Type", "")
            if "html" not in content_type.lower() and "text" not in content_type.lower():
                return ""

            payload = response.read(max_bytes + 1)
            if len(payload) > max_bytes:
                payload = payload[:max_bytes]

        html = payload.decode("utf-8", errors="ignore")
        extractor = ArticleTextExtractor()
        extractor.feed(html)
        text = _clean_article_text(extractor.get_text(), max_chars=max_chars)
        _ARTICLE_CACHE[url] = (now, text)
        return text
    except Exception:
        return ""


def enrich_news_items_with_article_text(
    news_items: list[dict],
    max_articles: int = 3,
    max_chars_per_article: int = 2500,
) -> list[dict]:
    enriched: list[dict] = []

    for idx, item in enumerate(news_items):
        new_item = dict(item)

        if idx < max_articles:
            article_text = fetch_article_text(
                item.get("link", ""),
                max_chars=max_chars_per_article,
            )
            if article_text:
                new_item["article_excerpt"] = article_text
                new_item["article_status"] = "正文已读取"
            else:
                new_item["article_excerpt"] = ""
                new_item["article_status"] = "正文不可用，使用标题与来源"
        else:
            new_item["article_excerpt"] = ""
            new_item["article_status"] = "未读取正文，仅使用标题与来源"

        enriched.append(new_item)

    return enriched


def _format_news_items_for_digest(news_items: list[dict]) -> str:
    lines: list[str] = []

    for idx, item in enumerate(news_items, start=1):
        title = item.get("title", "")
        source = item.get("source", "新闻源")
        published_at = item.get("published_at", "今天")
        link = item.get("link", "")
        article_status = item.get("article_status", "仅标题")
        article_excerpt = item.get("article_excerpt", "")

        lines.append(f"{idx}. {title}")
        lines.append(f"来源：{source}")
        lines.append(f"时间：{published_at}")
        lines.append(f"链接：{link}")
        lines.append(f"正文状态：{article_status}")

        if article_excerpt:
            lines.append("正文摘录：")
            lines.append(article_excerpt)

        lines.append("")

    return "\n".join(lines).strip()


def format_news_source_block(query_text: str, news_items: list[dict]) -> str:
    query_text = normalize_news_query(query_text)
    lines = [f"【联网检索】\n查询：{query_text}"]

    for idx, item in enumerate(news_items[:5], start=1):
        title = item.get("title", "")
        source = item.get("source", "新闻源")
        published_at = item.get("published_at", "今天")
        link = item.get("link", "")
        article_status = item.get("article_status", "仅标题")
        lines.append(f"{idx}. {title} | {source} | {published_at} | {article_status}")
        if link:
            lines.append(f"   {link}")

    return "\n".join(lines).strip()


def fetch_news_items(query_text: str = "最新新闻 when:1d", max_items: int = 5) -> list[dict]:
    query_text = normalize_news_query(query_text)
    cache_key = f"{query_text}|{max_items}"

    now = time.time()
    _prune_news_cache(now)

    cached = _NEWS_CACHE.get(cache_key)
    if cached and now - cached[0] < _NEWS_CACHE_TTL:
        return cached[1][:max_items]

    query = quote_plus(query_text)
    url = NEWS_FEED_URL.format(query=query)
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
        },
    )

    with urlopen(req, timeout=15) as response:
        payload = response.read()

    root = ET.fromstring(payload)
    items: list[dict] = []

    for node in root.findall("./channel/item"):
        title = (node.findtext("title") or "").strip()
        link = (node.findtext("link") or "").strip()
        pub_date = (node.findtext("pubDate") or "").strip()
        source = ""
        source_node = node.find("source")
        if source_node is not None and source_node.text:
            source = source_node.text.strip()

        published_local = ""
        if pub_date:
            try:
                published_local = parsedate_to_datetime(pub_date).astimezone().strftime(
                    "%m-%d %H:%M"
                )
            except Exception:
                published_local = pub_date

        clean_title = _clean_news_title(title)
        if not clean_title:
            continue

        items.append(
            {
                "title": clean_title,
                "source": source or "新闻源",
                "published_at": published_local or "今天",
                "link": link,
            }
        )

        if len(items) >= max_items:
            break

    _NEWS_CACHE[cache_key] = (now, items)
    return items

def fetch_latest_news_items(max_items: int = 5) -> list[dict]:
    return fetch_news_items("最新新闻 when:1d", max_items=max_items)


def generate_news_digest(
    news_items: list[dict],
    performance_mode: str = "standard",
    selected_model: str = "auto",
) -> str:
    if not news_items:
        return ""

    model_profile = _resolve_model_profile(selected_model, performance_mode)
    items_text = _format_news_items_for_digest(news_items)
    messages = [
        {
            "role": "system",
            "content": (
                "你要基于新闻搜索结果整理中文摘要。部分条目可能包含正文摘录，"
                "部分条目只有标题、来源和时间。"
                "优先依据正文摘录总结；没有正文摘录的条目，只能基于标题、来源和时间谨慎概括。"
                "不要假装读取了没有提供的正文，不要补充搜索结果中没有的信息。"
                "如果信息不足，要明确写出信息边界。"
                "输出格式固定为：\n"
                "【搜索结果摘要】\n"
                "1. 标题\n- 要点\n- 为什么值得关注\n- 信息边界：来自正文/仅标题线索\n"
                "2. 标题\n- 要点\n- 为什么值得关注\n- 信息边界：来自正文/仅标题线索\n"
            ),
        },
        {
            "role": "user",
            "content": "请整理以下 3 到 5 条搜索结果：\n\n" + items_text,
        },
    ]
    return chat(messages, temperature=0.3, model_profile=model_profile).strip()

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

    context: list[str] = [_load_system_prompt() + STYLE_PROMPTS.get(style, STYLE_PROMPTS["标准"])]
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
        if content and all(flag not in content for flag in ["失败", "无对话", "无需更新"]):
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


def _is_legacy_opening(content: str) -> bool:
    if "【用户】" in content:
        return False
    return all(marker in content for marker in LEGACY_OPENING_MARKERS)


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
        f"当前性能模式：{performance_mode}。{PERFORMANCE_STYLE_HINTS.get(performance_mode, PERFORMANCE_STYLE_HINTS['standard'])}\n"
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
    append_text_safely(GROUP_FILE, content.strip() + "\n")


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


def read_wechat_state() -> dict:
    raw = _load_text(STATE_FILE)
    if not raw:
        return {
            "user_has_joined": False,
            "first_join_done": False,
            "mode": "unread_feedback",
        }
    joined = "user_has_joined_group: true" in raw
    first_done = "first_join_reaction_done: true" in raw
    mode = "interactive_group"
    if "mode: unread_feedback" in raw:
        mode = "unread_feedback"
    elif "mode: first_user_join" in raw:
        mode = "first_user_join"
    return {
        "user_has_joined": joined,
        "first_join_done": first_done,
        "mode": mode,
    }


def write_wechat_state(user_has_joined: bool, first_join_done: bool, mode: str):
    content = f"""# 微信群状态
## 可见性状态
- user_has_joined_group: {"true" if user_has_joined else "false"}
- first_join_reaction_done: {"true" if first_join_done else "false"}

## 当前群聊模式
- mode: {mode}

## 群聊边界
- 群聊用于课后反馈、复盘、轻互动和学习动力。
- 不替代正式教学。
- 不进行无关剧情闲聊。
- 不编造用户没有表达过的感受。
- close 模式可以提供更贴近的陪伴氛围，但不生成成人内容，不模拟现实恋人身份。
"""
    safe_write_text(STATE_FILE, content)


def append_user_group_message(user_text: str):
    ts = datetime.now().strftime("%m-%d %H:%M")
    message = f"\n\n【用户】 {ts}\n{user_text}"
    if GROUP_FILE.is_file():
        current = GROUP_FILE.read_text(encoding="utf-8")
        safe_write_text(GROUP_FILE, current + message)
    else:
        safe_write_text(GROUP_FILE, f"# 学习伙伴群\n{message}")


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
    dividers = [i for i, line in enumerate(lines) if "---" in line or "课后反馈" in line]
    start = dividers[-1] if dividers else max(0, len(lines) - 60)
    recent = "\n".join(lines[start:])
    return recent[:max_chars] + ("..." if len(recent) > max_chars else "")


def count_wechat_messages(content: str) -> int:
    if not content.strip():
        return 0
    return len(_message_blocks(content))
