"""Deterministic tests for the answer reasoning policy A/B probe."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.run_answer_reasoning_policy_probe import (
    SCHEMA_VERSION,
    THINKING_DISABLED_BODY,
    _load_cases,
    _percentile,
    _quality_proxy,
    run_probe,
)

MANIFEST = Path("tests/fixtures/research_quality/rq1c_bounded_holdout_manifest.json")


def test_policy_probe_is_diagnostic_only() -> None:
    import tools.run_answer_reasoning_policy_probe as probe

    assert SCHEMA_VERSION == "rq1c-answer-reasoning-policy-v1"
    assert THINKING_DISABLED_BODY == {"thinking": {"type": "disabled"}}
    args = probe._parser().parse_args(["--output", "out.json"])
    assert args.repeats == 3
    assert args.answer_timeout_seconds == 90.0
    assert args.deadline_seconds == 240.0
    source = Path("tools/run_answer_reasoning_policy_probe.py").read_text(
        encoding="utf-8"
    )
    # The widened limits must stay diagnostic: the artifact declares it and the
    # production defaults are not touched anywhere in this tool.
    assert '"qualification_evidence": False' in source


def test_policy_probe_selection_bound_to_manifest() -> None:
    selected = _load_cases(MANIFEST, ["rq1c-provenance-xz"])

    assert [case["id"] for case in selected] == ["rq1c-provenance-xz"]
    with pytest.raises(ValueError):
        _load_cases(MANIFEST, ["rq1c-not-a-case"])


def test_quality_proxy_flags_unsupported_numbers_and_conditional_wording() -> None:
    evidence = "Bank Rate was set at 4.00% on 2026-08-07 according to the MPC."

    supported = _quality_proxy("The MPC set Bank Rate at 4.00% on 2026-08-07.", evidence)
    assert supported["unsupported_number_count"] == 0
    assert supported["conditional_wording"] is False
    assert supported["sentences"] == 1

    unsupported = _quality_proxy("Bank Rate is 5.25% and was cut twice.", evidence)
    assert unsupported["unsupported_numbers"] == ["5.25"]
    assert unsupported["unsupported_number_count"] == 1

    fail_closed = _quality_proxy("证据不足，无法确认当前 Bank Rate。", evidence)
    assert fail_closed["conditional_wording"] is True
    assert fail_closed["fail_closed_ok"] is True


def test_quality_proxy_treats_unsupported_specifics_as_not_fail_closed() -> None:
    evidence = "Evidence says nothing about rates."

    result = _quality_proxy("无法确认，但历史值为 4.00%。", evidence)

    assert result["conditional_wording"] is True
    assert result["unsupported_number_count"] == 1
    assert result["fail_closed_ok"] is False


def test_percentile_is_nearest_rank() -> None:
    assert _percentile([], 0.5) is None
    assert _percentile([5.0, 10.0, 15.0, 20.0], 0.5) == 15.0
    assert _percentile([5.0, 10.0, 15.0, 20.0], 0.9) == 20.0


def test_policy_probe_rejects_invalid_repeats(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        run_probe(
            manifest_path=MANIFEST,
            output_path=tmp_path / "out.json",
            case_ids=["rq1c-provenance-xz"],
            repeats=0,
            answer_timeout_seconds=90.0,
            deadline_seconds=240.0,
        )
