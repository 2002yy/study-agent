"""Safe, general-purpose web tools for model-directed research.

This gateway is intentionally separate from the news pipeline: news uses RSS
ranking and a ``news`` SearXNG category, while chat and durable research need
general web search, explicit page reads, and bounded GitHub repository access.
"""

from __future__ import annotations

from datetime import datetime, timezone
from html.parser import HTMLParser
import os
import re
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
from src.web.github_reader import GitHubSourceReader
from src.web.github_snapshot import GitHubRepositorySnapshotter
from src.web.query_normalizer import normalize_web_query


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(
    name: str,
    default: float,
    *,
    minimum: float,
    maximum: float,
) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


_DUCKDUCKGO_CHALLENGE_MARKERS = (
    'class="anomaly-modal',
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
    return (item.get("url") or item.get("title") or "").strip().casefold()


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


SEARCH_STRATEGIES = ("fallback", "merge")
_MERGE_TRACE_KEYS = (
    "search_strategy",
    "providers_attempted",
    "providers_skipped",
    "merged_count",
    "duplicate_count",
    "provider_counts",
    "ranked_urls",
)


def merge_trace(outcome: dict[str, Any]) -> dict[str, Any]:
    """The merge decision fields of a search payload, empty when none ran.

    ``providers_attempted`` also exists on the fallback path, so its presence is
    not evidence of a merge. Only ``search_strategy`` is: without it the caller
    would read a single-engine search as a two-engine one.
    """

    if not outcome.get("search_strategy"):
        return {}
    return {key: outcome[key] for key in _MERGE_TRACE_KEYS if key in outcome}


def _rank_merged(
    results: list[dict[str, str]], query: str
) -> list[dict[str, str]]:
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
    ranked = [item for _score, _index, item in sorted(scored, key=lambda row: (-row[0], row[1]))]
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


class GeneralWebGateway:
    """Expose bounded search, page reading, and GitHub browsing to model tools."""

    supports_official_metadata = True

    def __init__(
        self,
        github_reader: GitHubSourceReader | None = None,
        github_snapshotter: GitHubRepositorySnapshotter | None = None,
        *,
        search_strategy: str = "fallback",
    ) -> None:
        if search_strategy not in SEARCH_STRATEGIES:
            raise ValueError(
                f"unknown search strategy {search_strategy!r}; "
                f"expected one of {list(SEARCH_STRATEGIES)}"
            )
        # The default stays the sequential fallback. "merge" is the Quality-0
        # candidate arm (E2) and must be requested explicitly: an experiment that
        # changes the production search path by accident would make every other
        # comparison meaningless.
        self.search_strategy = search_strategy
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

        outcome = self._search_single(focused, limit)
        results = list(outcome["results"])
        # Engines do not consistently honor site: syntax. A single positive
        # domain constraint is enforceable locally; complex OR/negative queries
        # keep their existing behavior rather than inventing parser semantics.
        domain_filter = re.fullmatch(r"site:([A-Za-z0-9.-]+)\s+[^()]+", focused)
        filtered_count = 0
        if domain_filter and not re.search(r"(?:\bOR\b|-site:|\bsite:)", focused[domain_filter.end(1):]):
            domain = domain_filter.group(1).lower().rstrip(".")
            scoped = [item for item in results if (
                (urlparse(item.get("url", "")).hostname or "").lower().rstrip(".") == domain
                or (urlparse(item.get("url", "")).hostname or "").lower().rstrip(".").endswith("." + domain)
            )]
            filtered_count = len(results) - len(scoped)
            results = scoped
        provider_errors = list(outcome["provider_errors"])
        providers_enabled = bool(outcome["providers_attempted"])
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
        trace = self._merge_trace(outcome)
        if trace:
            # The delivered order, after the local domain constraint. Reporting
            # the pre-filter order would let a run claim a source it never gave
            # to the model.
            trace["ranked_urls"] = [str(item.get("url") or "") for item in results]
        return {
            "status": status,
            "reason": "domain_constraint_rejected_results" if filtered_count and not results else reason,
            "query": focused,
            "results": results,
            "domain_filtered_count": filtered_count,
            "provider_errors": provider_errors,
            "providers_attempted": list(outcome["providers_attempted"]),
            **trace,
            "searched_at": current.isoformat(),
        }

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
        results: list[dict[str, str]] = []
        saw_available_provider = False
        variant_traces: list[dict[str, Any]] = []
        adopted_query: str | None = None
        for variant in normalization.query_variants:
            attempted.append(variant)
            exact = self.search_exact(variant, max_results=limit, now=current)
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

    def _search_single(self, query: str, limit: int) -> dict[str, Any]:
        provider_timeout = _env_float(
            "WEB_SEARCH_PROVIDER_TIMEOUT_SECONDS",
            6.0,
            minimum=1.0,
            maximum=8.0,
        )
        total_timeout = _env_float(
            "WEB_SEARCH_TOTAL_TIMEOUT_SECONDS",
            8.0,
            minimum=3.0,
            maximum=10.0,
        )
        deadline = time.monotonic() + total_timeout
        results: list[dict[str, str]] = []
        provider_errors: list[str] = []
        providers_attempted: list[str] = []

        if self.search_strategy == "merge":
            return self._search_merged(query, limit, provider_timeout, deadline)

        def remaining_timeout(provider: str) -> float:
            remaining = deadline - time.monotonic()
            if remaining < 0.25:
                provider_errors.append(f"{provider}:search_budget_exhausted")
                return 0.0
            return min(provider_timeout, remaining)

        if searxng_enabled():
            providers_attempted.append("searxng")
            timeout = remaining_timeout("searxng")
            searx_results = (
                search_searxng(
                    query,
                    max_results=limit,
                    timeout=timeout,
                    categories=os.getenv("WEB_SEARXNG_CATEGORIES", "general"),
                )
                if timeout
                else []
            )
            if searx_results:
                results = [
                    {
                        "title": str(item.get("title", "")),
                        "url": str(
                            item.get("link") or item.get("resolved_link") or ""
                        ),
                        "snippet": str(
                            item.get("search_excerpt") or item.get("summary") or ""
                        ),
                        "source": str(item.get("source") or "SearXNG"),
                        "published_at": str(item.get("published_at") or ""),
                    }
                    for item in searx_results[:limit]
                    if item.get("title")
                    and (item.get("link") or item.get("resolved_link"))
                ]
            else:
                error = get_last_searxng_error()
                if error:
                    provider_errors.append(f"searxng:{error}")

        if not results and _env_flag("WEB_ENABLE_BING_RSS", default=True):
            providers_attempted.append("bing_rss")
            timeout = remaining_timeout("bing_rss")
            if timeout:
                bing_results, bing_error = self._search_bing_rss(
                    query, limit, timeout
                )
                results = bing_results
                if bing_error:
                    provider_errors.append(bing_error)

        if not results and _env_flag("WEB_ENABLE_DUCKDUCKGO", default=True):
            providers_attempted.append("duckduckgo_html")
            timeout = remaining_timeout("duckduckgo_html")
            if timeout:
                ddg_results, ddg_error = self._search_duckduckgo(
                    query, limit, timeout
                )
                results = ddg_results
                if ddg_error:
                    provider_errors.append(ddg_error)

        return {
            "results": _dedupe_results(results, limit),
            "provider_errors": provider_errors,
            "providers_attempted": providers_attempted,
        }

    def _search_merged(
        self,
        query: str,
        limit: int,
        provider_timeout: float,
        deadline: float,
    ) -> dict[str, Any]:
        """E2: ask both engines for the same query, merge, then rank.

        The fallback strategy stops at the first engine that answers, so a query
        that two engines would rank differently is decided by whichever answered
        first. This strategy pays a second request to remove that accident, then
        deduplicates and re-ranks with the production source scorer.

        Everything about the decision is reported - which providers were really
        attempted, how many rows each returned, how many were duplicates, and the
        final order - because "both providers were merged" is otherwise only a
        claim about the code, not about the run.
        """

        provider_errors: list[str] = []
        providers_attempted: list[str] = []
        providers_skipped: list[dict[str, str]] = []
        collected: list[dict[str, str]] = []
        provider_counts: dict[str, int] = {}

        def remaining(provider: str) -> float:
            left = deadline - time.monotonic()
            if left < 0.25:
                provider_errors.append(f"{provider}:search_budget_exhausted")
                return 0.0
            return min(provider_timeout, left)

        plan = (
            ("bing_rss", "WEB_ENABLE_BING_RSS", self._search_bing_rss),
            ("duckduckgo_html", "WEB_ENABLE_DUCKDUCKGO", self._search_duckduckgo),
        )
        for name, flag, fetch in plan:
            if not _env_flag(flag, default=True):
                provider_errors.append(f"{name}:provider_disabled")
                providers_skipped.append(
                    {"provider": name, "reason": "provider_disabled"}
                )
                continue
            timeout = remaining(name)
            if not timeout:
                providers_skipped.append(
                    {"provider": name, "reason": "search_budget_exhausted"}
                )
                continue
            # Recorded immediately before the call, never before the decision to
            # make it: a run that reports two engines while calling one would be
            # claiming the experiment it was supposed to prove.
            providers_attempted.append(name)
            rows, error = fetch(query, limit, timeout)
            if error:
                provider_errors.append(error)
            provider_counts[name] = len(rows)
            collected.extend(rows)

        seen: set[str] = set()
        merged: list[dict[str, str]] = []
        duplicates = 0
        for item in collected:
            key = _result_key(item)
            if not key or key in seen:
                duplicates += 1
                continue
            seen.add(key)
            merged.append(item)

        ranked = _dedupe_results(_rank_merged(merged, query), limit)
        return {
            "results": ranked,
            "provider_errors": provider_errors,
            "providers_attempted": providers_attempted,
            "search_strategy": self.search_strategy,
            "merged_count": len(collected),
            "duplicate_count": duplicates,
            "provider_counts": provider_counts,
            "providers_skipped": providers_skipped,
            "ranked_urls": [str(item.get("url") or "") for item in ranked],
        }

    @staticmethod
    def _merge_trace(outcome: dict[str, Any]) -> dict[str, Any]:
        """Carry the E2 decision fields through the compatibility wrappers.

        Empty for the fallback strategy: those fields describe a merge that did
        not happen, and a trace that always contains them would let a caller
        believe both providers were consulted when only one was.
        """

        return merge_trace(outcome)

    def read(
        self, url: str, *, max_chars: int = 6000, timeout: float | None = None
    ) -> dict[str, Any]:
        value = str(url or "").strip()
        from src.web.research.official_resolver import read_official_metadata

        # One budget for the whole read, not one budget per stage: the metadata
        # probe, the GitHub reader and the article fetcher must not each get the
        # caller's timeout, or a 6 s read can take 18 s.
        if timeout is not None:
            budget = float(timeout)
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
        # The article fetcher takes whole seconds, so it needs a whole second
        # left to be worth starting at all.
        if remaining() < 1.0:
            return exhausted()
        result = fetch_article_read_result(
            value,
            timeout=max(1, int(remaining())),
            max_chars=max(500, min(max_chars, 20_000)),
        )
        if not result.ok:
            return {
                "ok": False,
                "url": result.requested_url,
                "error": result.reason or "page_read_failed",
                "error_code": _canonical_read_error_code(result.reason),
            }
        response = {
            "ok": True,
            "kind": "web_page",
            "url": result.final_url or result.requested_url,
            "method": result.method,
            "content": result.text,
        }
        if result.author:
            response["author"] = result.author
        return response

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
                    "snippet": " ".join(
                        (item.findtext("description") or "").split()
                    ),
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
                opener = build_opener(
                    ProxyHandler({"http": proxy, "https": proxy})
                )
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
            marker in payload.casefold()
            for marker in _DUCKDUCKGO_CHALLENGE_MARKERS
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
