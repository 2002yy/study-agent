from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from src.web.github_pr_review_replay import (
    evaluate_github_replay_manifest,
    load_github_replay_manifest,
)


_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "github_replay"
_MANIFEST = _FIXTURE_DIR / "manifest.json"


def test_manifest_loads_immutable_seed_and_real_provider_cases():
    manifest = load_github_replay_manifest(_MANIFEST)

    assert manifest.corpus_id == "study-agent-g10-c3a-replay-v2"
    assert len(manifest.cases) == 15
    assert all(
        len(case.base_sha) == 40 and len(case.head_sha) == 40 for case in manifest.cases
    )
    assert sum(case.provenance == "curated_unit_seed" for case in manifest.cases) == 2
    assert sum(case.provider_replay for case in manifest.cases) == 13


def test_manifest_summary_reports_quality_coverage_and_provider_limits():
    summary = evaluate_github_replay_manifest(_MANIFEST)

    assert summary["coverage"] == {
        "cases": 15,
        "repositories": 13,
        "repository_names": [
            "2002yy/study-agent",
            "Corfucinas/devtask-manager",
            "durandtibo/glyphik",
            "encode/httpx",
            "encode/starlette",
            "fastapi/fastapi",
            "google/gson",
            "junit-team/junit5",
            "pallets/click",
            "pallets/flask",
            "pydantic/pydantic",
            "pytest-dev/pytest",
            "vitejs/vite",
        ],
        "languages": ["java", "markdown", "python", "rust", "typescript"],
        "scenarios": [
            "ambiguous-mapping",
            "build-failure",
            "change-impact-test",
            "ci-test-over-association",
            "cross-fork",
            "deleted-file",
            "docs-only",
            "empty-review-label",
            "failed-ci-negative-control",
            "failed-ci-positive-control",
            "failed-ci-test",
            "historical-non-code-reviews",
            "historical-review-line-missing",
            "lint-failure",
            "mapping-false-positive",
            "no-failed-ci",
            "no-label-candidates",
            "old-new-path-candidates",
            "outdated-review-line",
            "persistent-cache-hit",
            "provider-replay",
            "provider-truncated",
            "real-file-rename",
            "removed-review-target",
            "removed-symbol-candidates",
            "request-budget-exhausted",
            "resolved-non-code-review",
            "review-symbol",
            "test-matrix-failure",
            "unresolved-non-code-review",
            "unresolved-review-thread",
            "unsupported-language-symbol",
            "warm-replay",
        ],
        "provider_replay_cases": 13,
        "curated_seed_cases": 2,
    }
    assert summary["provider"] == {
        "status_counts": {"complete": 2, "curated": 2, "partial": 11},
        "partial_rate": 0.7333,
        "mean_requests": 9.6,
        "mean_elapsed_ms": 152362.216,
        "cache_hit_rate": 0.0667,
    }
    assert summary["metrics"]["macro"] == {
        "precision": 0.3765,
        "recall": 0.625,
        "f1": 0.4147,
        "mean_case_f1": 0.845,
    }


def test_failed_ci_replays_keep_named_job_evidence_without_hallucinated_tests():
    names = ["pydantic-pr13275", "junit5-pr5295", "pytest-pr13987"]
    contexts = [
        json.loads(
            (_FIXTURE_DIR / "contexts" / f"{name}.json").read_text(encoding="utf-8")
        )
        for name in names
    ]

    associations = [
        association
        for context in contexts
        for association in context["ci_associations"]
    ]
    assert len(associations) == 35
    assert all(association["job"]["name"] for association in associations)
    assert all(
        association["association"]["status"] == "unmapped"
        for association in associations
    )
    assert all(
        association["association"]["tests"] == [] for association in associations
    )


def test_edge_replays_keep_deleted_cache_and_truncation_evidence():
    httpx = json.loads(
        (_FIXTURE_DIR / "contexts" / "httpx-pr3319.json").read_text(encoding="utf-8")
    )
    cached = json.loads(
        (_FIXTURE_DIR / "contexts" / "study-agent-pr48-cache-hit.json").read_text(
            encoding="utf-8"
        )
    )
    truncated = json.loads(
        (_FIXTURE_DIR / "contexts" / "fastapi-pr15493-truncated.json").read_text(
            encoding="utf-8"
        )
    )

    assert any(
        candidate["side"] == "old" and candidate["path"] == "httpx/_compat.py"
        for candidate in httpx["label_candidates"]
    )
    assert cached["replay_metadata"]["cache_hit"] is True
    assert truncated["truncated"] is True
    assert truncated["provider_request_budget"]["exhausted"] is True
    assert truncated["provider_request_budget"]["used_requests"] == 6


def test_real_failed_ci_positive_exposes_over_association_baseline():
    summary = evaluate_github_replay_manifest(_MANIFEST)
    case = next(
        item
        for item in summary["cases"]
        if item["case_id"] == "devtask-manager-pr35-real-failed-tests"
    )
    metric = case["metrics"]["failed_ci_test_association"]

    assert metric["expected"] == [
        "tests/test_backup.py",
        "tests/test_formatter.py",
        "tests/test_importer.py",
    ]
    assert len(metric["predicted"]) == 14
    assert "tests/test_dedupe.py" in metric["predicted"]
    assert metric["precision"] == 0.2143
    assert metric["recall"] == 1.0
    assert metric["false_positive"] == 11


def test_real_rename_keeps_both_paths_without_historical_ci_noise():
    context = json.loads(
        (_FIXTURE_DIR / "contexts" / "glyphik-pr215-rename.json").read_text(
            encoding="utf-8"
        )
    )
    candidates = {
        (candidate["path"], candidate["side"], candidate["change_type"])
        for candidate in context["label_candidates"]
    }

    assert (
        "src/glyphik/pipelines/factory/sec_document_summarization.py",
        "old",
        "removed",
    ) in candidates
    assert (
        "src/glyphik/pipelines/factory/company_document.py",
        "new",
        "added",
    ) in candidates
    assert (
        "tests/unit/pipelines/factory/test_sec_document_summarization.py",
        "old",
        "moved",
    ) in candidates
    assert (
        "tests/unit/pipelines/factory/test_company_document.py",
        "new",
        "moved",
    ) in candidates
    assert context["ci_associations"] == []
    assert context["truncated"] is True
    assert context["provider_request_budget"]["used_requests"] == 6


def test_cross_fork_impact_and_docs_only_replays_keep_distinct_evidence():
    click = json.loads(
        (_FIXTURE_DIR / "contexts" / "click-pr3681.json").read_text(
            encoding="utf-8"
        )
    )
    starlette = json.loads(
        (_FIXTURE_DIR / "contexts" / "starlette-pr3359.json").read_text(
            encoding="utf-8"
        )
    )

    assert any(
        candidate["path"] == "src/click/_compat.py"
        for candidate in click["label_candidates"]
    )
    assert {
        candidate["path"]
        for candidate in click["label_candidates"]
        if candidate["path"].startswith("tests/")
    } >= {
        "tests/test_compat.py",
        "tests/test_utils/test_style.py",
    }
    assert click["provider_status"] == "complete"
    assert click["ci_associations"] == []
    assert starlette["label_candidates"] == []
    assert starlette["ci_associations"] == []
    assert starlette["provider_status"] == "partial"
    assert starlette["truncated"] is True


def test_manifest_rejects_mutable_ref_and_context_path_escape(tmp_path: Path):
    context = tmp_path / "context.json"
    context.write_text("{}", encoding="utf-8")
    payload = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    payload["cases"] = [dict(payload["cases"][0])]
    payload["cases"][0]["base_sha"] = "main"
    payload["cases"][0]["context_path"] = "context.json"
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="immutable 40-char SHAs"):
        load_github_replay_manifest(manifest)

    payload["cases"][0]["base_sha"] = "a" * 40
    payload["cases"][0]["context_path"] = "../outside.json"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="must stay under"):
        load_github_replay_manifest(manifest)


def test_replay_cli_writes_deterministic_json(tmp_path: Path):
    output = tmp_path / "summary.json"
    completed = subprocess.run(
        [
            sys.executable,
            "tools/evaluate_github_replay.py",
            str(_MANIFEST),
            "--output",
            str(output),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    first = output.read_text(encoding="utf-8")
    assert json.loads(first)["coverage"]["provider_replay_cases"] == 13
    subprocess.run(
        [
            sys.executable,
            "tools/evaluate_github_replay.py",
            str(_MANIFEST),
            "--output",
            str(output),
        ],
        check=True,
    )
    assert output.read_text(encoding="utf-8") == first


def test_provider_replay_rejects_manifest_source_mismatch(tmp_path: Path):
    context = tmp_path / "context.json"
    context.write_text(
        json.dumps(
            {
                "source": {
                    "kind": "github_provider",
                    "repository": "wrong/repo",
                    "pull_request": 1,
                    "base_sha": "a" * 40,
                    "head_sha": "b" * 40,
                },
                "replay_metadata": {"recorded_at": "2026-07-17T00:00:00+00:00"},
                "review_items": [],
                "ci_associations": [],
            }
        ),
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "corpus_id": "test",
                "schema_version": 1,
                "cases": [
                    {
                        "case_id": "case-1",
                        "repository": "right/repo",
                        "pull_request": 1,
                        "base_sha": "a" * 40,
                        "head_sha": "b" * 40,
                        "language": "python",
                        "scenarios": ["provider-replay"],
                        "context_path": "context.json",
                        "provenance": "github_provider_recording",
                        "provider_replay": True,
                        "labels": {"review_symbol_ids": [], "ci_test_paths": []},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="source mismatch"):
        evaluate_github_replay_manifest(manifest)
