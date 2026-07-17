"""Deterministic manifest runner for recorded GitHub PR review-context replays."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.web.github_pr_review_evaluation import evaluate_pr_review_context


_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_REPOSITORY_PATTERN = re.compile(r"^[^/\s]+/[^/\s]+$")


@dataclass(frozen=True)
class GitHubReplayCase:
    case_id: str
    repository: str
    pull_request: int
    base_sha: str
    head_sha: str
    language: str
    scenarios: tuple[str, ...]
    context_path: Path
    expected: dict[str, Any]
    provenance: str
    provider_replay: bool


@dataclass(frozen=True)
class GitHubReplayManifest:
    corpus_id: str
    schema_version: int
    cases: tuple[GitHubReplayCase, ...]


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _required_string(value: Any, field: str) -> str:
    resolved = str(value or "").strip()
    if not resolved:
        raise ValueError(f"GitHub replay case requires {field}")
    return resolved


def _string_tuple(value: Any, field: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"GitHub replay case {field} must be a list")
    resolved = tuple(str(item).strip() for item in value if str(item).strip())
    if not resolved and not allow_empty:
        raise ValueError(f"GitHub replay case requires {field}")
    return resolved


def _context_path(manifest_path: Path, value: Any) -> Path:
    relative = Path(_required_string(value, "context_path"))
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("GitHub replay context_path must stay under the manifest directory")
    root = manifest_path.parent.resolve()
    resolved = (root / relative).resolve()
    if root != resolved and root not in resolved.parents:
        raise ValueError("GitHub replay context_path escapes the manifest directory")
    if not resolved.is_file():
        raise ValueError(f"GitHub replay context not found: {relative.as_posix()}")
    return resolved


def _parse_case(manifest_path: Path, value: Any) -> GitHubReplayCase:
    if not isinstance(value, dict):
        raise ValueError("GitHub replay cases must be objects")
    repository = _required_string(value.get("repository"), "repository")
    if not _REPOSITORY_PATTERN.fullmatch(repository):
        raise ValueError(f"Invalid GitHub replay repository: {repository}")
    base_sha = _required_string(value.get("base_sha"), "base_sha").lower()
    head_sha = _required_string(value.get("head_sha"), "head_sha").lower()
    if not _SHA_PATTERN.fullmatch(base_sha) or not _SHA_PATTERN.fullmatch(head_sha):
        raise ValueError("GitHub replay base_sha and head_sha must be immutable 40-char SHAs")
    pull_request = int(value.get("pull_request") or 0)
    if pull_request <= 0:
        raise ValueError("GitHub replay pull_request must be positive")
    labels = value.get("labels")
    if not isinstance(labels, dict):
        raise ValueError("GitHub replay case requires labels")
    case_id = _required_string(value.get("case_id"), "case_id")
    expected: dict[str, Any] = {
        "case_id": case_id,
        "repository": repository,
        "pull_request": pull_request,
        "review_symbol_ids": list(
            _string_tuple(labels.get("review_symbol_ids"), "review_symbol_ids", allow_empty=True)
        ),
        "ci_test_paths": list(
            _string_tuple(labels.get("ci_test_paths"), "ci_test_paths", allow_empty=True)
        ),
    }
    return GitHubReplayCase(
        case_id=case_id,
        repository=repository,
        pull_request=pull_request,
        base_sha=base_sha,
        head_sha=head_sha,
        language=_required_string(value.get("language"), "language").lower(),
        scenarios=_string_tuple(value.get("scenarios"), "scenarios"),
        context_path=_context_path(manifest_path, value.get("context_path")),
        expected=expected,
        provenance=_required_string(value.get("provenance"), "provenance"),
        provider_replay=bool(value.get("provider_replay", False)),
    )


def load_github_replay_manifest(path: str | Path) -> GitHubReplayManifest:
    manifest_path = Path(path).resolve()
    payload = _load_json(manifest_path)
    if not isinstance(payload, dict):
        raise ValueError("GitHub replay manifest must be an object")
    schema_version = int(payload.get("schema_version") or 0)
    if schema_version != 1:
        raise ValueError(f"Unsupported GitHub replay schema_version: {schema_version}")
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("GitHub replay manifest requires cases")
    cases = tuple(_parse_case(manifest_path, value) for value in raw_cases)
    case_ids = [case.case_id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("GitHub replay case_id values must be unique")
    return GitHubReplayManifest(
        corpus_id=_required_string(payload.get("corpus_id"), "corpus_id"),
        schema_version=schema_version,
        cases=cases,
    )


def _ratio(numerator: int, denominator: int, *, empty: float = 0.0) -> float:
    return round(numerator / denominator, 4) if denominator else empty


def _aggregate_metric(results: list[dict[str, Any]], key: str) -> dict[str, Any]:
    metrics = [dict(result[key]) for result in results]
    true_positive = sum(int(item["true_positive"]) for item in metrics)
    false_positive = sum(int(item["false_positive"]) for item in metrics)
    false_negative = sum(int(item["false_negative"]) for item in metrics)
    precision = _ratio(true_positive, true_positive + false_positive, empty=1.0)
    recall = _ratio(true_positive, true_positive + false_negative, empty=1.0)
    f1 = (
        round(2 * precision * recall / (precision + recall), 4)
        if precision + recall
        else 0.0
    )
    return {
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 3) if values else 0.0


def _validate_recording_source(case: GitHubReplayCase, context: dict[str, Any]) -> None:
    if not case.provider_replay:
        return
    source = context.get("source")
    if not isinstance(source, dict) or source.get("kind") != "github_provider":
        raise ValueError(f"Provider replay requires recorded GitHub source: {case.case_id}")
    expected = {
        "repository": case.repository,
        "pull_request": case.pull_request,
        "base_sha": case.base_sha,
        "head_sha": case.head_sha,
    }
    mismatches = [field for field, value in expected.items() if source.get(field) != value]
    if mismatches:
        raise ValueError(
            f"Provider replay source mismatch for {case.case_id}: {', '.join(mismatches)}"
        )
    metadata = context.get("replay_metadata")
    if not isinstance(metadata, dict) or not str(metadata.get("recorded_at") or ""):
        raise ValueError(f"Provider replay requires recorded_at: {case.case_id}")


def evaluate_github_replay_manifest(path: str | Path) -> dict[str, Any]:
    manifest = load_github_replay_manifest(path)
    case_results: list[dict[str, Any]] = []
    provider_statuses: dict[str, int] = {}
    requests: list[float] = []
    elapsed: list[float] = []
    cache_hits = 0

    for case in manifest.cases:
        context = _load_json(case.context_path)
        if not isinstance(context, dict):
            raise ValueError(f"GitHub replay context must be an object: {case.case_id}")
        _validate_recording_source(case, context)
        metrics = evaluate_pr_review_context(context, case.expected)
        replay_metadata = context.get("replay_metadata")
        metadata = dict(replay_metadata) if isinstance(replay_metadata, dict) else {}
        provider_status = str(context.get("provider_status") or "unknown")
        provider_statuses[provider_status] = provider_statuses.get(provider_status, 0) + 1
        requests.append(float(metadata.get("provider_requests") or 0))
        elapsed.append(float(metadata.get("elapsed_ms") or 0))
        cache_hit = bool(metadata.get("cache_hit", False))
        cache_hits += int(cache_hit)
        case_results.append(
            {
                "case_id": case.case_id,
                "repository": case.repository,
                "pull_request": case.pull_request,
                "base_sha": case.base_sha,
                "head_sha": case.head_sha,
                "language": case.language,
                "scenarios": list(case.scenarios),
                "provenance": case.provenance,
                "provider_replay": case.provider_replay,
                "provider_status": provider_status,
                "provider_requests": int(requests[-1]),
                "elapsed_ms": round(elapsed[-1], 3),
                "cache_hit": cache_hit,
                "metrics": metrics,
            }
        )

    metric_results = [dict(item["metrics"]) for item in case_results]
    symbol = _aggregate_metric(metric_results, "review_symbol_mapping")
    ci = _aggregate_metric(metric_results, "failed_ci_test_association")
    total = len(case_results)
    provider_replays = sum(int(item["provider_replay"]) for item in case_results)
    partial = provider_statuses.get("partial", 0)
    repositories = sorted({case.repository for case in manifest.cases})
    languages = sorted({case.language for case in manifest.cases})
    scenarios = sorted({scenario for case in manifest.cases for scenario in case.scenarios})
    return {
        "corpus_id": manifest.corpus_id,
        "schema_version": manifest.schema_version,
        "coverage": {
            "cases": total,
            "repositories": len(repositories),
            "repository_names": repositories,
            "languages": languages,
            "scenarios": scenarios,
            "provider_replay_cases": provider_replays,
            "curated_seed_cases": total - provider_replays,
        },
        "provider": {
            "status_counts": dict(sorted(provider_statuses.items())),
            "partial_rate": _ratio(partial, total),
            "mean_requests": _mean(requests),
            "mean_elapsed_ms": _mean(elapsed),
            "cache_hit_rate": _ratio(cache_hits, total),
        },
        "metrics": {
            "review_symbol_mapping": symbol,
            "failed_ci_test_association": ci,
            "macro": {
                "precision": round((symbol["precision"] + ci["precision"]) / 2, 4),
                "recall": round((symbol["recall"] + ci["recall"]) / 2, 4),
                "f1": round((symbol["f1"] + ci["f1"]) / 2, 4),
                "mean_case_f1": _mean(
                    [float(item["metrics"]["macro"]["f1"]) for item in case_results]
                ),
            },
        },
        "cases": case_results,
    }
