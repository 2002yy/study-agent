"""Deterministic tests for the answer-stage replay calibration tool."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.run_answer_stage_replay import (
    DEFAULT_CASES,
    SCHEMA_VERSION,
    _load_cases,
    _percentile,
    run_replay,
)

MANIFEST = Path("tests/fixtures/research_quality/rq1c_bounded_holdout_manifest.json")


def test_replay_is_explicitly_not_qualification_evidence() -> None:
    assert SCHEMA_VERSION == "rq1c-answer-stage-replay-v1"
    import tools.run_answer_stage_replay as replay

    parser = replay._parser()
    args = parser.parse_args(["--output", "out.json"])
    # Defaults must be diagnostic-only: a widened answer timeout is never a
    # qualification/product configuration.
    assert args.answer_timeout_seconds == 90.0
    assert args.deadline_seconds == 240.0
    assert args.repeats == 3
    assert set(DEFAULT_CASES) <= {
        "rq1c-numeric-uk-inflation",
        "rq1c-unverifiable-python-security",
        "rq1c-academic-primary-attention",
        "rq1c-provenance-xz",
    }


def test_replay_selection_is_bound_to_the_holdout_manifest() -> None:
    selected = _load_cases(MANIFEST, ["rq1c-provenance-xz"])

    assert [case["id"] for case in selected] == ["rq1c-provenance-xz"]
    assert selected[0]["question"]
    with pytest.raises(ValueError):
        _load_cases(MANIFEST, ["rq1c-not-a-case"])


def test_replay_percentile_is_nearest_rank() -> None:
    assert _percentile([], 0.5) is None
    assert _percentile([10.0], 0.9) == 10.0
    # Ties round up: p90 of three samples is the maximum.
    assert _percentile([10.0, 20.0, 30.0], 0.5) == 20.0
    assert _percentile([10.0, 20.0, 30.0], 0.9) == 30.0
    assert _percentile([10.0, 20.0, 30.0, 40.0], 0.5) == 30.0


def test_replay_rejects_invalid_measurement_parameters(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        run_replay(
            manifest_path=MANIFEST,
            output_path=tmp_path / "out.json",
            case_ids=["rq1c-provenance-xz"],
            repeats=0,
            answer_timeout_seconds=90.0,
            deadline_seconds=240.0,
        )
    with pytest.raises(ValueError):
        run_replay(
            manifest_path=MANIFEST,
            output_path=tmp_path / "out.json",
            case_ids=["rq1c-provenance-xz"],
            repeats=1,
            answer_timeout_seconds=0.0,
            deadline_seconds=240.0,
        )
