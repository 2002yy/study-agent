"""Conservative pull-request review-location to hunk and symbol mapping helpers."""

from __future__ import annotations

from collections import defaultdict
import hashlib
from typing import Any


def as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def dict_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def review_context_id(repository: str, number: int, base_sha: str, head_sha: str) -> str:
    digest = hashlib.sha256(
        f"{repository}\x1f{number}\x1f{base_sha}\x1f{head_sha}".encode("utf-8")
    ).hexdigest()[:24]
    return f"pr_review_{digest}"


def symbol_records(impact: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for change in dict_items(impact.get("changes")):
        for bucket, review_side in (("old", "LEFT"), ("new", "RIGHT")):
            for symbol in dict_items(change.get(bucket)):
                evidence = as_dict(symbol.get("evidence"))
                start = max(1, safe_int(evidence.get("start_line"), 1))
                end = max(start, safe_int(evidence.get("end_line"), start))
                result.append(
                    {
                        "change_id": str(change.get("id") or ""),
                        "change_type": str(change.get("type") or ""),
                        "signature_changed": bool(change.get("signature_changed")),
                        "review_side": review_side,
                        "path": str(evidence.get("path") or ""),
                        "start_line": start,
                        "end_line": end,
                        "name": str(symbol.get("name") or ""),
                        "qualified_name": str(
                            symbol.get("qualified_name") or symbol.get("name") or ""
                        ),
                        "kind": str(symbol.get("kind") or ""),
                        "language": str(symbol.get("language") or ""),
                        "identity": as_dict(symbol.get("identity")),
                        "evidence": evidence,
                    }
                )
    return result


def hunk_records(pull: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for file_item in dict_items(pull.get("files")):
        new_path = str(file_item.get("filename") or "")
        old_path = str(file_item.get("previous_filename") or new_path)
        for index, hunk in enumerate(dict_items(file_item.get("hunks")), start=1):
            records.append(
                {
                    "hunk_id": f"{new_path or old_path}#hunk-{index}",
                    "file_status": str(file_item.get("status") or ""),
                    "old_path": old_path,
                    "new_path": new_path,
                    "old_start": safe_int(hunk.get("old_start")),
                    "old_end": safe_int(hunk.get("old_end")),
                    "new_start": safe_int(hunk.get("new_start")),
                    "new_end": safe_int(hunk.get("new_end")),
                    "patch_truncated": bool(file_item.get("patch_truncated")),
                }
            )
    return records


def path_aliases(impact: dict[str, Any]) -> dict[str, set[str]]:
    aliases: dict[str, set[str]] = defaultdict(set)
    for item in dict_items(impact.get("file_changes")):
        old_path = str(item.get("old_path") or "")
        new_path = str(item.get("new_path") or "")
        if old_path and new_path and old_path != new_path:
            aliases[old_path].add(new_path)
            aliases[new_path].add(old_path)
    return aliases


def changed_paths(impact: dict[str, Any]) -> set[str]:
    return {
        path
        for item in dict_items(impact.get("file_changes"))
        for path in (
            str(item.get("old_path") or ""),
            str(item.get("new_path") or ""),
        )
        if path
    }


def review_items(pull: dict[str, Any]) -> list[dict[str, Any]]:
    review_threads = as_dict(pull.get("review_threads"))
    threads = dict_items(review_threads.get("threads"))
    result: list[dict[str, Any]] = []
    covered_comment_ids: set[int] = set()
    for thread in threads:
        comments = dict_items(thread.get("comments"))
        covered_comment_ids.update(
            safe_int(comment.get("id"))
            for comment in comments
            if safe_int(comment.get("id")) > 0
        )
        body = " ".join(
            str(comments[0].get("body") if comments else "").split()
        )[:1_000]
        result.append(
            {
                "kind": "review_thread",
                "id": str(thread.get("id") or ""),
                "path": str(thread.get("path") or ""),
                "line": safe_int(thread.get("line")),
                "start_line": safe_int(thread.get("start_line")),
                "side": str(thread.get("side") or ""),
                "is_resolved": bool(thread.get("is_resolved")),
                "is_outdated": bool(thread.get("is_outdated")),
                "comments": comments,
                "body": body,
            }
        )
    for comment in dict_items(pull.get("inline_comments")):
        comment_id = safe_int(comment.get("id"))
        if comment_id > 0 and comment_id in covered_comment_ids:
            continue
        result.append(
            {
                "kind": "inline_comment",
                "id": str(comment_id or comment.get("node_id") or ""),
                "path": str(comment.get("path") or ""),
                "line": safe_int(comment.get("line"))
                or safe_int(comment.get("original_line")),
                "start_line": safe_int(comment.get("start_line")),
                "side": str(comment.get("side") or ""),
                "is_resolved": None,
                "is_outdated": False,
                "comments": [comment],
                "body": " ".join(str(comment.get("body") or "").split())[:1_000],
            }
        )
    return result


def _line_range(item: dict[str, Any]) -> tuple[int, int]:
    line = safe_int(item.get("line")) or safe_int(item.get("original_line"))
    start = safe_int(item.get("start_line")) or line
    if start <= 0 and line <= 0:
        return 0, 0
    start = max(1, start or line)
    return start, max(start, line or start)


def _overlaps(start: int, end: int, target_start: int, target_end: int) -> bool:
    if min(start, end, target_start, target_end) <= 0:
        return False
    return start <= target_end and end >= target_start


def _map_hunk(
    item: dict[str, Any], hunks: list[dict[str, Any]]
) -> dict[str, Any]:
    path = str(item.get("path") or "")
    side = str(item.get("side") or "").upper()
    start, end = _line_range(item)
    if not path or start <= 0:
        return {
            "status": "unmapped",
            "confidence": "low",
            "reason": "review_path_or_line_missing",
        }
    candidates: list[dict[str, Any]] = []
    for hunk in hunks:
        if side == "LEFT":
            hunk_path = str(hunk.get("old_path") or "")
            hunk_start = safe_int(hunk.get("old_start"))
            hunk_end = safe_int(hunk.get("old_end"))
        else:
            hunk_path = str(hunk.get("new_path") or "")
            hunk_start = safe_int(hunk.get("new_start"))
            hunk_end = safe_int(hunk.get("new_end"))
        if hunk_path == path and _overlaps(start, end, hunk_start, hunk_end):
            candidates.append(hunk)
    if len(candidates) == 1:
        return {
            "status": "mapped",
            "confidence": "high",
            "reason": "single_containing_diff_hunk",
            "hunk": candidates[0],
        }
    if len(candidates) > 1:
        return {
            "status": "ambiguous",
            "confidence": "low",
            "reason": "multiple_hunks_share_review_location",
            "candidate_count": len(candidates),
            "candidates": candidates[:10],
        }
    file_has_hunks = any(
        path in {str(hunk.get("old_path") or ""), str(hunk.get("new_path") or "")}
        for hunk in hunks
    )
    return {
        "status": "unmapped",
        "confidence": "low",
        "reason": (
            "review_line_not_in_available_hunks"
            if file_has_hunks
            else "patch_hunks_unavailable_for_file"
        ),
        "path": path,
    }


def map_review_item(
    item: dict[str, Any],
    *,
    symbols: list[dict[str, Any]],
    hunks: list[dict[str, Any]],
    aliases: dict[str, set[str]],
    paths: set[str],
) -> dict[str, Any]:
    path = str(item.get("path") or "")
    side = str(item.get("side") or "").upper()
    start, end = _line_range(item)
    accepted_paths = {path, *aliases.get(path, set())} if path else set()
    candidates = [
        symbol
        for symbol in symbols
        if str(symbol.get("path") or "") in accepted_paths
        and (side not in {"LEFT", "RIGHT"} or symbol.get("review_side") == side)
        and (
            start <= 0
            or _overlaps(start, end, symbol["start_line"], symbol["end_line"])
        )
    ]
    mapping: dict[str, Any]
    if candidates:
        smallest_span = min(
            safe_int(candidate.get("end_line"))
            - safe_int(candidate.get("start_line"))
            for candidate in candidates
        )
        narrowest = [
            candidate
            for candidate in candidates
            if safe_int(candidate.get("end_line"))
            - safe_int(candidate.get("start_line"))
            == smallest_span
        ]
        if len(narrowest) == 1:
            selected = narrowest[0]
            mapping = {
                "status": "mapped",
                "confidence": "high" if len(candidates) == 1 else "medium",
                "reason": (
                    "single_containing_symbol"
                    if len(candidates) == 1
                    else "unique_narrowest_containing_symbol"
                ),
                "change_id": selected["change_id"],
                "change_type": selected["change_type"],
                "signature_changed": selected["signature_changed"],
                "symbol": {
                    "name": selected["name"],
                    "qualified_name": selected["qualified_name"],
                    "kind": selected["kind"],
                    "language": selected["language"],
                    "identity": selected["identity"],
                    "evidence": selected["evidence"],
                },
            }
        else:
            mapping = {
                "status": "ambiguous",
                "confidence": "low",
                "reason": "multiple_symbols_share_review_location",
                "candidate_count": len(narrowest),
                "candidates": [
                    {
                        "change_id": candidate["change_id"],
                        "qualified_name": candidate["qualified_name"],
                        "kind": candidate["kind"],
                        "evidence": candidate["evidence"],
                    }
                    for candidate in narrowest[:10]
                ],
            }
    elif path and path in paths:
        mapping = {
            "status": "file_only",
            "confidence": "low",
            "reason": "changed_file_found_but_no_unique_symbol",
            "path": path,
        }
    else:
        mapping = {
            "status": "unmapped",
            "confidence": "low",
            "reason": "review_location_not_in_change_impact",
            "path": path,
        }
    return {
        **item,
        "line_range": {"start_line": start, "end_line": end},
        "hunk_mapping": _map_hunk(item, hunks),
        "mapping": mapping,
    }
