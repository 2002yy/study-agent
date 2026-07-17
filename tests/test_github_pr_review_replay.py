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
    assert len(manifest.cases) == 5
    assert all(len(case.base_sha) == 40 and len(case.head_sha) == 40 for case in manifest.cases)
    assert sum(case.provenance == "curated_unit_seed" for case in manifest.cases) == 2
    assert sum(case.provider_replay for case in manifest.cases) == 3


def test_manifest_summary_reports_quality_coverage_and_provider_limits():
    summary = evaluate_github_replay_manifest(_MANIFEST)

    assert summary["coverage"] == {
        "cases": 5,
        "repositories": 4,
        "repository_names": [
            "2002yy/study-agent",
            "google/gson",
            "pallets/flask",
            "vitejs/vite",
        ],
        "languages": ["java", "python", "typescript"],
        "scenarios": [
            "ambiguous-mapping",
            "change-impact-test",
            "cross-fork",
            "empty-review-label",
            "failed-ci-test",
            "historical-review-line-missing",
            "mapping-false-positive",
            "provider-replay",
            "removed-review-target",
            "review-symbol",
            "unresolved-review-thread",
        ],
        "provider_replay_cases": 3,
        "curated_seed_cases": 2,
    }
    assert summary["provider"] == {
        "status_counts": {"curated": 2, "partial": 3},
        "partial_rate": 0.6,
        "mean_requests": 6.0,
        "mean_elapsed_ms": 115402.889,
        "cache_hit_rate": 0.0,
    }
    assert summary["metrics"]["macro"] == {
        "precision": 0.625,
        "recall": 0.5834,
        "f1": 0.6,
        "mean_case_f1": 0.7,
    }


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
    assert json.loads(first)["coverage"]["provider_replay_cases"] == 3
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
