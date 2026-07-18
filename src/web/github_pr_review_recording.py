"""Record compact, immutable GitHub PR review-context provider replays."""

from __future__ import annotations

from datetime import datetime, timezone
from time import perf_counter
from typing import Any

from src.web.github_pr_review_context import GitHubPRReviewContextService


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _review_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": str(item.get("kind") or ""),
        "id": str(item.get("id") or ""),
        "path": str(item.get("path") or ""),
        "line": int(item.get("line") or item.get("original_line") or 0),
        "is_resolved": item.get("is_resolved"),
        "mapping": _dict(item.get("mapping")),
        "hunk_mapping": _dict(item.get("hunk_mapping")),
    }


def _ci_association(item: dict[str, Any]) -> dict[str, Any]:
    job = _dict(item.get("job"))
    if job:
        return {
            "job": {
                "id": str(job.get("id") or ""),
                "run_id": str(job.get("run_id") or ""),
                "name": str(job.get("name") or ""),
                "status": str(job.get("status") or ""),
                "conclusion": str(job.get("conclusion") or ""),
                "url": str(job.get("url") or ""),
            },
            "failed_steps": [
                {
                    "name": str(step.get("name") or ""),
                    "number": int(step.get("number") or 0),
                    "conclusion": str(step.get("conclusion") or ""),
                }
                for step in _items(item.get("failed_steps"))
            ],
            "association": _dict(item.get("association")),
        }
    check = _dict(item.get("check"))
    return {
        "check": {
            "id": str(check.get("id") or ""),
            "name": str(check.get("name") or ""),
            "conclusion": str(check.get("conclusion") or ""),
            "url": str(check.get("url") or ""),
        },
        "association": _dict(item.get("association")),
    }


def _label_candidates(result: dict[str, Any]) -> list[dict[str, Any]]:
    impact = _dict(_dict(result.get("source_evidence")).get("change_impact"))
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for change in _items(impact.get("changes")):
        for side in ("old", "new"):
            for symbol in _items(change.get(side)):
                identity = _dict(symbol.get("identity"))
                evidence = _dict(symbol.get("evidence"))
                symbol_id = str(identity.get("id") or "")
                key = (side, symbol_id)
                if not symbol_id or key in seen:
                    continue
                seen.add(key)
                candidates.append(
                    {
                        "side": side,
                        "change_type": str(change.get("type") or ""),
                        "id": symbol_id,
                        "qualified_name": str(symbol.get("qualified_name") or ""),
                        "kind": str(symbol.get("kind") or ""),
                        "language": str(symbol.get("language") or ""),
                        "path": str(evidence.get("path") or ""),
                        "start_line": int(evidence.get("start_line") or 0),
                        "end_line": int(evidence.get("end_line") or 0),
                    }
                )
    return candidates


def compact_recording(
    result: dict[str, Any],
    *,
    elapsed_ms: float,
    recorded_at: str,
) -> dict[str, Any]:
    """Strip provider output to replay evidence without comment/source bodies."""

    if result.get("ok") is not True:
        raise ValueError(str(result.get("error") or "github_provider_replay_failed"))
    base = _dict(result.get("base"))
    head = _dict(result.get("head"))
    base_sha = str(base.get("commit_sha") or "")
    head_sha = str(head.get("commit_sha") or "")
    if len(base_sha) != 40 or len(head_sha) != 40:
        raise ValueError("GitHub provider replay requires immutable base/head SHAs")
    request_budget = _dict(result.get("provider_request_budget"))
    return {
        "provider_status": str(result.get("provider_status") or "unknown"),
        "replay_metadata": {
            "recorded_at": recorded_at,
            "provider_requests": int(request_budget.get("used_requests") or 0),
            "elapsed_ms": round(max(0.0, elapsed_ms), 3),
            "cache_hit": bool(result.get("cache_hit", False)),
        },
        "source": {
            "kind": "github_provider",
            "repository": str(result.get("repository") or ""),
            "pull_request": int(result.get("number") or 0),
            "url": str(result.get("url") or ""),
            "base_sha": base_sha,
            "head_sha": head_sha,
            "cross_repository": bool(result.get("cross_repository", False)),
        },
        "review_items": [
            _review_item(item) for item in _items(result.get("review_items"))
        ],
        "ci_associations": [
            _ci_association(item) for item in _items(result.get("ci_associations"))
        ],
        "label_candidates": _label_candidates(result),
        "evidence_coverage": _dict(result.get("evidence_coverage")),
        "summary": _dict(result.get("summary")),
        "uncertainties": _items(result.get("uncertainties")),
        "provider_request_budget": request_budget,
        "truncated": bool(result.get("truncated", False)),
    }


def record_github_replay_context(
    service: GitHubPRReviewContextService,
    repo_url: str,
    pull_request: int,
    *,
    max_provider_requests: int = 32,
    max_pages_per_collection: int = 10,
) -> dict[str, Any]:
    """Invoke the production provider path and return a compact replay payload."""

    started = perf_counter()
    result = service.build(
        repo_url,
        pull_request,
        max_provider_requests=max_provider_requests,
        max_pages_per_collection=max_pages_per_collection,
    )
    elapsed_ms = (perf_counter() - started) * 1000
    recorded_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    return compact_recording(result, elapsed_ms=elapsed_ms, recorded_at=recorded_at)
