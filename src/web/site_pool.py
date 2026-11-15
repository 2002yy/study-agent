"""Site pool: which sources to try for a given question.

The pool is deliberately data, not code. Each entry knows its own search URL,
its result container or URL shape, whether it normally needs a login, and which
question shapes it serves. Selection returns a small ordered set - searching
every site for every question would be slow and would drown official
documentation in forum chatter.

Two rules keep the routing honest:

* a domain keyword (a game, a job board, a paper index) outranks a generic
  intent word, so "star rail team recommendation" does not go to Reddit first;
* only a site whose results can actually be recognised is routable. A site that
  merely opens is a candidate, not a source.

Safety rules live in :mod:`src.web.browse_search`; a challenge on one site stops
that site only and never tries to get around it.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
import os
import re
from typing import Any, Iterable
from urllib.parse import quote_plus, urlsplit


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
    #: CSS selector for the result containers, when the site's own markup is
    #: known to be stable enough to rely on.
    result_selector: str = ""
    #: URL shape of a real result on this site. Everything else the page links
    #: to (navigation, footer, login, promoted cards) is dropped.
    result_pattern: str = ""
    #: Hosts that belong to the search site itself. Results there are its own
    #: navigation unless a ``result_pattern`` says otherwise.
    own_hosts: tuple[str, ...] = ()
    #: True only for a site whose browser search was observed to return valid
    #: results in a real probe. An unproven site stays in the catalogue and can
    #: be opted in with ``WEB_SITE_POOL_EXTRA_SITES``, but never enters the
    #: default route on the strength of "the page opened".
    default_enabled: bool = False

    def search_url(self, query: str) -> str:
        return self.search.replace("{q}", quote_plus(query))

    @property
    def verified(self) -> bool:
        """True when a result can be told apart from the page's own chrome."""

        return bool(
            self.result_selector
            or self.result_pattern
            or self.own_hosts
            or self.adapter != "generic"
        )


#: First batch from the accepted site-pool proposal. Domain sources are listed
#: here too, but the router only picks them for a matching question.
#:
#: ``default_enabled`` records real-browser evidence from 2026-11-15. Stack
#: Overflow answered with a ``/nocaptcha`` wall, Reddit/Hacker News/Steam/
#: Miyoushe returned no results at all, and Zhihu/Nowcoder/NGA/Chiphell/
#: LINUX DO returned only page chrome. They stay opt-in until their adapters are
#: fixed; enabling them now would spend the pool budget on walls.
SITES: tuple[SiteProfile, ...] = (
    SiteProfile("google", "Google", "search", "https://www.google.com/",
                "https://www.google.com/search?q={q}", adapter="google",
                result_selector="a:has(h3)", default_enabled=True,
                note="2026-11-15: 5/5 valid results",
                own_hosts=("google.com", "www.google.com")),
    SiteProfile("duckduckgo", "DuckDuckGo", "search", "https://duckduckgo.com/",
                "https://duckduckgo.com/?q={q}", adapter="duckduckgo",
                note="2026-11-15: search page returned its own funnel links only",
                own_hosts=("duckduckgo.com", "www.duckduckgo.com")),
    SiteProfile("bing", "Bing", "search", "https://www.bing.com/",
                "https://www.bing.com/search?q={q}", adapter="bing",
                result_selector="li.b_algo h2 a", default_enabled=True,
                note="2026-11-15: 5/5 valid results",
                own_hosts=("bing.com", "www.bing.com", "cn.bing.com")),
    SiteProfile("brave", "Brave Search", "search", "https://search.brave.com/",
                "https://search.brave.com/search?q={q}", adapter="brave",
                result_selector=".result-content > a", default_enabled=True,
                note="2026-11-15: 5/5 valid results",
                own_hosts=("search.brave.com",)),
    SiteProfile("github", "GitHub", "en_community", "https://github.com/",
                "https://github.com/search?q={q}&type=issues", default_enabled=True,
                note="2026-11-15: 5/5 valid results",
                result_pattern=r"^https://github\.com/[^/?#]+/[^/?#]+/(?:issues|pull|discussions)/\d+"),
    SiteProfile("reddit", "Reddit", "en_community", "https://www.reddit.com/",
                "https://www.reddit.com/search/?q={q}",
                note="2026-11-15: no results (client-rendered search)",
                result_pattern=r"^https://(?:www\.|old\.)?reddit\.com/r/[^/?#]+/comments/"),
    SiteProfile("stackoverflow", "Stack Overflow", "en_community",
                "https://stackoverflow.com/", "https://stackoverflow.com/search?q={q}",
                note="2026-11-15: redirected to /nocaptcha",
                result_pattern=r"^https://stackoverflow\.com/questions/\d+"),
    SiteProfile("hn", "Hacker News Search", "en_community", "https://hn.algolia.com/",
                "https://hn.algolia.com/?q={q}",
                note="2026-11-15: results are client-rendered, none extracted",
                result_pattern=r"^https://news\.ycombinator\.com/item\?id=\d+"),
    SiteProfile("v2ex", "V2EX", "zh_community", "https://www.v2ex.com/",
                "https://www.v2ex.com/search?q={q}", needs_login=True,
                default_enabled=True, note="2026-11-15: 5/5 valid results",
                result_pattern=r"^https://(?:www\.)?v2ex\.com/t/\d+"),
    SiteProfile("linuxdo", "LINUX DO", "zh_community", "https://linux.do/",
                "https://linux.do/search?q={q}", needs_login=True,
                note="2026-11-15: flaky (login wall or no results)",
                result_pattern=r"^https://linux\.do/t/[^/?#]+/\d+"),
    SiteProfile("zhihu", "知乎", "zh_community", "https://www.zhihu.com/",
                "https://www.zhihu.com/search?type=content&q={q}", needs_login=True,
                note="2026-11-15: only footer links extracted",
                result_pattern=r"^https://(?:www\.)?zhihu\.com/question/\d+|^https://zhuanlan\.zhihu\.com/p/\d+"),
    SiteProfile("juejin", "稀土掘金", "zh_community", "https://juejin.cn/",
                "https://juejin.cn/search?query={q}", default_enabled=True,
                note="2026-11-15: 5/5 valid results",
                result_pattern=r"^https://juejin\.cn/post/\d+"),
    SiteProfile("huggingface", "Hugging Face", "domain", "https://huggingface.co/",
                "https://huggingface.co/search/full-text?q={q}", default_enabled=True,
                note="2026-11-15: 5/5 valid results",
                result_pattern=r"^https://huggingface\.co/(?!organizations|papers|datasets|spaces|models|login|join|pricing|courses|blog|docs|tasks|search)[^/?#]+/[^/?#]+"),
    SiteProfile("arxiv", "arXiv", "domain", "https://arxiv.org/",
                "https://arxiv.org/search/?query={q}&searchtype=all", default_enabled=True,
                note="2026-11-15: valid results for a query with hits; 0 results for an off-topic query",
                result_pattern=r"^https?://arxiv\.org/(?:abs|pdf)/"),
    SiteProfile("steam", "Steam", "domain", "https://store.steampowered.com/",
                "https://store.steampowered.com/search/?term={q}",
                note="2026-11-15: no results extracted",
                result_pattern=r"^https://store\.steampowered\.com/app/\d+"),
    SiteProfile("miyoushe", "米游社", "domain", "https://www.miyoushe.com/",
                "https://www.miyoushe.com/search?keyword={q}",
                note="2026-11-15: no results extracted",
                result_pattern=r"^https://(?:www\.)?miyoushe\.com/[^/?#]+/article/\d+"),
    SiteProfile("nga", "NGA", "domain", "https://bbs.nga.cn/",
                "https://bbs.nga.cn/search.php?key={q}",
                note="2026-11-15: only registration/footer links extracted",
                result_pattern=r"^https?://(?:bbs\.nga\.cn|ngabbs\.com|nga\.178\.com)/read\.php\?.*tid=\d+"),
    SiteProfile("chiphell", "Chiphell", "domain", "https://www.chiphell.com/",
                "https://www.chiphell.com/search.php?mod=forum&srchtxt={q}",
                note="2026-11-15: only footer links extracted",
                result_pattern=r"^https://www\.chiphell\.com/(?:thread-\d+|forum\.php\?mod=viewthread)"),
    SiteProfile("nowcoder", "牛客", "domain", "https://www.nowcoder.com/",
                "https://www.nowcoder.com/search?query={q}",
                note="2026-11-15: results load after the page settles",
                result_pattern=r"^https://www\.nowcoder\.com/(?:discuss|question|feed|jobs)/\d+"),
)

_BY_KEY = {site.key: site for site in SITES}

#: Domain question shapes. Checked before the generic intent routes so that a
#: specific community is not outranked by a generic word such as "recommended".
_DOMAIN_ROUTES: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("原神", "星铁", "崩坏", "米游社", "miyoushe", "配队", "抽卡"),
     ("miyoushe", "nga", "reddit")),
    (("游戏", "steam", "单机", "开黑"),
     ("steam", "reddit", "chiphell")),
    (("显卡", "cpu", "内存", "装机", "硬件", "rtx", "笔记本", "chiphell"),
     ("chiphell", "reddit", "v2ex")),
    (("校招", "面试", "找工作", "招聘", "简历", "就业", "牛客"),
     ("nowcoder", "v2ex", "zhihu")),
    (("论文", "arxiv", "paper", "引用", "文献"),
     ("arxiv", "google")),
    (("模型", "微调", "数据集", "权重", "huggingface"),
     ("huggingface", "github", "reddit")),
    (("报错", "异常", "traceback", "exception", "崩溃", "不工作", "error", "failed"),
     ("stackoverflow", "github", "google")),
    (("开源", "源码", "issue", "pull request", "部署", "自建", "release", "github"),
     ("github", "google", "reddit", "hn")),
)

#: Generic intent shapes, checked only when no domain route matched.
_INTENT_ROUTES: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("api", "agent", "llm", "中转"),
     ("huggingface", "github", "linuxdo", "reddit")),
    (("哪个好", "哪个更适合", "哪个", "推荐", "体验", "口碑", "值得", "争议",
      "vs", "对比", "选型", "怎么选", "选择"),
     ("google", "reddit", "hn", "v2ex", "linuxdo", "juejin")),
)

_DEFAULT_ORDER = ("google", "duckduckgo", "bing", "brave")

#: ASCII keywords must match as words: "api" inside "FastAPI" is not a request
#: for a model hub, and "vs" inside a word is not a comparison.
_ASCII_WORD = re.compile(r"[a-z0-9_+#.-]")


def _matches(text: str, keyword: str) -> bool:
    needle = keyword.casefold()
    if not needle:
        return False
    if not needle.isascii():
        return needle in text
    start = 0
    while True:
        index = text.find(needle, start)
        if index < 0:
            return False
        before = text[index - 1] if index else " "
        end = index + len(needle)
        after = text[end] if end < len(text) else " "
        if not _ASCII_WORD.match(before) and not _ASCII_WORD.match(after):
            return True
        start = index + 1


def site_limit() -> int:
    raw = os.getenv("WEB_SITE_POOL_LIMIT", "3").strip()
    try:
        value = int(raw)
    except ValueError:
        return 3
    return max(1, min(value, 6))


def extra_sites() -> set[str]:
    """Sites a deployment opts into beyond the evidence-backed default set."""

    raw = os.getenv("WEB_SITE_POOL_EXTRA_SITES", "")
    return {part.strip().casefold() for part in raw.split(",") if part.strip()}


def select_sites(
    question: str, *, limit: int | None = None, include_unverified: bool = False
) -> list[SiteProfile]:
    """Ordered sites worth trying for this question (bounded and deduped)."""

    text = f" {str(question or '').casefold()} "
    order: list[str] = []
    for routes in (_DOMAIN_ROUTES, _INTENT_ROUTES):
        for keywords, keys in routes:
            if any(_matches(text, keyword) for keyword in keywords):
                order.extend(keys)
                break
    order.extend(_DEFAULT_ORDER)
    extra = extra_sites()
    seen: set[str] = set()
    selected: list[SiteProfile] = []
    for key in order:
        profile = _BY_KEY.get(key)
        if profile is None or profile.key in seen:
            continue
        if not include_unverified and not (
            profile.default_enabled or profile.key in extra
        ):
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


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").casefold()


__all__ = [
    "SITES",
    "SiteProfile",
    "describe",
    "extra_sites",
    "host_of",
    "select_sites",
    "site_limit",
    "start_outcomes",
    "take_outcomes",
]
