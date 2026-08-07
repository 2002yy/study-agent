"""Deterministic source-result enrichment for commit-pinned GitHub evidence."""

from __future__ import annotations

import re
from typing import Any


_TOKEN_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[0-9]+|[\u3400-\u9fff]+")
_CAMEL_PART_PATTERN = re.compile(r"[A-Z]+(?=[A-Z][a-z]|\b)|[A-Z]?[a-z]+|[0-9]+")
_FAILURE_CONCLUSIONS = {
    "action_required",
    "cancelled",
    "failure",
    "startup_failure",
    "stale",
    "timed_out",
}
_SUCCESS_CONCLUSIONS = {"success", "neutral", "skipped"}


def _tokens(value: str) -> tuple[str, ...]:
    result: list[str] = []
    for raw in _TOKEN_PATTERN.findall(str(value or "")):
        folded = raw.casefold()
        result.append(folded)
        for segment in raw.replace("$", "_").split("_"):
            if not segment:
                continue
            parts = _CAMEL_PART_PATTERN.findall(segment) or [segment]
            result.extend(part.casefold() for part in parts)
    return tuple(dict.fromkeys(item for item in result if item))


def match_line_range(
    *,
    text: str,
    chunk_start_line: int,
    chunk_end_line: int,
    query: str,
) -> tuple[int, int]:
    """Locate the strongest deterministic query-bearing line inside a chunk.

    Search chunks are intentionally wider than a symbol.  Returning the whole
    chunk as source evidence can therefore make every definition in the chunk
    look relevant.  This function narrows the evidence to the best matching
    line without model inference.  If there is no lexical match it preserves
    the original chunk range as a conservative fallback.
    """

    lines = str(text or "").splitlines()
    query_tokens = set(_tokens(query))
    focused = " ".join(str(query or "").split()).casefold()
    if not lines or not query_tokens:
        return max(1, int(chunk_start_line)), max(1, int(chunk_end_line))

    best: tuple[int, int, int, int] | None = None
    best_offset = 0
    for offset, line in enumerate(lines):
        line_tokens = set(_tokens(line))
        overlap = len(query_tokens & line_tokens)
        exact = int(bool(focused) and focused in line.casefold())
        if not exact and overlap <= 0:
            continue
        coverage = int(1000 * overlap / max(1, len(query_tokens)))
        # Prefer exact phrase, then token coverage, then fewer unrelated tokens,
        # then the earliest stable line.
        rank = (exact, coverage, -len(line_tokens - query_tokens), -offset)
        if best is None or rank > best:
            best = rank
            best_offset = offset

    if best is None:
        return max(1, int(chunk_start_line)), max(1, int(chunk_end_line))
    line = max(1, int(chunk_start_line)) + best_offset
    return line, line


def primary_symbol_for_range(
    symbols: list[Any] | tuple[Any, ...],
    *,
    start_line: int,
    end_line: int,
) -> Any | None:
    """Return the innermost symbol that fully contains the matched source range."""

    candidates: list[Any] = []
    for symbol in symbols:
        evidence = getattr(symbol, "evidence", None)
        if evidence is None:
            continue
        symbol_start = int(getattr(evidence, "start_line", 0) or 0)
        symbol_end = int(getattr(evidence, "end_line", 0) or 0)
        if symbol_start <= start_line and symbol_end >= end_line:
            candidates.append(symbol)
    if not candidates:
        return None

    def rank(symbol: Any) -> tuple[int, int, int, str]:
        evidence = getattr(symbol, "evidence")
        span = int(evidence.end_line) - int(evidence.start_line)
        qualified = str(getattr(symbol, "qualified_name", "") or "")
        depth = qualified.count(".")
        return (span, -depth, int(evidence.start_line), qualified)

    return min(candidates, key=rank)


def summarize_commit_ci(payload: dict[str, Any], *, commit_sha: str) -> dict[str, Any]:
    """Project Provider CI data into a small exact-SHA source-evidence summary.

    CI is supporting evidence only.  Provider failures and missing checks are
    explicit ``unavailable`` states and never invalidate otherwise valid source
    evidence.
    """

    requested_sha = str(commit_sha or "").strip().lower()
    provider_sha = str(payload.get("commit_sha") or "").strip().lower()
    base = {
        "commit_sha": requested_sha,
        "association": "unavailable",
        "overall_status": "unknown",
        "checks": [],
    }
    if not requested_sha:
        return {**base, "error": "missing_commit_sha"}
    if provider_sha and provider_sha != requested_sha:
        return {**base, "error": "commit_sha_mismatch"}
    if payload.get("ok") is not True:
        return {
            **base,
            "error": str(payload.get("error") or "ci_provider_unavailable"),
            "provider_status": str(payload.get("provider_status") or payload.get("status") or "unavailable"),
        }

    normalized: list[dict[str, str]] = []
    for raw in payload.get("check_runs", []):
        if not isinstance(raw, dict):
            continue
        normalized.append(
            {
                "name": str(raw.get("name") or ""),
                "status": str(raw.get("status") or ""),
                "conclusion": str(raw.get("conclusion") or ""),
                "details_url": str(raw.get("details_url") or ""),
            }
        )
    normalized.sort(
        key=lambda item: (
            item["name"].casefold(),
            item["details_url"],
            item["status"],
            item["conclusion"],
        )
    )
    if not normalized:
        return {
            **base,
            "error": "no_check_runs",
            "provider_status": str(payload.get("provider_status") or "complete"),
        }

    statuses = {item["status"].casefold() for item in normalized}
    conclusions = {item["conclusion"].casefold() for item in normalized if item["conclusion"]}
    if any(status != "completed" for status in statuses) or not conclusions:
        overall = "pending"
    elif conclusions & _FAILURE_CONCLUSIONS:
        overall = "failure"
    elif conclusions <= _SUCCESS_CONCLUSIONS:
        overall = "success"
    else:
        overall = "unknown"
    return {
        "commit_sha": requested_sha,
        "association": "verified_exact_sha",
        "overall_status": overall,
        "provider_status": str(payload.get("provider_status") or "complete"),
        "checks": normalized,
    }
