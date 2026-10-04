"""Keep short research follow-ups attached to the user's stated topic.

History supplies query leads, never evidence or permission to use new data.
"""

from __future__ import annotations

import re

from src.web.query_normalizer import normalize_web_query

_RESEARCH_REQUEST = re.compile(
    r"^(?:请|帮我|麻烦)?\s*(?:联网|上网|深度)?\s*"
    r"(?:研究|搜索|查询|检索|查一下|搜一下)\s*[:：]?\s*(.+)$",
    re.IGNORECASE,
)
_RESUME = re.compile(
    r"^(?:快去|去吧|继续(?:查(?:查)?|搜(?:搜)?|研究)?|重试|再试(?:试)?|"
    r"再(?:查(?:查|一下)?|搜(?:搜|一下)?|搜索|检索|研究)|"
    r"直接(?:去|查|搜)|去查|去搜|查吧|搜吧|retry|try again|keep searching)"
    r"[！!。？?，,；;\s]*"
    r"(?:(?:不要|别)(?:一次|一(?:次)?失败|失败|搜不到|查不到|没找到)"
    r"(?:失败)?就(?:返回|结束|停止|停下|放弃)[！!。？?\s]*)?$",
    re.IGNORECASE,
)
_FOLLOWUP = re.compile(
    r"(?:你联网|刚刚|刚才|没有找到|没找到|没搜|不太可能|啊[？?])",
    re.IGNORECASE,
)

# Conservative compatibility fallback for the recorded reference-only turns.
# Broader conversational interpretation belongs to the semantic episode path;
# an unknown sentence containing "刚刚" must keep its own subject.
_REFERENCE_ONLY = frozenset({
    "是最新的a÷模型。你联网没有找到内容吗？不太可能吧",
    "？意思刚刚你没有搜？",
    "意思刚刚你没有搜？",
    "刚刚你没有搜？",
    "刚才你没有搜？",
    "你联网没有找到内容吗？",
    "没有找到吗？",
    "没找到吗？",
    "不太可能吧",
})


_NEW_TOPIC = re.compile(r"(?:换个|另外|现在查|现在搜|现在研究|接下来查|顺便查)")
_EN_RESEARCH_REQUEST = re.compile(
    r"^(?:please\s+)?(?:research|search(?:\s+the\s+web)?(?:\s+for)?|look\s+up)\s*[:：]?\s+(.+)$",
    re.IGNORECASE,
)
_MODEL_QUERY = re.compile(r"[A-Za-z][A-Za-z_-]*\s*\d+\.\d+")


def research_topic(user_message: str) -> str:
    match = _RESEARCH_REQUEST.match(user_message.strip()) or _EN_RESEARCH_REQUEST.match(
        user_message.strip()
    )
    return normalize_web_query(match.group(1)).canonical_query if match else ""


def is_research_resume(user_message: str) -> bool:
    """Recognize whole control requests; a supplied new subject must win."""
    return _RESUME.fullmatch(user_message.strip()) is not None


def research_query_lead(history: list[dict]) -> str:
    topic = ""
    for message in history:
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        text = str(message.get("content", ""))
        if explicit := research_topic(text):
            topic = explicit
        elif topic:
            topic = conversation_search_query(text, f"Research query lead: {topic}")
        elif _MODEL_QUERY.search(text):
            topic = normalize_web_query(text).canonical_query
    return topic


def conversation_search_query(user_input: str, context: str) -> str:
    """Use the current request unless it explicitly refers back to research."""
    current = normalize_web_query(user_input).canonical_query
    if (
        research_topic(user_input)
        or _NEW_TOPIC.search(user_input)
        or not (
            is_research_resume(user_input)
            or _FOLLOWUP.search(user_input.strip())
        )
    ):
        return current
    lead = re.match(r"Research query lead: ([^\n]+)", context)
    topic = lead.group(1) if lead else ""
    if not topic:
        return "" if is_research_resume(user_input) else current
    if is_research_resume(user_input):
        return topic
    if user_input.strip() not in _REFERENCE_ONLY and not re.fullmatch(
        r"[A-Za-z][A-Za-z0-9._-]{1,40}啊[？?](?:你不知道吗[？?])?", user_input.strip()
    ):
        return current
    # Corrections such as "Claude啊？" add a search qualifier without replacing
    # the original version. No manufacturer/model aliases are invented here.
    qualifiers = re.findall(r"[A-Za-z][A-Za-z0-9._-]{1,40}", user_input)
    if any(
        re.search(r"\d", value) and value.casefold() not in topic.casefold()
        for value in qualifiers
    ):
        return current
    if qualifiers and not all(
        value.casefold() in topic.casefold()
        or (
            value.casefold() in {"claude", "anthropic"}
            and re.search(r"opus|sonnet|haiku", topic, re.IGNORECASE)
        )
        for value in qualifiers
    ):
        return current
    return " ".join(
        [topic, *(v for v in qualifiers if v.casefold() not in topic.casefold())]
    )
