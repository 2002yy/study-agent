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
    """Locate the strongest deterministic query-bearing line inside a chunk."""

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


def _ci_record(raw: dict[str, Any], *, kind: str) -> dict[str, str]:
    return {
        "kind": kind,
        "name": str(raw.get("name") or raw.get("display_title") or ""),
        "status": str(raw.get("status") or ""),
        "conclusion": str(raw.get("conclusion") or ""),
        "details_url": str(raw.get("details_url") or raw.get("url") or ""),
    }


def summarize_commit_ci(payload: dict[str, Any], *, commit_sha: str) -> dict[str, Any]:
    """Project Provider CI data into a small exact-SHA source-evidence summary.

    CI is supporting evidence only. Provider failures and missing checks/runs are
    explicit ``unavailable`` states and never invalidate valid source evidence.
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
            "provider_status": str(
                payload.get("provider_status")
                or payload.get("status")
                or "unavailable"
            ),
        }

    normalized: list[dict[str, str]] = []
    for raw in payload.get("check_runs", []):
        if isinstance(raw, dict):
            normalized.append(_ci_record(raw, kind="check_run"))
    for raw in payload.get("workflow_runs", []):
        if not isinstance(raw, dict):
            continue
        head_sha = str(raw.get("head_sha") or "").strip().lower()
        if head_sha and head_sha != requested_sha:
            continue
        normalized.append(_ci_record(raw, kind="workflow_run"))

    normalized.sort(
        key=lambda item: (
            item["kind"],
            item["name"].casefold(),
            item["details_url"],
            item["status"],
            item["conclusion"],
        )
    )
    if not normalized:
        return {
            **base,
            "error": "no_ci_runs",
            "provider_status": str(payload.get("provider_status") or "complete"),
        }

    statuses = [item["status"].casefold() for item in normalized]
    conclusions = [item["conclusion"].casefold() for item in normalized]
    if any(status != "completed" for status in statuses) or any(
        not conclusion for conclusion in conclusions
    ):
        overall = "pending"
    elif any(conclusion in _FAILURE_CONCLUSIONS for conclusion in conclusions):
        overall = "failure"
    elif all(conclusion in _SUCCESS_CONCLUSIONS for conclusion in conclusions):
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
