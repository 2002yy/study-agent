"""§144 RQ-B: RQ-A semantic adequacy validated on the §143-B threshold-safe cohort.

The cohort is a real artifact (``docs/research_quality/F2_PAIRED.threshold_safe.json``),
so this is characterization on recorded evidence, not a synthetic fixture.
"""

from __future__ import annotations

import json

import pytest

from tools.run_rq_b_semantic_validation import (
    DEFAULT_COHORT,
    SCHEMA_VERSION,
    assess_side,
    assess_without_requirement,
    validate_cohort,
)

pytestmark = pytest.mark.skipif(
    not DEFAULT_COHORT.exists(), reason="§143-B threshold-safe cohort artifact is absent"
)


def _cohort() -> dict:
    return json.loads(DEFAULT_COHORT.read_text(encoding="utf-8"))


def test_cohort_verdict_is_pass() -> None:
    artifact = validate_cohort(_cohort())

    assert artifact["schema_version"] == SCHEMA_VERSION
    assert artifact["verdict"] == "PASS"
    assert artifact["summary"]["rows"] == 60


def test_contrast_full_coverage_is_adequate_and_satisfied() -> None:
    artifact = validate_cohort(_cohort())
    contrast = artifact["contrasts"]["full_coverage"]

    assert contrast["ok"] is True
    assert contrast["count"] > 0
    for row in artifact["rows"]:
        if row["expected_unit_count"] and row["missing_unit_count"] == 0:
            assert row["semantic_adequacy"] == "adequate"
            assert row["claim_state"] == "satisfied"


def test_contrast_read_success_but_units_short_is_never_satisfied() -> None:
    # The §143-C mechanism conclusion, on real cohort data: "read/shape/content
    # succeeded" must not be treated as "semantic adequacy is sufficient".
    artifact = validate_cohort(_cohort())
    contrast = artifact["contrasts"]["read_success_units_short"]

    assert contrast["ok"] is True
    assert contrast["count"] >= 1, "the cohort must contain a real read-success/short-units case"

    short = [r for r in artifact["rows"] if r["read_useful"] and r["missing_unit_count"] > 0]
    assert short, "expected at least one recorded read-success-but-short case"
    for row in short:
        assert row["semantic_adequacy"] in {"partial", "insufficient"}
        assert row["claim_state"] != "satisfied"


def test_recorded_selected_pdf_default_is_partial_not_satisfied() -> None:
    # Named regression: the cohort records a default-chain read that was useful
    # but recovered 2/3 required units. RQ-A must call that partial.
    artifact = validate_cohort(_cohort())
    rows = [
        r
        for r in artifact["rows"]
        if r["category"] == "selected_pdf"
        and r["side"] == "default"
        and r["read_useful"]
    ]

    assert rows, "expected recorded selected_pdf/default rows"
    for row in rows:
        assert row["recovered_unit_count"] < row["expected_unit_count"]
        assert row["semantic_adequacy"] == "partial"
        assert row["claim_state"] == "partially_satisfied"


def test_contrast_no_required_units_is_not_evaluated() -> None:
    artifact = validate_cohort(_cohort())
    contrast = artifact["contrasts"]["no_required_units"]

    assert contrast["ok"] is True
    assert contrast["count"] == 60
    for item in _cohort()["raw"]:
        for side in ("default", "crawl4ai"):
            row = assess_without_requirement(item, side=side)
            assert row["semantic_adequacy"] == "not_evaluated"


def test_no_false_satisfied_over_the_whole_cohort() -> None:
    artifact = validate_cohort(_cohort())

    assert artifact["contrasts"]["no_false_satisfied"]["ok"] is True
    for row in artifact["rows"]:
        if row["claim_state"] == "satisfied":
            assert row["missing_unit_count"] == 0


def test_assess_side_reports_the_declared_read_outcome_and_the_judgement() -> None:
    item = {
        "category": "synthetic",
        "fixture": "x.html",
        "expected_critical_units": ["a", "b"],
        "default": {"useful": True, "unit_set": ["a"]},
        "crawl4ai": {"useful": True, "unit_set": ["a", "b"]},
    }

    partial = assess_side(item, side="default")
    complete = assess_side(item, side="crawl4ai")

    assert partial["read_useful"] is True
    assert partial["semantic_adequacy"] == "partial"
    assert partial["claim_state"] == "partially_satisfied"
    assert complete["semantic_adequacy"] == "adequate"
    assert complete["claim_state"] == "satisfied"


def test_reader_never_derives_the_requirement() -> None:
    # The requirement is claim-side only: the same recovered units judged with an
    # empty requirement must be `not_evaluated`, not `adequate`.
    item = {
        "category": "synthetic",
        "fixture": "x.html",
        "expected_critical_units": ["a"],
        "default": {"useful": True, "unit_set": ["a"]},
    }

    assert assess_side(item, side="default")["semantic_adequacy"] == "adequate"
    assert assess_without_requirement(item, side="default")["semantic_adequacy"] == (
        "not_evaluated"
    )
