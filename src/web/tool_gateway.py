"""Safe, general-purpose web tools for model-directed research.

This gateway is intentionally separate from the news pipeline: news uses RSS
ranking and a ``news`` SearXNG category, while chat and durable research need
general web search, explicit page reads, and bounded GitHub repository access.
"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
import os
import re
import subprocess
import time
from typing import Any
from urllib.error import HTTPError
from urllib.parse import parse_qs, unquote, urlencode, urlparse
from urllib.request import ProxyHandler, Request, build_opener, urlopen
from xml.etree import ElementTree

from src.news.article_fetcher import fetch_article_read_result
from src.news.search_sources.searxng_source import (
    get_last_searxng_error,
    search_searxng,
    searxng_enabled,
)
from src.web.deepseek_web_tools import fetch_deepseek, search_deepseek
from src.web.github_reader import GitHubSourceReader
from src.web.github_snapshot import GitHubRepositorySnapshotter
from src.web.query_normalizer import normalize_web_query
from src.web.research.read_adequacy import classify_video_page
from src.web.search_router import DUAL, route_search
from src.web.site_pool import SiteProfile, enabled_platforms, platform_index_domain, platform_search_query, take_outcomes


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(
    name: str,    default: float,
    *,
    minimum: float,
    maximum: float,
) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def _search_failure_kind(error: str) -> str:
    """Bounded diagnostic code; never put provider exception URLs in outcomes."""

    value = error.casefold()
    if value == "browse:unexpected_search_page":
        return "unexpected_search_page"
    if "no_results" in value or "empty_response" in value:
        return "no_results"
    if "timeout" in value or "timed out" in value:
        return "timeout"
    if "refused" in value or "connection" in value:
        return "connection_failed"
    if "invalid_json" in value:
        return "invalid_json"
    if "content-type" in value:
        return "unexpected_content_type"
    if "unresponsive_engines" in value:
        return "unresponsive_engines"
    if "http_status" in value:
        return "http_status"
    if "search_budget_exhausted" in value:
        return "search_budget_exhausted"
    return "provider_error"


def _dual_channel_enabled() -> bool:
    """Off by default: the browser lane must be measured before it is default."""

    return _env_flag("WEB_SEARCH_DUAL_CHANNEL", False)


def _browser_search(
    query: str, limit: int, timeout: float, engine: str
) -> tuple[list[dict[str, str]], str]:
    """Run one browser engine search; imported lazily so the fast path stays cheap."""

    from src.web.browse_search import search_browse

    return search_browse(query, limit, timeout, engine=engine)


@dataclass
class _BrowserLane:
    executor: ThreadPoolExecutor
    future: Future[tuple[list[dict[str, str]], str]]
    started: float
    deadline: float
    engine: str


_DUCKDUCKGO_CHALLENGE_MARKERS = (    'class="anomaly-modal',
    'id="challenge-form"',
    "bots use duckduckgo",
)


class _DuckDuckGoResultsParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._href = ""
        self._parts: list[str] = []
        self._capturing = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        values = dict(attrs)
        css_class = values.get("class") or ""
        if "result__a" not in css_class and "result-link" not in css_class:
            return
        self._href = values.get("href") or ""
        self._parts = []
        self._capturing = True

    def handle_data(self, data: str) -> None:
        if self._capturing:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or not self._capturing:
            return
        title = " ".join("".join(self._parts).split())
        url = _unwrap_duckduckgo_url(self._href)
        if title and url:
            self.results.append({"title": title, "url": url})
        self._capturing = False


def _unwrap_duckduckgo_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme in {"http", "https"} and "duckduckgo.com" not in (
        parsed.hostname or ""
    ):
        return url
    target = parse_qs(parsed.query).get("uddg", [""])[0]
    target = unquote(target)
    parsed_target = urlparse(target)
    return target if parsed_target.scheme in {"http", "https"} else ""


def _result_key(item: dict[str, str]) -> str:
    url = (item.get("url") or "").strip()
    if not url:
        return (item.get("title") or "").strip().casefold()
    parsed = urlparse(url)
    # Hosts are case-insensitive; paths and query values can name different
    # pages. A "www." prefix is the same page, and counting it twice would
    # spend a slot that another source should have used.
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return parsed._replace(scheme=parsed.scheme.lower(), netloc=host, fragment="").geturl()


def _query_domain(query: str) -> str:
    """Only enforce the existing simple, positive site: form."""
    matches = list(re.finditer(r"(?<!\S)site:([A-Za-z0-9.-]+)(?=\s|$)", query))
    if len(matches) == 1 and not re.search(r"(?:\bOR\b|-site:|[()])", query):
        return matches[0].group(1).lower().rstrip(".")
    return ""


def _domain_results(rows: list[dict[str, str]], domain: str) -> list[dict[str, str]]:
    if not domain:
        return rows
    return [
        item
        for item in rows
        if (host := (urlparse(item.get("url", "")).hostname or "").lower().rstrip("."))
        == domain
        or host.endswith("." + domain)
    ]


def _provider_timeout(
    deadline: float, limit: float, provider: str, errors: list[str]
) -> float:
    """Time left for one provider, and the shared "budget exhausted" report.

    Every strategy needs the same two rules: never start a provider with less
    than a quarter second left, and record why a provider was skipped. Keeping
    one copy stops the strategies from drifting apart on that decision.
    """

    left = deadline - time.monotonic()
    if left < 0.25:
        errors.append(f"{provider}:search_budget_exhausted")
        return 0.0
    return min(limit, left)


def _dedupe_results(items: list[dict[str, str]], limit: int) -> list[dict[str, str]]:
    seen: set[str] = set()
    result: list[dict[str, str]] = []
    for item in items:
        key = _result_key(item)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item)
        if len(result) >= limit:
            break
    return result


def _merge_site_results(
    grouped: list[tuple[str, list[dict[str, str]]]], limit: int
) -> list[dict[str, str]]:
    """Take from every site before one site fills the whole answer.

    Groups arrive in route order and each keeps its own ranking. One result per
    site is taken in turn, so the first slot of every productive site appears
    before a second slot from any of them. A site that found nothing simply
    contributes nothing; a query with a single productive site still returns
    that site's ranking.
    """

    def key(row: dict[str, str]) -> str:
        return _result_key(row)

    productive = [(site, rows) for site, rows in grouped if rows]
    seen: set[str] = set()
    merged: list[dict[str, str]] = []
    cursors = [0] * len(productive)
    while len(merged) < limit:
        progressed = False
        for index, (_site, rows) in enumerate(productive):
            while len(merged) < limit and cursors[index] < len(rows):
                row = rows[cursors[index]]
                cursors[index] += 1
                marker = key(row)
                if not marker or marker in seen:
                    continue
                seen.add(marker)
                merged.append(row)
                progressed = True
                break
        if not progressed:
            break
    return merged[:limit]


SEARCH_STRATEGIES = (
    "fallback",
    "merge",
    "ddg_first",
    "browser_first",
    "browse_sites",
    "deepseek_first",
)
_DEFAULT_SEARCH_STRATEGY = "fallback"
_DEFAULT_AUDIO_SECONDS = 240
_MERGE_TRACE_KEYS = (
    "search_strategy",
    "providers_attempted",
    "providers_skipped",
    "provider_counts",
    "fallback_used",
    "merged_count",
    "duplicate_count",
    "ranked_urls",
)


def _configured_search_strategy() -> str:
    """The strategy the process asks for, defaulting to the unchanged fallback.

    Deployment needs a way to switch strategy without editing code, but an
    unknown value must fail loudly instead of silently running something else.
    """

    raw = (os.getenv("WEB_SEARCH_STRATEGY") or _DEFAULT_SEARCH_STRATEGY).strip().lower()
    if raw not in SEARCH_STRATEGIES:
        raise ValueError(
            f"unknown WEB_SEARCH_STRATEGY {raw!r}; expected one of {list(SEARCH_STRATEGIES)}"
        )
    return raw


def merge_trace(outcome: dict[str, Any]) -> dict[str, Any]:
    """The merge decision fields of a search payload, empty when none ran.

    ``providers_attempted`` also exists on the fallback path, so its presence is
    not evidence of a merge. Only ``search_strategy`` is: without it the caller
    would read a single-engine search as a two-engine one.
    """

    if not outcome.get("search_strategy"):
        return {}
    return {key: outcome[key] for key in _MERGE_TRACE_KEYS if key in outcome}


def _rank_merged(results: list[dict[str, str]], query: str) -> list[dict[str, str]]:
    """Order merged results with the repository's own source scorer.

    The scorer is deliberately not the evaluation rule: ranking by the signal the
    metrics measure would make the candidate arm score itself. ``assess_sources``
    is a production relevance heuristic; its known weakness on Chinese
    single-character overlap is a finding to report, not a bug to paper over.
    """

    from src.web.source_assessment import assess_sources

    assessed, _rejected = assess_sources(results, canonical_query=query)
    scored: list[tuple[float, int, dict[str, str]]] = []
    for index, record in enumerate(assessed):
        item = record.get("item") if isinstance(record, dict) else None
        if not isinstance(item, dict) or not item.get("url"):
            continue
        assessment = record.get("assessment") if isinstance(record, dict) else {}
        score = float((assessment or {}).get("relevance") or 0.0)
        scored.append((score, index, item))
    ranked = [
        item
        for _score, _index, item in sorted(scored, key=lambda row: (-row[0], row[1]))
    ]
    # Anything the assessor dropped keeps its relative order at the end rather
    # than disappearing: a merge that silently loses one provider's results would
    # look like a ranking improvement.
    known = {str(item.get("url") or "") for item in ranked}
    ranked.extend(item for item in results if str(item.get("url") or "") not in known)
    return ranked


def _snapshot_search_results(
    snapshot: dict[str, Any],
    *,
    max_results: int,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for item in snapshot.get("files", [])[:max_results]:
        if not isinstance(item, dict):
            continue
        results.append(
            {
                "name": str(item.get("path") or "").rsplit("/", 1)[-1],
                "path": str(item.get("path") or ""),
                "sha": str(item.get("sha") or ""),
                "url": str(item.get("url") or ""),
                "repository": str(snapshot.get("repository") or ""),
                "score": int(item.get("score") or 0),
            }
        )
    return results


_READ_ERROR_CODE_BY_REASON = {
    "unsafe_or_empty_url": "invalid_url",
    "empty_cache_entry": "fetch_failed",
    "unsafe_redirect_target": "blocked",
    "non_html_resource": "unsupported",
    "all_backends_failed": "provider_failed",
}


def _canonical_read_error_code(reason: str) -> str:
    value = str(reason or "").strip()
    if value.startswith("exception:"):
        return "provider_failed"
    return _READ_ERROR_CODE_BY_REASON.get(value, "other")


def _browse_read(
    url: str, max_chars: int, timeout: float,
    *, include_discussion: bool = False, max_comments: int = 0,
) -> dict[str, Any]:
    """One browse read attempt; failures come back as a result, never a raise."""

    from src.web.browse_read import read_browse

    try:
        return read_browse(
            url, max_chars=max_chars, timeout=timeout,
            include_discussion=include_discussion, max_comments=max_comments,
        )
    except (OSError, ValueError, TypeError) as exc:
        return {
            "ok": False,
            "kind": "web_page",
            "url": url,
            "method": "browse",
            "error": f"{type(exc).__name__}: {exc}",
            "error_code": "browse_failed",
        }


def _read_video(
    url: str, max_chars: int, timeout: float,
    *, start_seconds: int = 0, video_seconds: int = 180,
    include_ocr: bool = False,
) -> dict[str, Any]:
    """One video read; a missing media toolchain is a result, not a raise."""

    from src.web.video_read import read_video

    try:
        return read_video(
            url, max_chars=max_chars, timeout=timeout,
            start_seconds=start_seconds, max_seconds=video_seconds,
            include_ocr=include_ocr,
        )
    except (OSError, ValueError, TypeError, subprocess.SubprocessError) as exc:
        return {
            "ok": False,
            "kind": "video",
            "url": url,
            "error": f"{type(exc).__name__}: {exc}",
            "error_code": "video_failed",
        }


def _read_audio(
    url: str, max_chars: int, timeout: float,
    *, start_seconds: int = 0, audio_seconds: int = 240,
) -> dict[str, Any]:
    """One audio read; a missing FFmpeg/ASR toolchain is a result, not a raise."""

    from src.web.audio_read import read_audio

    try:
        return read_audio(
            url, max_chars=max_chars, timeout=timeout,
            start_seconds=start_seconds, max_seconds=audio_seconds,
        )
    except (OSError, ValueError, TypeError, subprocess.SubprocessError) as exc:
        return {
            "ok": False,
            "kind": "audio",
            "url": url,
            "error": f"{type(exc).__name__}: {exc}",
            "error_code": "audio_failed",
        }


def _read_comments(
    url: str, page: int, limit: int, timeout: float,
) -> dict[str, Any]:
    from src.web.bilibili_comments import read_comments

    try:
        return read_comments(url, page=page, limit=limit, timeout=timeout)
    except (OSError, ValueError, TypeError) as exc:
        return {
            "ok": False,
            "kind": "comments",
            "url": url,
            "error": f"{type(exc).__name__}: {exc}",
            "error_code": "comments_failed",
        }


def _browse_read_available() -> bool:
    """Browse reads are on by default; an explicit off switch still wins."""

    raw = os.getenv("WEB_BROWSE_READ_ENABLED")
    if raw is not None and raw.strip().lower() in {"0", "false", "no", "off"}:
        return False
    import shutil

    return shutil.which("browse") is not None


def _browse_short_read_chars() -> int:
    from src.web.browse_read import SHORT_READ_CHARS

    return SHORT_READ_CHARS


def _github_release_default_timeout() -> float:
    """Budget for a GitHub release read when the caller names none.

    A release read is one API call with a known shape, and on a slow network it
    is the read most likely to need more than the generic ten seconds. An
    explicit caller timeout always wins, so a research deadline is never
    exceeded by this default.
    """

    try:
        value = float(os.getenv("WEB_GITHUB_RELEASES_TIMEOUT_SECONDS", "15"))
    except ValueError:
        value = 15.0
    return max(5.0, min(value, 30.0))


def _video_read_default_timeout(video_seconds: int) -> float:
    """Budget for a video read when the caller names none.

    A video read downloads the media, transcribes it and may run OCR, so the
    generic ten-second page budget is guaranteed to fail. The section length
    plus one minute for fetch, metadata and transcription keeps the default
    honest without letting one tool call run unbounded. An explicit caller
    timeout always wins.
    """

    seconds = max(15, min(int(video_seconds or 180), 600))
    return float(seconds) + 60.0


def _audio_read_default_timeout(audio_seconds: int) -> float:
    """Budget for an audio read when the caller names none.

    Download plus FFmpeg conversion plus transcription needs the section length
    and some slack; the generic ten-second page budget cannot finish.
    """

    seconds = max(15, min(int(audio_seconds or _DEFAULT_AUDIO_SECONDS), 600))
    return float(seconds) + 90.0


class GeneralWebGateway:
    """Expose bounded search, page reading, and GitHub browsing to model tools."""

    supports_official_metadata = True

    def __init__(
        self,
        github_reader: GitHubSourceReader | None = None,
        github_snapshotter: GitHubRepositorySnapshotter | None = None,
        *,
        search_strategy: str | None = None,
    ) -> None:
        strategy = search_strategy or _configured_search_strategy()
        if strategy not in SEARCH_STRATEGIES:
            raise ValueError(
                f"unknown search strategy {strategy!r}; "
                f"expected one of {list(SEARCH_STRATEGIES)}"
            )
        # The default stays the sequential fallback. "merge" is the Quality-0
        # candidate arm (E2) and "ddg_first" is the Search-1 candidate; both must
        # be requested explicitly: an experiment that changes the production
        # search path by accident would make every other comparison meaningless.
        self.search_strategy = strategy
        self.github_reader = github_reader or GitHubSourceReader()
        self.github_snapshotter = github_snapshotter or GitHubRepositorySnapshotter()

    def search(self, query: str, *, max_results: int = 5) -> list[dict[str, str]]:
        """Compatibility list API used by older callers."""

        payload = self.search_detailed(query, max_results=max_results)
        return list(payload["results"])

    def search_exact(
        self,
        query: str,
        *,
        max_results: int = 5,
        now: datetime | None = None,
        deadline: float | None = None,
        index_only: bool = False,
    ) -> dict[str, Any]:
        """Search one already-planned query without creating more variants."""

        focused = " ".join(str(query or "").split())
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        current = current.astimezone(timezone.utc)
        limit = max(1, min(max_results, 12))
        if not focused:
            return {
                "status": "invalid_query",
                "reason": "empty_query",
                "query": focused,
                "results": [],
                "provider_errors": [],
                "searched_at": current.isoformat(),
            }

        if focused.startswith("platform:"):
            scope, _, phrase = focused.partition(" ")
            return self.search_site(phrase, site_key=scope.removeprefix("platform:"),
                                    max_results=limit, deadline=deadline)
        lane = self._start_browser_lane(focused, limit) if deadline is None and not index_only else None
        outcome = (
            self._search_single(focused, limit) if deadline is None and not index_only
            else self._search_single(focused, limit, deadline=deadline, index_only=index_only)
        )
        if lane is not None:
            outcome = self._merge_browser_lane(outcome, lane, limit)
        results = list(outcome["results"])
        filtered_count = outcome.get("domain_filtered_count", 0)
        provider_errors = list(outcome["provider_errors"])
        providers_enabled = bool(outcome["providers_attempted"])
        outcomes = list(outcome.get("provider_outcomes") or [])
        if results:
            status = "ok"
            reason = "results_found"
        elif not providers_enabled:
            status = "unavailable"
            reason = "no_search_provider_enabled"
        elif provider_errors and len(provider_errors) >= len(
            outcome["providers_attempted"]
        ):
            status = "unavailable"
            reason = "providers_failed"
        else:
            status = "empty"
            reason = "providers_returned_no_results"
        if index_only and not results:
            for code in ("human_action_required", "login_required"):
                if f"browse:{code}" in provider_errors:
                    reason = code
                    break
        trace = self._merge_trace(outcome)
        if trace:
            # The delivered order, after the local domain constraint. Reporting
            # the pre-filter order would let a run claim a source it never gave
            # to the model.
            trace["ranked_urls"] = [str(item.get("url") or "") for item in results]
        return {
            "status": status,
            "reason": "domain_constraint_rejected_results"
            if filtered_count and not results
            else reason,
            "query": focused,
            "results": results,
            "domain_filtered_count": filtered_count,
            "provider_errors": provider_errors,
            "providers_attempted": list(outcome["providers_attempted"]),
            "provider_outcomes": outcomes,
            **{
                key: outcome[key]
                for key in ("site_outcomes", "site_route", "dual_channel")
                if key in outcome
            },
            **trace,
            "searched_at": current.isoformat(),
        }

    def search_site(
        self, query: str, *, site_key: str, max_results: int = 5, deadline: float | None = None,
    ) -> dict[str, Any]:
        """Dispatch one explicitly scoped search through the existing site adapter."""
        if platform_search_query(query):
            site = enabled_platforms().get(site_key)
            if site is not None:
                timeout = min(10.0, deadline - time.monotonic()) if deadline is not None else 10.0
                if timeout < 1.5:
                    return {"status": "unavailable", "reason": "search_budget_exhausted", "results": []}
                return self._search_target_site(query, site, max_results, provider="browse_sites", timeout=timeout)
            domain = platform_index_domain(site_key)
            if domain:
                scoped = f"{query} site:{domain}"
                result = self.search_exact(scoped, max_results=max_results, deadline=deadline, index_only=True)
                return {**result, "site_route": {"target": site_key, "domain": domain}}
        return {"status": "unavailable", "reason": "site_scope_invalid", "results": []}

    def search_community_site(
        self, query: str, *, host: str, max_results: int = 5
    ) -> dict[str, Any]:
        """Search one *verified* community site in the browser, for a source gap.

        This is discovery only. A search hit cannot become evidence without the
        normal ``web_read`` path. Host is chosen by the source-gap planner, but
        is checked against the enabled site catalogue rather than used as a URL.
        """

        from src.web import site_pool

        focused = " ".join(str(query or "").split())
        requested_host = site_pool.host_of(f"https://{host}/")
        scope = re.search(r"\s+site:([a-z0-9.-]+)$", focused, re.IGNORECASE)
        scoped_host = site_pool.host_of(f"https://{scope.group(1)}/") if scope else ""
        phrase = focused[:scope.start()].strip() if scope else ""
        sites = [
            site for site in site_pool.SITES
            if ("news.ycombinator.com" if site.key == "hn"
                else site_pool.host_of(site.home)) == requested_host
            and (site.default_enabled or site.key in site_pool.extra_sites())
            and site.verified
            and (site.category in {"zh_community", "en_community"}
                 or site.key in {"miyoushe", "nowcoder", "chiphell"})
        ]
        if not phrase or requested_host != scoped_host or not sites:
            return {
                "status": "unavailable", "reason": "community_site_not_enabled_or_invalid_scope",
                "query": focused, "results": [], "providers_attempted": [],
                "provider_errors": ["community_browser:invalid_scope"],
                "provider_outcomes": [{"provider": "community_browser", "status": "failed",
                                       "reason": "invalid_scope", "result_count": 0}],
                "site_outcomes": [],
            }
        return {
            **self._search_target_site(phrase, sites[0], max_results, provider="community_browser"),
            "query": focused,
        }

    def _search_target_site(
        self, query: str, site: SiteProfile, max_results: int, *, provider: str, timeout: float = 10.0,
    ) -> dict[str, Any]:
        limit = max(1, min(max_results, 12))
        rows, _error = self._search_browse_sites(query, limit, timeout, target_site=site)
        site_outcomes = take_outcomes()
        raw_status = str(site_outcomes[0].get("status") or "") if site_outcomes else ""
        if rows:
            status, reason = "ok", "results_found"
        elif raw_status in {"browse:no_results", "browse:no_valid_results"}:
            status, reason = "empty", "no_results"
        else:
            status, reason = "unavailable", _search_failure_kind(raw_status or "provider_error")
        if provider == "browse_sites" and raw_status in {"browse:login_required", "browse:human_action_required"}:
            reason = raw_status.removeprefix("browse:")
        return {
            "status": status,
            "reason": reason,
            "query": query,
            "results": rows,
            "providers_attempted": [provider],
            "provider_errors": [] if status != "unavailable" else [f"{provider}:{reason}"],
            "provider_outcomes": [{
                "provider": provider, "status": "failed" if status == "unavailable" else status,
                "reason": reason, "result_count": len(rows), "site": site.key,
            }],
            "site_outcomes": site_outcomes,
            "site_route": {"target": site.key},
        }

    def _start_browser_lane(self, query: str, limit: int) -> _BrowserLane | None:
        """Start the browser channel alongside the fast one, when shape says so."""

        if self.search_strategy in {"browse_sites", "browser_first", "deepseek_first"}:
            return None
        if not _dual_channel_enabled() or route_search(query) != DUAL:
            return None
        if _query_domain(query):
            # A domain-constrained query is the existing domain-first job; a
            # general engine page would ignore the constraint.
            return None
        total = _env_float(
            "WEB_DUAL_CHANNEL_TOTAL_SECONDS", 8.0, minimum=1.0, maximum=20.0
        )
        engine = (os.getenv("WEB_DUAL_CHANNEL_ENGINE") or "bing").strip().lower()
        started = time.monotonic()
        deadline = started + total
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="browser-lane")
        future = executor.submit(_browser_search, query, limit, total, engine)
        return _BrowserLane(
            executor=executor,
            future=future,
            started=started,
            deadline=deadline,
            engine=engine,
        )

    def _merge_browser_lane(
        self, outcome: dict[str, Any], lane: _BrowserLane, limit: int
    ) -> dict[str, Any]:
        """Merge browser rows into one outcome, keeping provenance.

        Browser rows go first for a dual-routed question: the engine page ranked
        a multi-constraint CJK question far better than the aggregated fast path
        did. The channel only adds candidates; every row still needs an ordinary
        ``web_read`` before it can support an answer.
        """

        merge_seconds = max(0.0, lane.deadline - time.monotonic())
        rows: list[dict[str, str]] = []
        error = ""
        try:
            if merge_seconds <= 0:
                raise FutureTimeout()
            rows, error = lane.future.result(timeout=merge_seconds)
        except FutureTimeout:
            error = "browser_timeout"
        except Exception as exc:  # noqa: BLE001 - a lane failure is diagnostic
            error = type(exc).__name__
        finally:
            lane.executor.shutdown(wait=False)
        elapsed_ms = int((time.monotonic() - lane.started) * 1000)
        source_label = f"browser_{lane.engine}"
        clean = [
            {
                "title": str(row.get("title") or ""),
                "url": str(row.get("url") or ""),
                "snippet": str(row.get("snippet") or ""),
                "source": source_label,
            }
            for row in rows
            if isinstance(row, dict) and str(row.get("url") or "").strip()
        ]
        merged: list[dict[str, str]] = []
        seen_urls: set[str] = set()
        # Fast rows keep their order and provenance; the browser only adds
        # candidates the fast channel did not already return.
        for item in [*list(outcome.get("results") or []), *clean]:
            url = str(item.get("url") or "")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            merged.append(item)
        outcome["results"] = merged[:limit]
        kind = _search_failure_kind(error) if error else "no_results"
        outcomes = list(outcome.get("provider_outcomes") or [])
        outcomes.append(
            {
                "provider": "browser_bing",
                "status": (
                    "ok" if clean
                    else "empty" if kind == "no_results"
                    else "failed"
                ),
                "reason": "results_found" if clean else kind,
                "result_count": len(clean),
                "elapsed_ms": elapsed_ms,
            }
        )
        outcome["provider_outcomes"] = outcomes
        attempted = list(outcome.get("providers_attempted") or [])
        if "browser_bing" not in attempted:
            attempted.append("browser_bing")
        outcome["providers_attempted"] = attempted
        if error:
            outcome["provider_errors"] = [
                *(outcome.get("provider_errors") or []),
                f"browser_bing:{error}",
            ]
        outcome["dual_channel"] = {
            "route": DUAL,
            "engine": lane.engine,
            "browser_rows": len(clean),
            "elapsed_ms": elapsed_ms,
            "deadline_ms": int((lane.deadline - lane.started) * 1000),
        }
        return outcome

    def search_detailed(
        self,
        query: str,
        *,
        max_results: int = 5,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        normalization = normalize_web_query(query, now=now)
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        current = current.astimezone(timezone.utc)
        limit = max(1, min(max_results, 12))
        if not normalization.raw_query:
            return {
                **normalization.to_dict(),
                "status": "invalid_query",
                "reason": "empty_query",
                "attempted_queries": [],
                "results": [],
                "provider_errors": [],
                "searched_at": current.isoformat(),
            }

        attempted: list[str] = []
        provider_errors: list[str] = []
        provider_outcomes: list[dict[str, Any]] = []
        results: list[dict[str, str]] = []
        saw_available_provider = False
        variant_traces: list[dict[str, Any]] = []
        adopted_query: str | None = None
        for variant_index, variant in enumerate(normalization.query_variants):
            attempted.append(variant)
            exact = self.search_exact(variant, max_results=limit, now=current)
            provider_outcomes.extend(
                {**row, "query_index": variant_index}
                for row in exact.get("provider_outcomes", [])
            )
            trace = self._merge_trace(exact)
            if trace:
                variant_traces.append({"query": variant, **trace})
            if exact["status"] != "unavailable":
                saw_available_provider = True
            for error in exact.get("provider_errors", []):
                if error and error not in provider_errors:
                    provider_errors.append(str(error))
            if exact["status"] == "unavailable" and exact.get("provider_errors"):
                break
            results = _dedupe_results(
                [*results, *list(exact.get("results", []))],
                limit,
            )
            if results:
                # The results the caller receives come from this variant, so this
                # is the trace that describes them. Keeping the first variant's
                # trace instead would report a merge that produced nothing.
                adopted_query = variant
                break

        if results:
            status = "ok"
            reason = "results_found"
        elif not saw_available_provider:
            status = "unavailable"
            reason = (
                "providers_failed" if provider_errors else "no_search_provider_enabled"
            )
        else:
            status = "empty"
            reason = "providers_returned_no_results"
        payload = {
            **normalization.to_dict(),
            "status": status,
            "reason": reason,
            "attempted_queries": attempted,
            "results": results,
            "provider_errors": provider_errors,
            "provider_outcomes": provider_outcomes,
            "searched_at": current.isoformat(),
        }
        if variant_traces:
            payload["merge_traces"] = variant_traces
            payload["adopted_query"] = adopted_query
            adopted = next(
                (
                    trace
                    for trace in variant_traces
                    if adopted_query is not None and trace["query"] == adopted_query
                ),
                None,
            )
            if adopted is not None:
                # Only an adopted variant describes the delivered answer. With no
                # adopted variant the aggregates are omitted rather than taken
                # from the last attempt, which would present a failed merge as
                # the run's search evidence.
                payload.update(
                    {key: value for key, value in adopted.items() if key != "query"}
                )
            else:
                payload["providers_attempted"] = []
                payload["ranked_urls"] = []
        return payload

    def _search_single(
        self, query: str, limit: int, *, deadline: float | None = None, index_only: bool = False,
    ) -> dict[str, Any]:
        """One provider loop; strategies choose order and whether to keep searching."""
        provider_timeout = _env_float(
            "WEB_SEARCH_PROVIDER_TIMEOUT_SECONDS", 6.0, minimum=1.0, maximum=8.0
        )
        strategy = self.search_strategy
        if index_only and strategy == "browse_sites":
            strategy = "browser_first"
        if strategy == "browse_sites":
            # One provider searches several sites sequentially, so it needs its
            # own budget. The reserve is what keeps SearXNG/Bing RSS/DuckDuckGo
            # reachable after the whole pool failed; a slow pool must not be
            # able to consume the budget that the documented fallback needs.
            started = time.monotonic()
            pool_deadline = started + _env_float(
                "WEB_SITE_POOL_TOTAL_SECONDS", 20.0, minimum=6.0, maximum=36.0
            )
            default_deadline = pool_deadline + _env_float(
                "WEB_SEARCH_FALLBACK_RESERVE_SECONDS", 4.0, minimum=2.0, maximum=8.0
            )
        else:
            pool_deadline = 0.0
            default_deadline = time.monotonic() + _env_float(
                "WEB_SEARCH_TOTAL_TIMEOUT_SECONDS", 8.0, minimum=3.0, maximum=10.0
            )
        deadline = default_deadline if deadline is None else min(deadline, default_deadline)
        pool_deadline = min(pool_deadline, deadline)
        plan = {
            "fallback": ("searxng", "bing_rss", "duckduckgo_html"),
            "browser_first": ("browse", "searxng", "bing_rss", "duckduckgo_html"),
            "browse_sites": ("browse_sites", "searxng", "bing_rss", "duckduckgo_html"),
            "ddg_first": ("duckduckgo_html", "bing_rss"),
            "merge": ("bing_rss", "duckduckgo_html"),
            "deepseek_first": ("deepseek", "searxng", "bing_rss", "duckduckgo_html"),
        }[strategy]
        # No change to existing routing/diagnostics until explicitly enabled.
        # The independent index is tried after SearXNG on regular fallback,
        # or first when selected for a later controlled comparison.
        if _env_flag("WEB_DEEPSEEK_SEARCH_ENABLED") and strategy in {
            "fallback",
            "browser_first",
            "browse_sites",
        }:
            index = plan.index("searxng") + 1
            plan = (*plan[:index], "deepseek", *plan[index:])
        providers = {
            "browse": (True, self._search_browse),
            "browse_sites": (True, self._search_browse_sites),
            "searxng": (searxng_enabled(), self._search_searxng),
            "deepseek": (
                _env_flag("WEB_DEEPSEEK_SEARCH_ENABLED"), self._search_deepseek
            ),
            "bing_rss": (_env_flag("WEB_ENABLE_BING_RSS", True), self._search_bing_rss),
            "duckduckgo_html": (
                _env_flag("WEB_ENABLE_DUCKDUCKGO", True),
                self._search_duckduckgo,
            ),
        }
        domain = _query_domain(query)
        errors: list[str] = []
        attempted: list[str] = []
        skipped: list[dict[str, str]] = []
        provider_outcomes: list[dict[str, Any]] = []
        counts: dict[str, int] = {}
        collected: list[dict[str, str]] = []
        filtered_count = 0
        fallback_used = False
        for index, name in enumerate(plan):
            enabled, fetch = providers[name]
            if not enabled:
                if strategy != "fallback":
                    errors.append(f"{name}:provider_disabled")
                skipped.append({"provider": name, "reason": "provider_disabled"})
                provider_outcomes.append({
                    "provider": name, "status": "skipped",
                    "reason": "provider_disabled", "result_count": 0,
                })
                continue
            if name == "browse_sites":
                timeout = max(0.0, pool_deadline - time.monotonic())
                if timeout <= 1.0:
                    errors.append("browse_sites:search_budget_exhausted")
                    skipped.append({"provider": name, "reason": "search_budget_exhausted"})
                    provider_outcomes.append({
                        "provider": name, "status": "skipped",
                        "reason": "search_budget_exhausted", "result_count": 0,
                    })
                    continue
            else:
                timeout = _provider_timeout(deadline, provider_timeout, name, errors)
            if not timeout:
                skipped.append({"provider": name, "reason": "search_budget_exhausted"})
                provider_outcomes.append({
                    "provider": name, "status": "skipped",
                    "reason": "search_budget_exhausted", "result_count": 0,
                })
                continue
            attempted.append(name)
            fallback_used = fallback_used or index > 0
            rows, error = fetch(query, limit, timeout)
            counts[name] = len(rows)
            kind = _search_failure_kind(error) if error else "no_results"
            if error in {"browse:human_action_required", "browse:login_required"}:
                kind = error.removeprefix("browse:")
            eligible = _domain_results(rows, domain)
            provider_outcomes.append({
                "provider": name,
                "status": "ok" if eligible else "empty" if rows or kind == "no_results" else "failed",
                "reason": "results_found" if eligible else "domain_constraint_rejected_results" if rows else kind,
                "result_count": len(eligible),
            })
            if error:
                errors.append(error)
            if error == "browse:human_action_required":
                break
            filtered_count += len(rows) - len(eligible)
            collected.extend(eligible)
            # A provider returning unrelated sites is not a successful search.
            if eligible and (index_only or strategy != "merge"):
                break

        unique = _dedupe_results(collected, len(collected))
        results = (
            _rank_merged(unique, query)[:limit]
            if strategy == "merge"
            else unique[:limit]
        )
        payload: dict[str, Any] = {
            "results": results,
            "provider_errors": errors,
            "providers_attempted": attempted,
            "provider_outcomes": provider_outcomes,
            "domain_filtered_count": filtered_count,
        }
        if strategy != "fallback":
            payload.update(search_strategy=strategy, provider_counts=counts)
        if strategy == "browse_sites":
            from src.web import site_pool

            payload["site_outcomes"] = site_pool.take_outcomes()
            payload["site_route"] = site_pool.describe_route(query)
        if strategy == "ddg_first":
            payload["fallback_used"] = fallback_used
        elif strategy == "merge":
            payload.update(
                merged_count=sum(counts.values()),
                duplicate_count=len(collected) - len(unique),
                providers_skipped=skipped,
                ranked_urls=[item.get("url", "") for item in results],
            )
        return payload

    @staticmethod
    def _search_browse(query: str, limit: int, timeout: float):
        from src.web.browse_search import search_browse

        return search_browse(query, limit, timeout)

    def _search_browse_sites(
        self, query: str, limit: int, timeout: float, *, target_site=None
    ):
        """Search the selected sites in order, one browser page each.

        Every selected site is visited: the pool exists to compare sources, so a
        first site returning ``limit`` rows must not hide the others. The final
        list is still truncated to ``limit``.
        """

        from src.web import site_pool
        from src.web.browse_search import search_browse_at

        deadline = time.monotonic() + max(1.5, timeout)
        site_seconds = _env_float(
            "WEB_SITE_POOL_SITE_SECONDS", 12.0, minimum=5.0, maximum=18.0
        )
        outcomes = site_pool.start_outcomes()
        grouped: list[tuple[str, list[dict[str, str]]]] = []
        seen_urls: set[str] = set()
        for site in ([target_site] if target_site is not None else site_pool.select_sites(query)):
            remaining = deadline - time.monotonic()
            if remaining < 1.5:
                outcomes.append({"site": site.key, "status": "budget_exhausted",
                                 "seconds": 0.0, "results": 0, "page_results": 0})
                continue
            if site.search_via:
                from src.web.browse_search import _valid_rows, search_browse

                started = time.monotonic()
                scoped = f"{query} site:{site_pool.host_of(site.home)}"
                rows, error = search_browse(
                    scoped,
                    max(limit * 2, 8),
                    min(site_seconds, remaining),
                    engine=site.search_via,
                )
                found = len(rows)
                rows = _valid_rows(
                    rows,
                    limit,
                    source=f"{site.label} via {site.search_via}",
                    pattern=site.result_pattern,
                )
                meta = {
                    "status": "ok" if rows else (error or "browse:no_valid_results"),
                    "seconds": round(time.monotonic() - started, 2),
                    "page_results": found,
                }
            elif site.adapter != "generic":
                from src.web.browse_search import search_browse

                started = time.monotonic()
                rows, error = search_browse(
                    query, limit, min(site_seconds, remaining), engine=site.adapter
                )
                meta = {"status": "ok" if rows else (error or "browse:no_results"),
                        "seconds": round(time.monotonic() - started, 2),
                        "page_results": len(rows)}
            else:
                rows, error, meta = search_browse_at(
                    site.search_url(query),
                    limit,
                    min(site_seconds, remaining),
                    source=f"{site.label} via browse",
                    selector=site.result_selector,
                    pattern=site.result_pattern,
                    own_hosts=site.own_hosts,
                    wait_for=site.wait_selector,
                    require_search_page=site.require_search_page,
                )
            fresh = 0
            for row in rows:
                marker = _result_key(row)
                if marker and marker not in seen_urls:
                    seen_urls.add(marker)
                    fresh += 1
            outcomes.append({
                "site": site.key,
                "status": meta.get("status") or (error or "ok"),
                "seconds": meta.get("seconds", 0.0),
                "results": len(rows),
                "page_results": meta.get("page_results", len(rows)),
                "new_results": fresh,
                "via": site.search_via or (site.adapter if site.adapter != "generic" else "site"),
            })
            grouped.append((site.key, rows))
        unique = _merge_site_results(grouped, limit)
        return unique, "" if unique else "browse:no_results"

    @staticmethod
    def _search_deepseek(
        query: str, limit: int, timeout: float
    ) -> tuple[list[dict[str, str]], str]:
        return search_deepseek(query, limit, timeout)

    @staticmethod
    def _search_searxng(
        query: str, limit: int, timeout: float
    ) -> tuple[list[dict[str, str]], str]:
        rows = search_searxng(
            query,
            max_results=limit,
            timeout=timeout,
            categories=os.getenv("WEB_SEARXNG_CATEGORIES", "general"),
        )
        results = [
            {
                "title": str(item.get("title", "")),
                "url": str(item.get("link") or item.get("resolved_link") or ""),
                "snippet": str(item.get("search_excerpt") or item.get("summary") or ""),
                "source": str(item.get("source") or "SearXNG"),
                "published_at": str(item.get("published_at") or ""),
            }
            for item in rows[:limit]
            if item.get("title") and (item.get("link") or item.get("resolved_link"))
        ]
        error = get_last_searxng_error() if not rows else ""
        return results, f"searxng:{error}" if error else ""

    @staticmethod
    def _merge_trace(outcome: dict[str, Any]) -> dict[str, Any]:
        """Carry the E2 decision fields through the compatibility wrappers.

        Empty for the fallback strategy: those fields describe a merge that did
        not happen, and a trace that always contains them would let a caller
        believe both providers were consulted when only one was.
        """

        return merge_trace(outcome)

    def read(
        self, url: str, *, max_chars: int = 6000, timeout: float | None = None,
        mode: str = "auto", include_discussion: bool = False,
        max_comments: int = 0, start_seconds: int = 0, video_seconds: int = 180,
        include_ocr: bool = False, comment_page: int = 1,
        audio_seconds: int = 240,
    ) -> dict[str, Any]:
        value = str(url or "").strip()
        from src.web.research.official_resolver import read_official_metadata

        mode = str(mode or "auto").strip().lower()
        position = max(0, min(int(max_comments or 0), 50))
        include_discussion = bool(include_discussion) and mode != "http"
        if mode not in {"auto", "http", "browse", "video", "comments", "audio"}:
            return {
                "ok": False,
                "url": value,
                "error": f"unknown read mode {mode!r}",
                "error_code": "invalid_mode",
            }
        # A direct audio file is a transcript read, not a page: sending an MP3
        # through the article reader would decode it as text and "succeed".
        from src.web.audio_read import looks_like_audio_url

        wants_audio = mode == "audio" or (
            mode in {"auto", "http"} and looks_like_audio_url(value)
        )

        # One budget for the whole read, not one budget per stage: the metadata
        # probe, the GitHub reader and the article fetcher must not each get the
        # caller's timeout, or a 6 s read can take 18 s.
        if timeout is not None:
            budget = float(timeout)
        elif mode == "video":
            # A video read is download + transcript + optional OCR, not a page
            # fetch. The 10 s page budget made every tool-level video read die
            # as video_timeout before the transcript could even start.
            budget = _video_read_default_timeout(video_seconds)
        elif wants_audio:
            budget = _audio_read_default_timeout(audio_seconds)
        elif self.github_reader.supports(value) and "/releases" in value:
            budget = _github_release_default_timeout()
        else:
            budget = 10.0
        deadline = time.monotonic() + max(0.5, budget)

        def remaining() -> float:
            return deadline - time.monotonic()

        def exhausted() -> dict[str, Any]:
            # A stage must not start once the read has no time left: the old
            # floor (max(0.5, ...)) let an exhausted budget open a fresh network
            # request, so a 6 s read could still run an article fetch.
            return {
                "ok": False,
                "url": value,
                "error": "read_timeout",
                "error_code": "timeout",
            }

        # A browser-first search must not be followed by a browser-last read.
        # An explicit mode="browse" goes straight to the paired browser; the
        # default "auto" keeps the cheap HTTP path first unless the deployment
        # already chose browser_first.
        if mode == "comments":
            return _read_comments(value, comment_page, position or 20, remaining())
        if mode == "video":
            return _read_video(
                value, max_chars, remaining(),
                start_seconds=start_seconds, video_seconds=video_seconds,
                include_ocr=include_ocr,
            )
        if wants_audio:
            return _read_audio(
                value, max_chars, remaining(),
                start_seconds=start_seconds, audio_seconds=audio_seconds,
            )

        # Platforms with a stable public API are read through it instead of
        # scraping their JS pages; a failure falls back to the normal path.
        # A known-source URL is excluded: an API summary cannot carry the page
        # spans that the official-field publication binds, so answering from it
        # would silently drop the verified author/date.
        from src.web import platform_readers
        from src.web.research.official_resolver import is_official_source_url

        if not is_official_source_url(value) and platform_readers.detect(value):
            platform = platform_readers.read(value, timeout=remaining())
            if platform.get("ok"):
                return platform
        browse_allowed = mode != "http" and _browse_read_available()
        browse_tried = False
        if mode == "browse" and not browse_allowed:
            return {
                "ok": False,
                "kind": "web_page",
                "url": value,
                "method": "browse",
                "error": "browse read is disabled",
                "error_code": "browse_unavailable",
            }
        browse_first = browse_allowed and (
            mode == "browse"
            or include_discussion
            or (mode == "auto" and self.search_strategy == "browser_first")
        )
        if browse_first:
            browse_tried = True
            browsed = _browse_read(
                value, max_chars, remaining(),
                include_discussion=include_discussion, max_comments=position,
            )
            if browsed.get("ok") or mode == "browse":
                return browsed

        # GitHub URLs are read by the GitHub reader. Probing the official-metadata
        # resolver first would spend part of the budget on a stage that cannot
        # serve them.
        if self.github_reader.supports(value):
            if remaining() <= 0.05:
                return exhausted()
            return self.github_reader.read(
                value, max_chars=max_chars, timeout=remaining()
            )
        if remaining() <= 0.05:
            return exhausted()
        official = read_official_metadata(
            value, timeout=remaining(), max_chars=max_chars
        )
        if official is not None:
            return official
        # fetch_article_read_result takes whole seconds. A budget that is still
        # within rounding distance of one second is enough to start; only a
        # sub-half-second remainder means the read is really out of time.
        left = remaining()
        if left < 0.5:
            return exhausted()
        result = fetch_article_read_result(
            value,
            timeout=max(1, int(left)),
            max_chars=max(500, min(max_chars, 20_000)),
        )
        browse_enabled = browse_allowed and not browse_tried
        browse_upgrade = browse_enabled and (
            self.search_strategy == "browser_first"
            or _env_flag("WEB_BROWSE_READ_ENABLED", False)
        )
        if not result.ok:
            # Independent paid Fetch is a last-resort, explicitly enabled
            # fallback; never override an explicit safety refusal from the
            # regular reader by forwarding that URL to an outside vendor.
            # Its DNS/redirect checks are stronger than Fetch's lexical URL
            # preflight, so a denied internal hostname must remain denied.
            refusal = str(result.reason or "").lower()
            security_refused = (
                refusal in {"unsafe_or_empty_url", "unsafe_redirect_target"}
                or refusal.startswith("security_refused:")
            )
            failure = {
                "ok": False,
                "url": result.requested_url,
                "error": result.reason or "page_read_failed",
                "error_code": _canonical_read_error_code(result.reason),
            }
            # The paired browser already holds the user's session. It is free
            # and it is the only path that renders a JS-only page, so it runs
            # before the paid Fetch fallback and never against a refused URL.
            if not security_refused and browse_enabled and remaining() >= 0.5:
                browsed = _browse_read(
                    value, max_chars, remaining(),
                    include_discussion=include_discussion, max_comments=position,
                )
                if browsed.get("ok"):
                    return classify_video_page(browsed, value)
                # Keep the browser's own diagnosis: a login wall, a challenge
                # and a dead connection are different facts for the model.
                failure["browse_error"] = browsed.get("error")
                failure["browse_error_code"] = browsed.get("error_code")
            if (
                not security_refused
                and _env_flag("WEB_DEEPSEEK_FETCH_ENABLED")
                and remaining() >= 0.5
            ):
                fetched, _error = fetch_deepseek(
                    value, max_chars=max_chars, timeout=remaining()
                )
                if fetched is not None:
                    return classify_video_page({
                        "ok": True,
                        "kind": "web_page",
                        "url": value,
                        "method": "deepseek_fetch",
                        "content": fetched["content"],
                        "title": fetched["title"],
                    }, value)
            return failure
        response = {
            "ok": True,
            "kind": "web_page",
            "url": result.final_url or result.requested_url,
            "method": result.method,
            "content": result.text,
        }
        if result.author:
            response["author"] = result.author
        # A static reader can "succeed" with navigation chrome only. When the
        # browser is already in play, ask it for the real body before giving up
        # on the page.
        if (
            browse_upgrade
            and len(str(result.text or "")) < _browse_short_read_chars()
            and remaining() >= 0.5
        ):
            browsed = _browse_read(
                value, max_chars, remaining(),
                include_discussion=include_discussion, max_comments=position,
            )
            if (
                browsed.get("ok")
                and len(str(browsed["content"])) > len(str(response.get("content") or ""))
            ):
                return classify_video_page(browsed, value)
        return classify_video_page(response, value)

    def github_search(
        self,
        repo_url: str,
        query: str,
        *,
        max_results: int = 8,
    ) -> dict[str, Any]:
        result = self.github_reader.search_repository(
            repo_url,
            query,
            max_results=max_results,
        )
        if result.get("ok") is not False:
            return result

        snapshot = self.github_snapshotter.snapshot(
            repo_url,
            query=query,
        )
        if snapshot.get("ok") is not True:
            return result
        return {
            "ok": True,
            "repository": str(snapshot.get("repository") or ""),
            "query": " ".join(str(query or "").split()),
            "mode": "snapshot_fallback",
            "default_branch": str(snapshot.get("default_branch") or ""),
            "results": _snapshot_search_results(
                snapshot,
                max_results=max(1, min(max_results, 20)),
            ),
            "truncated": bool(snapshot.get("tree_truncated")),
            "warning": (
                "github_search_failed; used bounded snapshot fallback: "
                f"{result.get('error', 'unknown_error')}"
            ),
        }

    def github_snapshot(
        self,
        repo_url: str,
        *,
        query: str = "",
        ref: str = "",
    ) -> dict[str, Any]:
        return self.github_snapshotter.snapshot(
            repo_url,
            query=query,
            ref=ref,
        )

    @staticmethod
    def _search_bing_rss(
        query: str,
        limit: int,
        timeout: float,
    ) -> tuple[list[dict[str, str]], str]:
        request = Request(
            "https://www.bing.com/search?" + urlencode({"format": "rss", "q": query}),
            headers={"User-Agent": "StudyAgent/1.0 (+general-web-tool)"},
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                status = int(getattr(response, "status", 200) or 200)
                payload = response.read(500_000)
        except Exception as exc:
            return [], f"bing_rss:{type(exc).__name__}:{exc}"
        if status != 200:
            return [], f"bing_rss:http_status:{status}"
        try:
            root = ElementTree.fromstring(payload)
        except ElementTree.ParseError as exc:
            return [], f"bing_rss:invalid_xml:{exc}"
        results: list[dict[str, str]] = []
        for item in root.findall("./channel/item"):
            title = " ".join((item.findtext("title") or "").split())
            url = (item.findtext("link") or "").strip()
            if not title or urlparse(url).scheme not in {"http", "https"}:
                continue
            results.append(
                {
                    "title": title,
                    "url": url,
                    "snippet": " ".join((item.findtext("description") or "").split()),
                    "source": "Bing RSS",
                    "published_at": "",
                }
            )
            if len(results) >= limit:
                break
        return (results, "" if results else "bing_rss:empty_response")

    # DuckDuckGo publishes no search API, so this reads the same HTML form the
    # site itself posts to. A plain GET with a self-identifying user agent is
    # answered with the anti-bot page (HTTP 202, "anomaly"), so the query goes
    # out as the form's own POST with ordinary browser headers. Both halves were
    # measured against the live endpoint: GET -> 202 challenge, POST -> 200 with
    # result links, which the parser below already understands.
    #
    # Egress is opt-in per provider (WEB_DUCKDUCKGO_PROXY) rather than through a
    # process-wide HTTP(S)_PROXY: docs/CL_M1_REBIND_PREVIEW.md §7 records a local
    # proxy in the process environment hijacking loopback requests and breaking
    # the browser gates (Firefox/WebKit got an empty-Content-Type 404 for
    # 127.0.0.1). A provider-scoped opener keeps that failure mode out of the
    # rest of the process.
    @staticmethod
    def _search_duckduckgo(
        query: str,
        limit: int,
        timeout: float,
    ) -> tuple[list[dict[str, str]], str]:
        request = Request(
            "https://html.duckduckgo.com/html/",
            data=urlencode({"q": query, "b": "", "kl": "wt-wt"}).encode("utf-8"),
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
                ),
                "Accept-Language": "en-US,en;q=0.9",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        proxy = (os.getenv("WEB_DUCKDUCKGO_PROXY") or "").strip()
        try:
            if proxy:
                opener = build_opener(ProxyHandler({"http": proxy, "https": proxy}))
                with opener.open(request, timeout=timeout) as response:
                    status = int(getattr(response, "status", 200) or 200)
                    payload = response.read(500_000).decode("utf-8", errors="ignore")
            else:
                with urlopen(request, timeout=timeout) as response:
                    status = int(getattr(response, "status", 200) or 200)
                    payload = response.read(500_000).decode("utf-8", errors="ignore")
        except HTTPError as exc:
            # urllib raises for 4xx/5xx, so the status has to be taken from the
            # error itself; otherwise every blocked request would surface as an
            # opaque HTTPError string instead of a status code.
            return [], f"duckduckgo_html:http_status:{exc.code}"
        except Exception as exc:
            return [], f"duckduckgo_html:{type(exc).__name__}:{exc}"
        # Only the anti-bot page's own structure counts as a challenge. Matching
        # bare words would reject ordinary result pages: DuckDuckGo echoes the
        # query into the document title, so searching for "coding challenge"
        # returned ten results and used to be reported as a challenge.
        challenge = any(
            marker in payload.casefold() for marker in _DUCKDUCKGO_CHALLENGE_MARKERS
        )
        if challenge:
            return [], "duckduckgo_html:challenge"
        if status != 200:
            return [], f"duckduckgo_html:http_status:{status}"
        parser = _DuckDuckGoResultsParser()
        parser.feed(payload)
        results = [
            {**item, "snippet": "", "source": "DuckDuckGo", "published_at": ""}
            for item in parser.results[:limit]
        ]
        return (results, "" if results else "duckduckgo_html:empty_response")
