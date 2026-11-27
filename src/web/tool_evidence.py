"""Truthful projection of model web-tool calls into usable evidence."""

from __future__ import annotations

import hashlib
import re

from copy import deepcopy
import ipaddress
from typing import Any, Sequence
from urllib.parse import urlparse

from src.news.url_normalizer import canonicalize_url


def _public_url(value: object) -> str:
    url = str(value or "").strip()
    parsed = urlparse(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username
        or parsed.password
    ):
        return ""
    host = (parsed.hostname or "").strip().casefold()
    if not host or host == "localhost" or host.endswith(".localhost"):
        return ""
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return url
    if (
        address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    ):
        return ""
    return url


def _is_true(value: object) -> bool:
    return value is True or str(value).strip().casefold() == "true"


def _trusted_call_pairs(
    calls: list[dict[str, Any]],
    *,
    user_urls: Sequence[str] = (),
) -> list[tuple[int, dict[str, Any]]]:
    """Sanitized source-bearing calls paired with their original position.

    Admission needs the position because two reads of the same URL can differ
    (one failed, one succeeded); comparing projected payloads would let a later
    success erase the earlier failure.
    """

    trusted: list[tuple[int, dict[str, Any]]] = []
    discovered_urls: set[str] = set()
    # Canonical keys strip fragments and normalize the query, so a section
    # anchor or a user-typed variant still matches its source document.
    discovered_keys: set[str] = {
        key for key in (canonicalize_url(url) for url in user_urls) if key
    }
    for index, raw_call in enumerate(calls):
        if not isinstance(raw_call, dict):
            continue
        name = str(raw_call.get("name") or "")
        result = raw_call.get("result")
        if not isinstance(result, dict) or result.get("error"):
            continue
        call = deepcopy(raw_call)
        projected = call.get("result")
        if not isinstance(projected, dict):
            continue

        if name == "official_resolve":
            from src.web.research.official_resolver import valid_candidate

            arguments = raw_call.get("arguments") or {}
            query = str(arguments.get("query") or "")
            valid = [dict(item) for item in result.get("results") or [] if isinstance(item, dict)
                     and valid_candidate(query, str(item.get("url") or ""))]
            if not valid:
                continue
            projected["results"] = valid
            discovered_urls.update(str(item["url"]).casefold() for item in valid)
            discovered_keys.update(
                key for key in (canonicalize_url(str(item["url"])) for item in valid) if key
            )
            trusted.append((index, call))
            continue

        if name == "web_search":
            if str(result.get("status") or "") != "ok":
                continue
            valid_results = [
                dict(item)
                for item in result.get("results", [])
                if isinstance(item, dict)
                and str(item.get("title") or "").strip()
                and _public_url(item.get("url") or item.get("link"))
            ]
            if not valid_results:
                continue
            projected["results"] = valid_results
            discovered_urls.update(
                _public_url(item.get("url") or item.get("link")).casefold()
                for item in valid_results
            )
            discovered_keys.update(
                key
                for key in (
                    canonicalize_url(_public_url(item.get("url") or item.get("link")))
                    for item in valid_results
                )
                if key
            )
            trusted.append((index, call))
            continue

        if name == "web_read":
            content = result.get("content") or result.get("readme")
            arguments = raw_call.get("arguments")
            arguments = arguments if isinstance(arguments, dict) else {}
            url = _public_url(result.get("url") or arguments.get("url"))
            if not _is_true(result.get("ok")) or not url:
                continue
            requested_url = _public_url(arguments.get("url"))
            # Discovery authorizes the actual read request. The server reader
            # may return a different public canonical URL after redirects.
            # Never add that destination to the search results to manufacture
            # discovery provenance, or accept an undiscovered request because
            # its response claims a previously discovered destination.
            requested_key = canonicalize_url(requested_url)
            if (
                requested_url.casefold() not in discovered_urls
                and (not requested_key or requested_key not in discovered_keys)
            ):
                continue
            if result.get("requested_url") and result["requested_url"] != requested_url:
                continue
            if not isinstance(content, str) or not content.strip():
                continue
            projected["url"] = url
            trusted.append((index, call))
            links = result.get("links")
            if isinstance(links, (list, tuple)):
                for link in links:
                    if not isinstance(link, dict):
                        continue
                    link_url = _public_url(link.get("url") or link.get("link"))
                    key = canonicalize_url(link_url) if link_url else ""
                    if key:
                        discovered_keys.add(key)
            continue

        if name.startswith("github_") and _is_true(result.get("ok")):
            arguments = raw_call.get("arguments")
            arguments = arguments if isinstance(arguments, dict) else {}
            source_url = _public_url(
                result.get("html_url")
                or result.get("url")
                or result.get("repository")
                or arguments.get("repo_url")
            )
            valid_results = [
                dict(item)
                for item in result.get("results", [])
                if isinstance(item, dict)
                and _public_url(item.get("url") or item.get("html_url"))
            ]
            if not source_url and not valid_results:
                continue
            if valid_results:
                projected["results"] = valid_results
            trusted.append((index, call))

    return trusted


def trusted_tool_calls(
    calls: list[dict[str, Any]],
    *,
    user_urls: Sequence[str] = (),
) -> list[dict[str, Any]]:
    """Return sanitized source-bearing calls, including search candidates.

    A successful ``web_search`` proves only that candidate links were
    discovered.  Callers must use :func:`evidence_tool_calls` before treating
    a call as answer evidence.
    """

    return [
        call for _index, call in _trusted_call_pairs(calls, user_urls=user_urls)
    ]


def evidence_tool_calls(
    calls: list[dict[str, Any]],
    *,
    user_urls: Sequence[str] = (),
) -> list[dict[str, Any]]:
    """Return calls that may enter answer context.

    Plain search snippets are deliberately excluded.  A normal web page is
    usable only after a successful, discovery-linked ``web_read``.  GitHub
    tools remain usable because their structured API response is itself the
    bounded primary payload rather than a search-engine snippet.
    """

    return [
        call
        for call in trusted_tool_calls(calls, user_urls=user_urls)
        if (
            str(call.get("name") or "") == "web_read"
            and call.get("result", {}).get("answer_eligible") is not False
        ) or str(call.get("name") or "").startswith("github_")
    ]


def tool_call_errors(calls: list[dict[str, Any]]) -> list[str]:
    """Collect bounded provider/tool failures for durable diagnostics."""

    errors: list[str] = []
    for call in calls:
        if not isinstance(call, dict):
            continue
        name = str(call.get("name") or "web_tool")
        result = call.get("result")
        if not isinstance(result, dict):
            errors.append(f"{name}:invalid_result")
            continue
        if result.get("error"):
            errors.append(f"{name}:{result['error']}")
        for error in result.get("provider_errors", []):
            if str(error).strip():
                errors.append(f"{name}:{error}")
        if str(result.get("status") or "") == "unavailable":
            errors.append(f"{name}:{result.get('reason') or 'provider_unavailable'}")
    return list(dict.fromkeys(errors))[:20]


def diagnostic_tool_calls(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep failure diagnostics without persisting retrieved page content."""

    diagnostics: list[dict[str, Any]] = []
    for call in calls[:20]:
        if not isinstance(call, dict):
            continue
        result = call.get("result")
        result = result if isinstance(result, dict) else {}
        arguments = call.get("arguments")
        arguments = arguments if isinstance(arguments, dict) else {}
        provider_errors = result.get("provider_errors")
        provider_errors = provider_errors if isinstance(provider_errors, list) else []
        diagnostics.append(
            {
                "name": str(call.get("name") or "web_tool"),
                "arguments": dict(arguments),
                "status": str(result.get("status") or ""),
                "reason": str(result.get("reason") or result.get("adequacy_reason") or ""),
                "error": str(result.get("error") or "")[:1000],
                "provider_errors": [
                    str(value)[:1000]
                    for value in provider_errors[:10]
                ],
                "result_count": len(result.get("results", []))
                if isinstance(result.get("results"), list)
                else 0,
            }
        )
        # Semantic fallback details are local validation codes, not source text.
        # Preserve those codes so persisted traces explain rejected plans.
        detail = result.get("detail")
        if (
            call.get("name") == "research_semantic_fallback"
            and isinstance(detail, str)
            and re.fullmatch(r"[a-z_]{1,80}", detail)
        ):
            diagnostics[-1]["detail"] = detail
    return diagnostics


def tool_source_items(
    calls: list[dict[str, Any]],
    *,
    user_urls: Sequence[str] = (),
) -> list[dict[str, Any]]:
    """Project trusted web search/read calls into durable source items."""

    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for call in trusted_tool_calls(calls, user_urls=user_urls):
        name = str(call.get("name") or "")
        result = call.get("result")
        if not isinstance(result, dict):
            continue
        candidates: list[dict[str, Any]] = []
        if name == "web_search":
            candidates = [dict(item) for item in result.get("results", [])]
        elif name == "web_read":
            url = _public_url(result.get("url"))
            candidates = [
                {
                    "title": urlparse(url).netloc,
                    "url": url,
                    "snippet": str(result.get("content") or result.get("readme") or "")[:500],
                    "source": str(result.get("method") or "web_read"),
                }
            ]
        elif name.startswith("github_"):
            arguments = call.get("arguments")
            arguments = arguments if isinstance(arguments, dict) else {}
            url = _public_url(
                result.get("html_url")
                or result.get("url")
                or arguments.get("repo_url")
            )
            if url:
                candidates = [
                    {
                        "title": str(
                            result.get("title")
                            or result.get("repository")
                            or arguments.get("repo_url")
                            or name
                        ),
                        "url": url,
                        "snippet": str(result.get("summary") or result.get("reason") or "")[:500],
                        "source": "GitHub",
                    }
                ]
        for item in candidates:
            url = _public_url(item.get("url") or item.get("link"))
            title = str(item.get("title") or "").strip()
            if not url or not title or url.casefold() in seen:
                continue
            seen.add(url.casefold())
            items.append({**item, "url": url, "link": url})
    return items


def tool_evidence_items(
    calls: list[dict[str, Any]],
    *,
    admitted: Sequence[dict[str, Any]] | None = None,
    user_urls: Sequence[str] = (),
) -> list[dict[str, Any]]:
    """Project answer-usable calls into stable source identities.

    `admitted` lets the caller pass a gate-approved read subset while the
    full call list still supplies search titles and structured metadata.
    """

    safe_calls = trusted_tool_calls(calls, user_urls=user_urls)
    search_titles: dict[str, str] = {}
    for call in safe_calls:
        if str(call.get("name") or "") != "web_search":
            continue
        result = call.get("result")
        if not isinstance(result, dict):
            continue
        for item in result.get("results", []):
            if not isinstance(item, dict):
                continue
            url = _public_url(item.get("url") or item.get("link"))
            title = str(item.get("title") or "").strip()
            if url and title:
                search_titles.setdefault(url.casefold(), title)

    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for call in (
        admitted
        if admitted is not None
        else evidence_tool_calls(calls, user_urls=user_urls)
    ):
        name = str(call.get("name") or "")
        result = call.get("result")
        if not isinstance(result, dict):
            continue
        arguments = call.get("arguments")
        arguments = arguments if isinstance(arguments, dict) else {}
        if name == "web_read":
            url = _public_url(result.get("url") or arguments.get("url"))
            if not url or url.casefold() in seen:
                continue
            seen.add(url.casefold())
            items.append(
                {
                    "title": str(result.get("title") or "").strip()
                    or search_titles.get(url.casefold())
                    or urlparse(url).netloc,
                    "url": url,
                    "link": url,
                    "snippet": str(result.get("content") or result.get("readme") or "")[:500],
                    "source": str(result.get("method") or "web_read"),
                }
            )
            continue
        # Structured GitHub calls are already independently sanitized by
        # ``trusted_tool_calls`` and can reuse the normal item projection.
        for item in tool_source_items([call], user_urls=user_urls):
            url = _public_url(item.get("url") or item.get("link"))
            if not url or url.casefold() in seen:
                continue
            seen.add(url.casefold())
            items.append(item)
    return items

def _admitted_call_indexes(
    pairs: Sequence[tuple[int, dict[str, Any]]],
) -> set[int]:
    """Positions whose projected call may support the final answer."""

    indexes: set[int] = set()
    for index, call in pairs:
        name = str(call.get("name") or "")
        if name == "web_read" and call.get("result", {}).get("answer_eligible") is False:
            continue
        if name == "web_read" or name.startswith("github_"):
            indexes.add(index)
    return indexes


def admit_tool_evidence(
    calls: list[dict[str, Any]],
    *,
    user_urls: Sequence[str] = (),
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Admitted reads plus a bounded reason for each rejected read.

    Reading is exploration; only an admitted read may support the final answer.
    A source is admitted when it was typed by the user, discovered by a search,
    cited by an already-admitted read, or is the same canonical document as one
    of those (fragment/query differences do not hide an anchor).
    """

    pairs = _trusted_call_pairs(calls, user_urls=user_urls)
    admitted_indexes = _admitted_call_indexes(pairs)
    admitted = [call for index, call in pairs if index in admitted_indexes]
    rejected: list[dict[str, str]] = []
    for index, call in enumerate(calls):
        if not isinstance(call, dict) or call.get("name") != "web_read":
            continue
        if index in admitted_indexes:
            continue
        result = call.get("result")
        arguments = call.get("arguments")
        arguments = arguments if isinstance(arguments, dict) else {}
        if not isinstance(result, dict):
            reason = "missing_result"
        elif not _is_true(result.get("ok")):
            reason = "read_failed"
        elif not str(result.get("content") or result.get("readme") or "").strip():
            reason = "empty_content"
        elif result.get("requested_url") and str(
            result["requested_url"]
        ) != (_public_url(arguments.get("url")) or str(result["requested_url"])):
            reason = "redirect_unverified"
        else:
            reason = "source_not_established"
        rejected.append(
            {
                "url": _public_url(
                    result.get("url") if isinstance(result, dict) else ""
                )
                or _public_url(arguments.get("url")),
                "reason": reason,
            }
        )
    return admitted, rejected


#: Exploratory reads are kept for audit even when they never become evidence.
#: The body budget is bounded so one turn cannot store an arbitrary page dump;
#: every record still reports its full size and digest.
EXPLORATION_CONTENT_CHARS = 20000
EXPLORATION_TOTAL_CHARS = 60000
EXPLORATION_MAX_RECORDS = 12


def exploration_read_records(
    calls: list[dict[str, Any]],
    *,
    user_urls: Sequence[str] = (),
    content_chars: int = EXPLORATION_CONTENT_CHARS,
    total_chars: int = EXPLORATION_TOTAL_CHARS,
    max_records: int = EXPLORATION_MAX_RECORDS,
) -> list[dict[str, Any]]:
    """Bounded bodies of successful reads that were not admitted as evidence.

    ``tool_trace.calls`` already carries every admitted read.  This projection
    covers the other case: a page the model read but could not use, whose body
    used to survive only in process memory.  Nothing here becomes answer
    evidence; it exists so a reviewer can see what was explored.
    """

    pairs = _trusted_call_pairs(calls, user_urls=user_urls)
    admitted_indexes = _admitted_call_indexes(pairs)
    records: list[dict[str, Any]] = []
    remaining = max(0, int(total_chars))
    for index, call in enumerate(calls):
        if index in admitted_indexes or not isinstance(call, dict):
            continue
        if call.get("name") != "web_read":
            continue
        result = call.get("result")
        if not isinstance(result, dict) or not _is_true(result.get("ok")):
            continue
        content = result.get("content") or result.get("readme")
        if not isinstance(content, str) or not content.strip():
            continue
        if len(records) >= max_records or remaining <= 0:
            break
        arguments = call.get("arguments")
        arguments = arguments if isinstance(arguments, dict) else {}
        url = _public_url(result.get("url")) or _public_url(arguments.get("url"))
        keep = max(0, min(int(content_chars), remaining, len(content)))
        records.append(
            {
                "url": url,
                "requested_url": _public_url(arguments.get("url")),
                "title": str(result.get("title") or "")[:200],
                "method": str(result.get("method") or ""),
                "chars": len(content),
                "stored_chars": keep,
                "truncated": keep < len(content),
                "digest": hashlib.sha256(
                    content.encode("utf-8", "ignore")
                ).hexdigest()[:12],
                "reason": (
                    "answer_ineligible"
                    if result.get("answer_eligible") is False
                    else "source_not_established"
                ),
                "content": content[:keep],
            }
        )
        remaining -= keep
    return records
