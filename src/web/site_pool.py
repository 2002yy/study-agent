"""Site pool: which sources to try for a given question.

The pool is deliberately data, not code. Each entry knows its own search URL,
whether it normally needs a login, and which question shapes it serves. Selection
returns a small ordered set — searching every site for every question would be
slow and would drown official documentation in forum chatter.

Safety rules live in :mod:`src.web.browse_search`; a challenge on one site stops
that site only and never tries to get around it.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from contextvars import ContextVar
from typing import Any, Iterable
from urllib.parse import quote_plus


@dataclass(frozen=True)
class SiteProfile:
    key: str
    label: str
    category: str
    home: str
    search: str
    needs_login: bool = False
    note: str = ""
    adapter: str = "generic"

    def search_url(self, query: str) -> str:
        return self.search.replace("{q}", quote_plus(query))


#: First batch from the accepted site-pool proposal. Domain sources are listed
#: here too, but the router only picks them for a matching question.
SITES: tuple[SiteProfile, ...] = (
    SiteProfile("google", "Google", "search", "https://www.google.com/",
                "https://www.google.com/search?q={q}", adapter="google"),
    SiteProfile("duckduckgo", "DuckDuckGo", "search", "https://duckduckgo.com/",
                "https://duckduckgo.com/?q={q}"),
    SiteProfile("bing", "Bing", "search", "https://www.bing.com/",
                "https://www.bing.com/search?q={q}"),
    SiteProfile("brave", "Brave Search", "search", "https://search.brave.com/",
                "https://search.brave.com/search?q={q}"),
    SiteProfile("github", "GitHub", "en_community", "https://github.com/",
                "https://github.com/search?q={q}&type=issues"),
    SiteProfile("reddit", "Reddit", "en_community", "https://www.reddit.com/",
                "https://www.reddit.com/search/?q={q}"),
    SiteProfile("stackoverflow", "Stack Overflow", "en_community",
                "https://stackoverflow.com/", "https://stackoverflow.com/search?q={q}"),
    SiteProfile("hn", "Hacker News Search", "en_community", "https://hn.algolia.com/",
                "https://hn.algolia.com/?q={q}"),
    SiteProfile("v2ex", "V2EX", "zh_community", "https://www.v2ex.com/",
                "https://www.v2ex.com/search?q={q}", needs_login=True),
    SiteProfile("linuxdo", "LINUX DO", "zh_community", "https://linux.do/",
                "https://linux.do/search?q={q}", needs_login=True),
    SiteProfile("zhihu", "知乎", "zh_community", "https://www.zhihu.com/",
                "https://www.zhihu.com/search?type=content&q={q}", needs_login=True),
    SiteProfile("juejin", "稀土掘金", "zh_community", "https://juejin.cn/",
                "https://juejin.cn/search?query={q}"),
    SiteProfile("huggingface", "Hugging Face", "domain", "https://huggingface.co/",
                "https://huggingface.co/search/full-text?q={q}"),
    SiteProfile("arxiv", "arXiv", "domain", "https://arxiv.org/",
                "https://arxiv.org/search/?query={q}&searchtype=all"),
    SiteProfile("steam", "Steam", "domain", "https://store.steampowered.com/",
                "https://store.steampowered.com/search/?term={q}"),
    SiteProfile("miyoushe", "米游社", "domain", "https://www.miyoushe.com/",
                "https://www.miyoushe.com/search?keyword={q}"),
    SiteProfile("nga", "NGA", "domain", "https://bbs.nga.cn/",
                "https://bbs.nga.cn/search.php?key={q}"),
    SiteProfile("chiphell", "Chiphell", "domain", "https://www.chiphell.com/",
                "https://www.chiphell.com/search.php?mod=forum&srchtxt={q}"),
    SiteProfile("nowcoder", "牛客", "domain", "https://www.nowcoder.com/",
                "https://www.nowcoder.com/search?query={q}"),
)

_BY_KEY = {site.key: site for site in SITES}

#: Question shapes from the accepted routing table. First match wins; the
#: ordered tuple is the order in which the sites are tried.
_ROUTES: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("报错", "异常", "traceback", "exception", "崩溃", "不工作", "error", "failed"),
     ("stackoverflow", "github", "google")),
    (("哪个好", "哪个更适合", "推荐", "体验", "值得", "争议", "vs", "对比", "选择"),
     ("reddit", "hn", "v2ex", "linuxdo", "google")),
    (("开源", "源码", "issue", "pull request", "部署", "自建", "release", "版本"),
     ("github", "google", "reddit", "hn")),
    (("论文", "arxiv", "paper", "引用", "研究"),
     ("arxiv", "google")),
    (("模型", "api", "agent", "llm", "微调", "数据集"),
     ("huggingface", "github", "linuxdo", "reddit")),
    (("显卡", "cpu", "内存", "装机", "硬件", "rtx", "笔记本"),
     ("chiphell", "reddit", "v2ex", "zhihu")),
    (("游戏", "原神", "星铁", "配队", "steam", "版本体验"),
     ("miyoushe", "nga", "steam", "reddit")),
    (("校招", "面试", "找工作", "招聘", "简历", "就业"),
     ("nowcoder", "v2ex", "zhihu")),
)

_DEFAULT_ORDER = ("google", "duckduckgo", "bing", "brave")


def site_limit() -> int:
    raw = os.getenv("WEB_SITE_POOL_LIMIT", "3").strip()
    try:
        value = int(raw)
    except ValueError:
        return 3
    return max(1, min(value, 6))


def select_sites(
    question: str, *, limit: int | None = None
) -> list[SiteProfile]:
    """Ordered sites worth trying for this question (bounded and deduped)."""

    text = f" {str(question or '').casefold()} "
    order: list[str] = []
    for keywords, keys in _ROUTES:
        if any(keyword.casefold() in text for keyword in keywords):
            order.extend(keys)
            break
    order.extend(_DEFAULT_ORDER)
    seen: set[str] = set()
    selected: list[SiteProfile] = []
    for key in order:
        profile = _BY_KEY.get(key)
        if profile is None or profile.key in seen:
            continue
        seen.add(profile.key)
        selected.append(profile)
        if len(selected) >= (limit if limit is not None else site_limit()):
            break
    return selected


def describe(sites: Iterable[SiteProfile]) -> str:
    return ", ".join(site.key for site in sites)


_outcomes: ContextVar[list[dict[str, Any]] | None] = ContextVar(
    "site_pool_outcomes", default=None
)


def start_outcomes() -> list[dict[str, Any]]:
    """Begin a per-request outcome log for one site-pool search."""

    outcomes: list[dict[str, Any]] = []
    _outcomes.set(outcomes)
    return outcomes


def take_outcomes() -> list[dict[str, Any]]:
    outcomes = list(_outcomes.get() or [])
    _outcomes.set(None)
    return outcomes


__all__ = [
    "SITES",
    "SiteProfile",
    "describe",
    "select_sites",
    "site_limit",
    "start_outcomes",
    "take_outcomes",
]
