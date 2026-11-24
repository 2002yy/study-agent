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
  merely opens is a candidate, not a source, and one that failed a real probe
  stays out of the default route until it is fixed.

The default route is small on purpose: about a dozen sources that passed a real
browser check, with the rest opt-in through ``WEB_SITE_POOL_EXTRA_SITES``.

Safety rules live in :mod:`src.web.browse_search`; a challenge on one site stops
that site only and never tries to get around it.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
import os
import re
from typing import Any, Iterable, Mapping
from urllib.parse import quote_plus, urlsplit

from src.web.source_directions import SOURCE_DIRECTIONS


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
    #: Element that only exists once results rendered. Waited for (bounded)
    #: instead of sleeping a fixed time. Defaults to ``result_selector``.
    wait_for: str = ""
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
    #: Engine used for site-restricted discovery when the site's own search is
    #: blocked (login, captcha, client render). The query becomes
    #: ``<question> site:<host>`` and the results are still validated by
    #: ``result_pattern``, so only that site's real pages can pass.
    search_via: str = ""

    #: Alternative search templates chosen by a word in the question, e.g. a
    #: community that has one search page per game. (keywords, template) pairs,
    #: first match wins; ``search`` is the fallback.
    search_variants: tuple[tuple[tuple[str, ...], str], ...] = ()

    def search_url(self, query: str) -> str:
        text = str(query or "").casefold()
        for keywords, template in self.search_variants:
            if any(word.casefold() in text for word in keywords):
                return template.replace("{q}", quote_plus(query))
        return self.search.replace("{q}", quote_plus(query))

    @property
    def verified(self) -> bool:
        """True when a result can be told apart from the page's own chrome."""

        return bool(
            self.result_selector
            or self.result_pattern
            or self.own_hosts
            or self.adapter != "generic"
            or self.search_via
        )

    @property
    def wait_selector(self) -> str:
        """Element to wait for before reading the page."""

        return self.wait_for or self.result_selector


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
                default_enabled=True, note="2026-11-15: 5/5 valid results"),
    SiteProfile("duckduckgo", "DuckDuckGo", "search", "https://duckduckgo.com/",
                "https://duckduckgo.com/?q={q}", adapter="duckduckgo",
                note="2026-11-15: HTML endpoint asks for a human check; not enabled"),
    SiteProfile("bing", "Bing", "search", "https://www.bing.com/",
                "https://www.bing.com/search?q={q}", adapter="bing",
                default_enabled=True,
                note="2026-11-15: 5/5 valid results; redirects to cn.bing.com"),
    SiteProfile("brave", "Brave Search", "search", "https://search.brave.com/",
                "https://search.brave.com/search?q={q}", adapter="brave",
                default_enabled=True,
                note="2026-11-15: 5/5 valid results; title is .search-snippet-title"),
    SiteProfile("github", "GitHub", "en_community", "https://github.com/",
                "https://github.com/search?q={q}&type=issues", default_enabled=True,
                note="2026-11-15: 5/5 valid results",
                result_pattern=r"^https://github\.com/[^/?#]+/[^/?#]+/(?:issues|pull|discussions)/\d+"),
    SiteProfile("reddit", "Reddit", "en_community", "https://www.reddit.com/",
                "https://www.reddit.com/search/?q={q}",
                note="2026-11-15: native search redirects to login; discovered through Google, thread body reads (2896 chars)",
                search_via="google", default_enabled=True,
                result_pattern=r"^https://(?:www\.|old\.)?reddit\.com/r/[^/?#]+/comments/"),
    SiteProfile("stackoverflow", "Stack Overflow", "en_community",
                "https://stackoverflow.com/", "https://stackoverflow.com/search?q={q}",
                note="2026-11-15: native search redirects to /nocaptcha; discovered through Google (5/5, 3.5s)",
                search_via="google", default_enabled=True,
                result_pattern=r"^https://stackoverflow\.com/questions/\d+"),
    SiteProfile("hn", "Hacker News Search", "en_community", "https://hn.algolia.com/",
                "https://hn.algolia.com/?query={q}&type=story",
                result_selector="div.Story_title a", default_enabled=True,
                note="2026-11-15: ?q= renders nothing; ?query=&type=story gives story links",
                result_pattern=r"^https://news\.ycombinator\.com/item\?id=\d+"),
    SiteProfile("v2ex", "V2EX", "zh_community", "https://www.v2ex.com/",
                "https://www.v2ex.com/search?q={q}", needs_login=True,
                default_enabled=True, note="2026-11-15: 5/5 valid results",
                result_pattern=r"^https://(?:www\.)?v2ex\.com/t/\d+"),
    SiteProfile("linuxdo", "LINUX DO", "zh_community", "https://linux.do/",
                "https://linux.do/search?q={q}", needs_login=True,
                note="2026-11-15: native search needs a login; discovered through Google, topic body reads (3523 chars)",
                search_via="google", default_enabled=True,
                result_pattern=r"^https://linux\.do/t/[^/?#]+/\d+"),
    SiteProfile("zhihu", "知乎", "zh_community", "https://www.zhihu.com/",
                "https://www.zhihu.com/search?type=content&q={q}", needs_login=True,
                result_selector='.SearchResult-Card a[href*="/question/"]',
                note=(
                    "2026-11-15: logged-in session; classic answer cards extract 5/5, "
                    "but some queries render an AI-only page with no question links, "
                    "so it stays opt-in until that is stable"
                ),
                result_pattern=r"^https://(?:www\.)?zhihu\.com/question/\d+|^https://zhuanlan\.zhihu\.com/p/\d+"),
    SiteProfile("juejin", "稀土掘金", "zh_community", "https://juejin.cn/",
                "https://juejin.cn/search?query={q}", default_enabled=True,
                note="2026-11-15: 5/5 valid results",
                result_pattern=r"^https://juejin\.cn/post/\d+"),
    SiteProfile("huggingface", "Hugging Face", "domain", "https://huggingface.co/",
                "https://huggingface.co/search/full-text?q={q}", default_enabled=True,
                note="2026-11-15: 5/5 valid results",
                result_pattern=r"^https://huggingface\.co/(?!organizations|papers|datasets|spaces|models|login|join|pricing|courses|blog|docs|tasks|search|inference|enterprise|chat|support|security|terms|privacy|api)[^/?#]+/[^/?#]+"),
    SiteProfile("arxiv", "arXiv", "domain", "https://arxiv.org/",
                "https://arxiv.org/search/?query={q}&searchtype=all", default_enabled=True,
                note="2026-11-15: valid results for a query with hits; 0 results for an off-topic query",
                result_pattern=r"^https?://arxiv\.org/(?:abs|pdf)/"),
    SiteProfile("steam", "Steam", "domain", "https://store.steampowered.com/",
                "https://store.steampowered.com/search/?term={q}",
                result_selector="a.search_result_row", default_enabled=True,
                note="2026-11-15: results render after the first paint",
                result_pattern=r"^https://store\.steampowered\.com/app/\d+"),
    SiteProfile("bilibili", "哔哩哔哩", "domain", "https://www.bilibili.com/",
                "https://search.bilibili.com/all?keyword={q}",
                result_selector=".bili-video-card__info--right a",
                result_pattern=r"^https://www\.bilibili\.com/video/BV[0-9A-Za-z]+",
                default_enabled=True,
                note="2026-11-15: public search, 5/5 valid twice (~4.5s); video pages need the video pipeline"),
    SiteProfile("miyoushe", "米游社", "domain", "https://www.miyoushe.com/",
                "https://www.miyoushe.com/sr/search?keyword={q}",
                search_variants=(
                    (("原神",), "https://www.miyoushe.com/ys/search?keyword={q}"),
                    (("绝区零",), "https://www.miyoushe.com/zzz/search?keyword={q}"),
                    (("崩坏3", "崩坏三"), "https://www.miyoushe.com/bh3/search?keyword={q}"),
                    (("未定事件簿",), "https://www.miyoushe.com/wd/search?keyword={q}"),
                ),
                result_selector="a.mhy-article-card__link", default_enabled=True,
                note="2026-11-15: /search is 404; each game has its own /<game>/search page (5/5 valid, ~10s)",
                result_pattern=r"^https://www\.miyoushe\.com/(?:sr|ys|zzz|bh3|wd)/article/\d+"),
    SiteProfile("nga", "NGA", "domain", "https://bbs.nga.cn/",
                "https://bbs.nga.cn/search.php?key={q}",
                note="2026-11-15: only registration/footer links extracted",
                result_pattern=r"^https?://(?:bbs\.nga\.cn|ngabbs\.com|nga\.178\.com)/read\.php\?.*tid=\d+"),
    SiteProfile("chiphell", "Chiphell", "domain", "https://www.chiphell.com/",
                "https://www.chiphell.com/search.php?mod=forum&srchtxt={q}",
                note="2026-11-15: search page returns only footer; discovered through Google, thread body reads (4272 chars)",
                search_via="google", default_enabled=True,
                result_pattern=r"^https://www\.chiphell\.com/(?:thread-\d+|forum\.php\?mod=viewthread)"),
    SiteProfile("nowcoder", "牛客", "domain", "https://www.nowcoder.com/",
                "https://www.nowcoder.com/search?query={q}",
                result_selector='a[href*="/feed/main/detail/"]', default_enabled=True,
                note="2026-11-15: results render after the search XHR",
                result_pattern=r"^https://www\.nowcoder\.com/feed/(?:main/)?detail/[0-9a-f]{16,}"),
)

_BY_KEY = {site.key: site for site in SITES}

#: Domain question shapes. Checked before the generic intent routes so that a
#: specific community is not outranked by a generic word such as "recommended".
_DOMAIN_ROUTES: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("原神", "星铁", "崩坏", "米游社", "miyoushe", "配队", "抽卡"),
     ("miyoushe", "nga", "bilibili", "reddit")),
    (("游戏", "steam", "单机", "开黑"),
     ("steam", "bilibili", "reddit")),
    (("显卡", "cpu", "内存", "装机", "硬件", "rtx", "笔记本", "chiphell"),
     ("chiphell", "bilibili", "reddit")),
    (("校招", "面试", "找工作", "招聘", "简历", "就业", "牛客"),
     ("nowcoder", "v2ex", "zhihu")),
    (("论文", "arxiv", "paper", "引用", "文献"),
     ("arxiv", "google")),
    (("模型", "微调", "数据集", "权重", "huggingface"),
     ("huggingface", "github", "reddit")),
    (("教程", "教学", "演示", "实操", "视频", "上手", "安装"),
     ("bilibili", "google")),
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


def enabled_platforms() -> dict[str, SiteProfile]:
    """Platform routes available to the semantic search planner."""
    extra = extra_sites()
    return {
        site.key: site for site in SITES
        if site.category != "search" and site.verified
        and (site.default_enabled or site.key in extra)
    }


REQUESTED_PLATFORM_SCOPE_KEY = "requested_platform_scope"

# Group entries use the audited representative URL. Known-link directions
# can contribute to a plan once there is an actual public source URL.
_LINK_ONLY_DOMAINS = frozenset({"t.me", "web.archive.org"})


def platform_index_domain(key: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]+", key) or key in _LINK_ONLY_DOMAINS:
        return ""
    if key == "bbc.com":
        return key
    return key if any(row.startswith(f"{key}|") for row in SOURCE_DIRECTIONS.splitlines()) else ""


def platform_search_query(query: str) -> bool:
    """Only plain terms can be combined with a server-owned site scope."""
    return bool(query.strip()) and not re.search(
        r"\b(?:(?:site|platform)\s*:|OR\b|file:)|[()]|://", query, re.I
    )


def planned_platform_query(value: object) -> str:
    """Encode an optional bounded model direction as a regular planned query."""
    if not isinstance(value, dict) or set(value) != {"site_key", "query"}:
        return ""
    key = value["site_key"]
    query = value["query"]
    if not isinstance(key, str) or not isinstance(query, str) or len(query) > 260:
        return ""
    if not (key in enabled_platforms() or platform_index_domain(key)) or not platform_search_query(query):
        return ""
    return f"platform:{key} {' '.join(query.split())}"


def platform_key_for_query(query: str) -> str:
    token, _, _ = query.partition(" ")
    return token.removeprefix("platform:") if token.startswith("platform:") else ""


def platform_scope_keys(value: str) -> tuple[str, ...]:
    keys = tuple(dict.fromkeys(part.strip() for part in value.split(",") if part.strip()))
    enabled = enabled_platforms()
    return keys if len(keys) <= 3 and all(key in enabled or platform_index_domain(key) for key in keys) else ()


def platform_url_allowed(url: str, keys: tuple[str, ...]) -> bool:
    if not keys:
        return True
    try:
        host = host_of(url)
    except ValueError:
        return False
    enabled = enabled_platforms()
    for key in keys:
        site = enabled.get(key)
        if site and site.result_pattern and re.search(site.result_pattern, url):
            return True
        domain = key if platform_index_domain(key) else host_of(site.home) if site else ""
        domains = ("bbc.com", "bbc.co.uk") if domain in {"bbc.com", "bbc.co.uk"} else (domain,)
        if any(candidate and (host == candidate or host.endswith(f".{candidate}")) for candidate in domains):
            return True
    return False


def platform_read_allowed(payload: Mapping[str, Any], requested_url: str, keys: tuple[str, ...]) -> bool:
    if not keys:
        return True
    # These readers do not return their own verified final destination.
    if payload.get("method") in {"deepseek_fetch", "firecrawl", "jina_reader"}:
        return False
    return platform_url_allowed(str(payload.get("url") or requested_url), keys)


def platform_map_instruction() -> str:
    """Compact capability map for existing model calls, independent of topic."""
    profiles = enabled_platforms()
    by_domain = {host_of(site.home): key for key, site in profiles.items()}
    by_domain.update({"news.ycombinator.com": "hn"} if "hn" in profiles else {})
    lines = []
    for row in SOURCE_DIRECTIONS.splitlines():
        domain, label, topic = row.split("|")
        key = by_domain.get(domain, domain)
        if domain in _LINK_ONLY_DOMAINS:
            method = "L"
        elif key in profiles:
            site = profiles[key]
            method = f"I/{site.search_via}" if site.search_via else "N/login" if site.needs_login else "N"
        else:
            method = "I"
        lines.append(f"{key}|{label}|{topic}|{method}")
    mapped = {line.split("|", 1)[0] for line in lines}
    lines.extend(
        f"{key}|{site.label}|{site.category}|"
        + (f"I/{site.search_via}" if site.search_via else "N/login" if site.needs_login else "N")
        for key, site in profiles.items() if key not in mapped
    )
    return (
        "Platform map (site_key|source direction|topic|capability). N opens native search via Browse, "
        "N/login may require an existing session, I limits an existing public search provider to the listed "
        "domain, I/engine uses the named engine, L needs an already known URL and is not a search key. "
        "I or N may return no useful content. Read candidate URLs with the normal bounded reader. "
        "Search only selected directions; the catalogue is not evidence and does not imply login access, "
        "video transcripts or comments. Respect user scope; use empty site_key for general search.\n"
        + "\n".join(lines)
    )


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


def describe_route(question: str) -> dict[str, list[str]]:
    """Separate the candidate route from what this deployment will execute.

    Candidates are the sites the question shape asks for. A candidate that has
    not passed a real browser probe is listed as skipped, so "the route is
    fixed" can never be read as "Miyoushe actually searched".
    """

    candidates = select_sites(question, include_unverified=True, limit=len(SITES))
    chosen = select_sites(question)
    chosen_keys = {site.key for site in chosen}
    extra = extra_sites()
    skipped = [
        site.key for site in candidates
        if site.key not in chosen_keys
        and not (site.default_enabled or site.key in extra)
    ]
    trimmed = [
        site.key for site in candidates
        if site.key not in chosen_keys and site.key not in skipped
    ]
    return {
        "candidates": [site.key for site in candidates],
        "enabled": [site.key for site in chosen],
        "trimmed": trimmed,
        "skipped": skipped,
    }


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
    """Host used for ``site:`` scoping: lower-case, no leading ``www.``."""

    host = (urlsplit(url).hostname or "").casefold()
    return host[4:] if host.startswith("www.") else host


__all__ = [
    "SITES",
    "SiteProfile",
    "describe",
    "describe_route",
    "extra_sites",
    "host_of",
    "select_sites",
    "site_limit",
    "start_outcomes",
    "take_outcomes",
]
