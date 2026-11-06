"""A4 shadow controls: the two gate metrics, and what makes a report unsafe."""

from __future__ import annotations

import json
from pathlib import Path

from src.web.research.support_shadow import (
    Annotation,
    ShadowCase,
    as_rows,
    run_shadow,
)
from tools.a4_shadow_report import load_cases

CASES = Path("tests/fixtures/research_quality/a4_shadow_cases.json")


def test_the_annotated_fixture_separates_increment_from_false_release():
    cases, annotations = load_cases(CASES)

    report = run_shadow(cases, annotations)

    assert report.literal_refused == 5
    assert report.shadow_qualified == 5
    assert report.correct_increment == 1
    assert report.false_release == 3
    assert report.unannotated == 0
    assert report.measured is True
    assert report.safe is False
    assert report.false_release_rate == 0.6


def test_the_causal_overreach_is_counted_as_a_false_release():
    cases, annotations = load_cases(CASES)

    report = run_shadow(cases, annotations)
    causal = next(
        row for row in as_rows(report) if row["claim_id"] == "claim_profit_cause"
    )

    assert causal["shadow_publishable"] is True
    assert causal["annotation_correct"] is False
    assert causal["false_release"] is True
    assert causal["increment"] is False


def test_a_claim_the_literal_rule_already_bound_is_not_an_increment():
    cases, annotations = load_cases(CASES)

    report = run_shadow(cases, annotations)
    literal = next(
        row for row in as_rows(report) if row["claim_id"] == "claim_literal"
    )

    assert literal["literal_bound"] is True
    assert literal["increment"] is False


def test_an_insufficient_verdict_is_not_a_release():
    cases, annotations = load_cases(CASES)

    report = run_shadow(cases, annotations)
    margin = next(
        row for row in as_rows(report) if row["claim_id"] == "claim_margin"
    )

    assert margin["shadow_publishable"] is False
    assert margin["false_release"] is False


def test_an_unannotated_release_makes_the_report_unmeasured():
    cases, _annotations = load_cases(CASES)
    partial = tuple(
        annotation
        for annotation in _annotations
        if annotation["claim_id"] != "claim_profit_cause"
    )

    report = run_shadow(cases, partial)

    assert report.unannotated == 1
    assert report.measured is False
    assert report.safe is False
    assert report.false_release_rate is None
    assert any("no independent annotation" in note for note in report.notes)


def test_a_contradiction_never_becomes_a_release():
    # Build the smallest possible case: a verified candidate is required, so the
    # fixture supplies one and the verdict is flipped to contradicts.
    from src.web.research.claim_span_provenance import verify_claim_span
    from src.web.research.read_evidence import ReadEvidence
    from src.web.research.support_qualification import ClaimJudgement

    passage = "公司声明：有关收入增长的说法不属实。"
    span = "有关收入增长的说法不属实"
    record = ReadEvidence.build(url="https://x.example/a", excerpt=passage, read_id="read_x")
    candidate = verify_claim_span(
        {
            "claim_id": "claim_denied2",
            "claim_text": "收入增长",
            "evidence_id": "read-9",
            "url": "https://x.example/a",
            "read_id": "read_x",
            "span_start": passage.index(span),
            "span_end": passage.index(span) + len(span),
            "span_text": span,
            "excerpt_sha256": record.content_sha256,
        },
        evidence=[record],
        evidence_ids={"read-9"},
        evidence_urls={"read-9": "https://x.example/a"},
    )
    case = ShadowCase(
        claim_id="claim_denied2",
        claim_text="收入增长",
        candidates=(candidate,),
        judgements=(
            ClaimJudgement(
                claim_id="claim_denied2",
                passage_key=(
                    f"claim_denied2|read-9|read_x|"
                    f"{passage.index(span)}-{passage.index(span) + len(span)}"
                ),
                verdict="contradicts",
                evidence_span=span,
            ),
        ),
    )

    report = run_shadow([case], [Annotation("claim_denied2", True)])

    assert report.shadow_qualified == 0
    assert report.false_release == 0
    assert report.correct_increment == 0


def test_the_report_never_claims_to_publish():
    cases, annotations = load_cases(CASES)

    report = run_shadow(cases, annotations)

    assert not hasattr(report, "published")
    payload = json.dumps([row for row in as_rows(report)], ensure_ascii=False)
    assert "published" not in payload
