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


def test_manifest_loads_immutable_seed_cases_without_claiming_provider_replay():
    manifest = load_github_replay_manifest(_MANIFEST)

    assert manifest.corpus_id == "study-agent-g10-c3a-seed-v1"
    assert len(manifest.cases) == 2
    assert all(len(case.base_sha) == 40 and len(case.head_sha) == 40 for case in manifest.cases)
    assert all(case.provenance == "curated_unit_seed" for case in manifest.cases)
    assert not any(case.provider_replay for case in manifest.cases)


def test_manifest_summary_reports_quality_coverage_and_provider_limits():
    summary = evaluate_github_replay_manifest(_MANIFEST)

    assert summary["coverage"] == {
        "cases": 2,
        "repositories": 1,
        "repository_names": ["2002yy/study-agent"],
        "languages": ["python"],
        "scenarios": [
            "change-impact-test",
            "empty-review-label",
            "failed-ci-test",
            "review-symbol",
        ],
        "provider_replay_cases": 0,
        "curated_seed_cases": 2,
    }
    assert summary["provider"] == {
        "status_counts": {"curated": 2},
        "partial_rate": 0.0,
        "mean_requests": 0.0,
        "mean_elapsed_ms": 0.0,
        "cache_hit_rate": 0.0,
    }
    assert summary["metrics"]["macro"] == {
        "precision": 1.0,
        "recall": 1.0,
        "f1": 1.0,
        "mean_case_f1": 1.0,
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
    assert json.loads(first)["coverage"]["provider_replay_cases"] == 0
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
