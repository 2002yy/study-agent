"""Deterministic tests for the answer timeline / reasoning probe tool."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.run_answer_timeline_probe import (
    SCHEMA_VERSION,
    THINKING_DISABLED_BODY,
    _call_record,
    _load_cases,
    run_probe,
)

MANIFEST = Path("tests/fixtures/research_quality/rq1c_bounded_holdout_manifest.json")


def test_probe_is_diagnostic_only_and_defaults_are_measurement_safe() -> None:
    import tools.run_answer_timeline_probe as probe

    assert SCHEMA_VERSION == "rq1c-answer-timeline-probe-v1"
    assert THINKING_DISABLED_BODY == {"thinking": {"type": "disabled"}}
    args = probe._parser().parse_args(["--output", "out.json"])
    assert args.mode == "position"
    assert args.repeats == 3
    assert args.answer_timeout_seconds == 90.0
    assert args.deadline_seconds == 240.0


def test_probe_selection_is_bound_to_the_holdout_manifest() -> None:
    selected = _load_cases(
        MANIFEST, ["rq1c-academic-primary-attention", "rq1c-provenance-xz"]
    )

    assert [case["id"] for case in selected] == [
        "rq1c-academic-primary-attention",
        "rq1c-provenance-xz",
    ]
    with pytest.raises(ValueError):
        _load_cases(MANIFEST, ["rq1c-not-a-case"])


def test_call_record_projects_budget_telemetry() -> None:
    class FakeBudget:
        def __init__(self) -> None:
            self.call_records = [
                {
                    "phase": "answer_generation",
                    "outcome": "RuntimeError",
                    "timeout_seconds": 30.0,
                    "remaining_at_dispatch_seconds": 36.0,
                    "remaining_after_call_seconds": 5.9,
                    "request_max_retries": 0,
                    "message_count": 2,
                    "message_chars": 4712,
                }
            ]

    record = _call_record(
        budget=FakeBudget(),
        before=0,
        elapsed_seconds=30.11,
        answer_status="unavailable",
        answer_reason="production_chat_failed:RuntimeError",
        answer_text_chars=0,
    )

    assert record["outcome"] == "RuntimeError"
    assert record["timeout_seconds"] == 30.0
    assert record["remaining_at_dispatch_seconds"] == 36.0
    assert record["request_max_retries"] == 0
    assert record["prompt_message_chars"] == 4712
    assert record["answer_status"] == "unavailable"


def test_probe_rejects_invalid_repeats_before_touching_git(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        run_probe(
            manifest_path=MANIFEST,
            output_path=tmp_path / "out.json",
            case_ids=["rq1c-provenance-xz"],
            mode="position",
            repeats=0,
            delay_seconds=0.0,
            answer_timeout_seconds=90.0,
            deadline_seconds=240.0,
        )
