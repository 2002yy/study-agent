"""A1 negative controls: a passage is only confirmed when all four rules hold."""

from __future__ import annotations

import hashlib
from dataclasses import replace

from src.web.research.claim_span_provenance import (
    BODY_SCOPE,
    EVIDENCE_NOT_IN_RUN,
    EXCERPT_CORRUPT,
    HASH_MISMATCH,
    HASH_REQUIRED,
    READ_IDENTITY_MISMATCH,
    SPAN_NOT_IN_BODY,
    SPAN_OUT_OF_BOUNDS,
    SPAN_TEXT_REQUIRED,
    URL_MISMATCH,
    ClaimSpan,
    verify_claim_span,
)
from src.web.research.read_evidence import EXCERPT_CHARS, ReadEvidence

URL = "https://news.example/earnings"
READ_ID = "read_a1b2c3d4e5f60718"
BODY = (
    "公司周三发布季度报告。研发费用同比增加百分之三十，"
    "净利润同比下降百分之十二。管理层称投入仍将继续。"
)
QUOTE = "研发费用同比增加百分之三十，净利润同比下降百分之十二"
EVIDENCE_IDS = {"tool_read_1"}


def _span(needle: str, *, body: str = BODY) -> tuple[int, int]:
    start = body.index(needle)
    return start, start + len(needle)


def _evidence(body: str = BODY, *, url: str = URL, read_id: str = READ_ID):
    return ReadEvidence.build(url=url, excerpt=body, read_id=read_id)


def _candidate(body: str = BODY, **overrides):
    start, end = _span(QUOTE, body=body)
    values = {
        "claim_id": "claim_profit_drop",
        "claim_text": "利润下降的主要原因是研发投入增加",
        "evidence_id": "tool_read_1",
        "url": URL,
        "read_id": READ_ID,
        "span_start": start,
        "span_end": end,
        "span_text": QUOTE,
        "excerpt_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
    }
    values.update(overrides)
    return values


def test_an_exact_span_is_confirmed_and_points_at_its_offsets():
    record = _evidence()
    result = verify_claim_span(
        _candidate(), evidence=[record], evidence_ids=EVIDENCE_IDS
    )

    assert result.verified is True
    assert result.reason == ""
    assert result.body_scope == BODY_SCOPE
    assert result.body_chars == len(BODY)
    assert result.body_truncated is False
    assert result.excerpt_sha256 == record.content_sha256
    assert result.locator == f"span:{result.span.span_start}-{result.span.span_end}"
    assert BODY[result.span.span_start : result.span.span_end] == QUOTE


def test_provenance_is_independent_of_what_the_claim_says():
    # The passage says profit fell; the candidate claims it rose. Provenance is
    # still true - that is exactly why A1 must not be allowed to carry a verdict.
    result = verify_claim_span(
        _candidate(claim_text="净利润同比上升"),
        evidence=[_evidence()],
        evidence_ids=EVIDENCE_IDS,
    )

    assert result.verified is True
    assert not hasattr(result, "verdict")


def test_a_shifted_offset_is_refused_rather_than_searched():
    # Re-finding the text elsewhere in the page would hide the locator bug.
    start, end = _span(QUOTE)
    result = verify_claim_span(
        _candidate(span_start=start + 1, span_end=end + 1),
        evidence=[_evidence()],
        evidence_ids=EVIDENCE_IDS,
    )

    assert result.verified is False
    assert result.reason == SPAN_NOT_IN_BODY
    assert result.locator == ""


def test_text_that_is_not_in_the_body_is_refused():
    result = verify_claim_span(
        _candidate(span_text="净利润同比增长百分之十二"),
        evidence=[_evidence()],
        evidence_ids=EVIDENCE_IDS,
    )

    assert result.verified is False
    assert result.reason == SPAN_NOT_IN_BODY


def test_a_source_outside_the_run_references_is_refused():
    result = verify_claim_span(
        _candidate(evidence_id="tool_read_9"),
        evidence=[_evidence()],
        evidence_ids=EVIDENCE_IDS,
    )

    assert result.verified is False
    assert result.reason == EVIDENCE_NOT_IN_RUN


def test_a_read_identity_that_does_not_exist_is_refused():
    result = verify_claim_span(
        _candidate(read_id="read_0000000000000000"),
        evidence=[_evidence()],
        evidence_ids=EVIDENCE_IDS,
    )

    assert result.verified is False
    assert result.reason == READ_IDENTITY_MISMATCH


def test_a_read_identity_from_another_page_is_refused():
    other = _evidence("另一篇文章的正文。", url="https://news.example/other")
    result = verify_claim_span(
        _candidate(read_id=other.read_id),
        evidence=[_evidence(), other],
        evidence_ids=EVIDENCE_IDS,
    )

    assert result.verified is False
    assert result.reason == READ_IDENTITY_MISMATCH


def test_a_different_url_is_refused():
    result = verify_claim_span(
        _candidate(url="https://news.example/other"),
        evidence=[_evidence()],
        evidence_ids=EVIDENCE_IDS,
    )

    assert result.verified is False
    assert result.reason == URL_MISMATCH


def test_url_spelling_differences_do_not_break_a_real_read():
    result = verify_claim_span(
        _candidate(url="HTTPS://News.Example/earnings/"),
        evidence=[_evidence()],
        evidence_ids=EVIDENCE_IDS,
    )

    assert result.verified is True


def test_a_candidate_hash_that_does_not_match_the_read_is_refused():
    result = verify_claim_span(
        _candidate(excerpt_sha256=hashlib.sha256(b"other body").hexdigest()),
        evidence=[_evidence()],
        evidence_ids=EVIDENCE_IDS,
    )

    assert result.verified is False
    assert result.reason == HASH_MISMATCH


def test_a_candidate_without_a_hash_cannot_be_confirmed():
    result = verify_claim_span(
        _candidate(excerpt_sha256=""),
        evidence=[_evidence()],
        evidence_ids=EVIDENCE_IDS,
    )

    assert result.verified is False
    assert result.reason == HASH_REQUIRED


def test_a_read_record_that_no_longer_hashes_to_its_digest_is_refused():
    tampered = replace(_evidence(), excerpt=BODY + "（被篡改）")
    result = verify_claim_span(
        _candidate(), evidence=[tampered], evidence_ids=EVIDENCE_IDS
    )

    assert result.verified is False
    assert result.reason == EXCERPT_CORRUPT


def test_offsets_from_a_longer_body_are_out_of_bounds_not_relocated():
    # The saved body is the bounded excerpt. A 12k-body offset must not be
    # compared with a 3k digest, and the verifier must say why instead of
    # quietly searching the page again.
    tail = "净利润同比下降百分之十二。"
    long_body = ("前置内容。" * 700) + tail
    excerpt = long_body[:EXCERPT_CHARS]
    start = long_body.index(tail)
    assert start > len(excerpt)

    result = verify_claim_span(
        _candidate(
            span_start=start,
            span_end=start + len(tail),
            span_text=tail,
            excerpt_sha256=hashlib.sha256(long_body.encode("utf-8")).hexdigest(),
        ),
        evidence=[_evidence(excerpt)],
        evidence_ids=EVIDENCE_IDS,
    )

    assert result.verified is False
    assert result.reason == HASH_MISMATCH
    assert result.body_chars == EXCERPT_CHARS
    assert result.body_truncated is True

    with_excerpt_hash = verify_claim_span(
        _candidate(
            span_start=start,
            span_end=start + len(tail),
            span_text=tail,
            excerpt_sha256=hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
        ),
        evidence=[_evidence(excerpt)],
        evidence_ids=EVIDENCE_IDS,
    )

    assert with_excerpt_hash.verified is False
    assert with_excerpt_hash.reason == SPAN_OUT_OF_BOUNDS
    assert with_excerpt_hash.locator == ""


def test_two_records_with_the_same_read_identity_are_ambiguous():
    # An identity that resolves to more than one body cannot say which body was
    # verified, so it is refused instead of taking the first match.
    record = _evidence()
    result = verify_claim_span(
        _candidate(), evidence=[record, record], evidence_ids=EVIDENCE_IDS
    )

    assert result.verified is False
    assert result.reason == READ_IDENTITY_MISMATCH


def test_an_empty_span_text_is_refused():
    result = verify_claim_span(
        _candidate(span_text=""),
        evidence=[_evidence()],
        evidence_ids=EVIDENCE_IDS,
    )

    assert result.verified is False
    assert result.reason == SPAN_TEXT_REQUIRED


def test_a_mapping_and_a_claim_span_object_agree():
    record = _evidence()
    mapping = verify_claim_span(
        _candidate(), evidence=[record], evidence_ids=EVIDENCE_IDS
    )
    span = ClaimSpan.from_mapping(_candidate())
    typed = verify_claim_span(span, evidence=[record], evidence_ids=EVIDENCE_IDS)

    assert mapping.as_record() == typed.as_record()
