"""A2 negative controls: bounded, deterministic locating with no authority.

The metric this slice is judged by is recall of useful passages, not whether the
passage supports the claim. A miss is therefore a recorded outcome, not a test
failure - except where the locator would otherwise invent a span.
"""

from __future__ import annotations

import hashlib

from src.web.research.claim_span_location import (
    MAX_TOTAL_CANDIDATES,
    REASON_NO_EVIDENCE,
    REASON_NO_OVERLAP,
    REASON_TOTAL_CAP,
    REASON_WEAK_OVERLAP,
    ClaimToLocate,
    EvidenceSource,
    locate_claim_spans,
)
from src.web.research.read_evidence import EXCERPT_CHARS, ReadEvidence

URL = "https://news.example/earnings"
BODY = (
    "公司周三发布季度报告。"
    "研发费用同比增加百分之三十，净利润同比下降百分之十二。"
    "管理层表示投入仍将继续。"
    "同日公布的现金流数据显示经营现金净流入为负。"
)


def _record(body: str = BODY, *, url: str = URL, read_id: str = "read_aaa111bbb222"):
    return ReadEvidence.build(url=url, excerpt=body, read_id=read_id)


def _source(
    evidence_id: str = "tool_read_1", *, body: str = BODY, url: str = URL, read_id: str = "read_aaa111bbb222"
) -> EvidenceSource:
    return EvidenceSource(
        evidence_id=evidence_id,
        evidence=_record(body, url=url, read_id=read_id),
    )


def _claim(text: str, claim_id: str = "claim_1") -> ClaimToLocate:
    return ClaimToLocate(claim_id=claim_id, text=text)


def _locate(claim: ClaimToLocate, sources, **kwargs):
    return locate_claim_spans([claim], sources=sources, **kwargs)[0]


def test_an_exact_sentence_is_located_at_its_true_offsets():
    claim_text = "研发费用同比增加百分之三十，净利润同比下降百分之十二"
    location = _locate(_claim(claim_text), [_source()])

    assert location.located is True
    assert len(location.candidates) == 1
    candidate = location.candidates[0]
    assert candidate.verified is True
    assert candidate.span.span_text == claim_text
    assert BODY[candidate.span.span_start : candidate.span.span_end] == claim_text
    assert candidate.locator == (
        f"span:{candidate.span.span_start}-{candidate.span.span_end}"
    )


def test_shared_topic_terms_produce_candidates_without_deciding_support():
    # "研发投入上升使利润下滑" is not what the page says - the page states an
    # increase in R&D expense and a fall in net profit, with no causal claim.
    # A2 may still offer the passage; deciding it does not support the causal
    # wording is A3's job, and nothing here carries a verdict.
    location = _locate(_claim("研发投入上升使利润下滑"), [_source()])

    assert location.located is True
    for candidate in location.candidates:
        assert candidate.verified is True
        assert not hasattr(candidate, "verdict")


def test_a_paraphrase_with_no_shared_characters_is_recorded_as_a_miss():
    # Cross-wording, cross-language and synonym-heavy paraphrases are where a
    # deterministic locator loses recall. V1 must report that loss, not disguise
    # it as a keyword rule that pretends to be semantics.
    body = "公司增加了实验与开发预算，全年盈利减少。"
    location = _locate(_claim("研发投入上升使利润下滑"), [_source(body=body)])

    assert location.located is False
    assert location.candidates == ()
    assert location.reason == REASON_NO_OVERLAP


def test_a_rewrite_that_keeps_the_facts_is_located():
    # Same facts, different word order: this is the recall v1 must actually win.
    location = _locate(_claim("净利润同比下降百分之十二，研发费用同比增加百分之三十"), [_source()])

    # The claim's own sentence is not verbatim in the body, so the locator has
    # to fall back on overlapping anchors rather than exact matching.
    assert location.located is True
    candidate = location.candidates[0]
    assert "净利润" in candidate.span.span_text
    assert candidate.verified is True


def test_two_facts_on_one_page_get_different_passages():
    locations = locate_claim_spans(
        [
            _claim("研发费用同比增加百分之三十", claim_id="claim_rd"),
            _claim("现金流数据显示经营现金净流入为负", claim_id="claim_cash"),
        ],
        sources=[_source()],
    )

    first, second = locations
    assert first.located and second.located
    assert first.candidates[0].locator != second.candidates[0].locator
    assert "研发" in first.candidates[0].span.span_text
    assert "现金流" in second.candidates[0].span.span_text


def test_a_repeated_sentence_yields_one_candidate():
    # Not verbatim, so the locator must score windows and then de-duplicate the
    # identical passage it finds twice.
    body = "净利润同比下降百分之十二。其他说明见附录。净利润同比下降百分之十二。"
    location = _locate(_claim("净利润下降百分之十二"), [_source(body=body)])

    assert location.located is True
    texts = [candidate.span.span_text for candidate in location.candidates]
    assert len(texts) == len(set(texts)) == 1


def test_text_beyond_the_saved_excerpt_is_not_located():
    tail = "净利润同比下降百分之十二。"
    long_body = ("前置内容。" * 700) + tail
    assert long_body.index(tail) > EXCERPT_CHARS
    excerpt = long_body[:EXCERPT_CHARS]

    location = _locate(_claim(tail), [_source(body=excerpt)])

    assert location.located is False
    assert location.candidates == ()


def test_a_candidate_never_carries_another_pages_evidence_id():
    page_a = _source("tool_read_1", body="公司周三发布季度报告。", read_id="read_page_a")
    same_text = "净利润同比下降百分之十二。"
    page_b = _source(
        "tool_read_2",
        body=f"无关段落。{same_text}",
        url="https://news.example/other",
        read_id="read_page_b",
    )

    location = _locate(_claim(same_text), [page_a, page_b])

    assert location.located is True
    for candidate in location.candidates:
        assert candidate.span.evidence_id == "tool_read_2"
        assert candidate.span.read_id == "read_page_b"
        assert candidate.span.url == "https://news.example/other"


def test_no_evidence_returns_an_empty_result_and_a_reason():
    location = _locate(_claim("净利润同比下降百分之十二"), [])

    assert location.located is False
    assert location.reason == REASON_NO_EVIDENCE


def test_unrelated_text_yields_no_candidates():
    location = _locate(_claim("董事会批准了新的回购计划"), [_source()])

    assert location.located is False
    assert location.reason in {REASON_NO_OVERLAP, REASON_WEAK_OVERLAP}


def test_candidates_are_capped_per_claim():
    body = "".join(f"净利润同比下降百分之{index}。" for index in range(1, 8))
    location = _locate(_claim("净利润同比下降百分之三"), [_source(body=body)])

    assert len(location.candidates) <= 3
    assert all(candidate.verified for candidate in location.candidates)


def test_the_batch_has_a_hard_total_cap():
    claims = [_claim("净利润同比下降百分之十二", claim_id=f"claim_{i}") for i in range(10)]

    locations = locate_claim_spans(claims, sources=[_source()], max_total=2)

    total = sum(len(location.candidates) for location in locations)
    assert total <= 2
    assert any(location.reason == REASON_TOTAL_CAP for location in locations)
    assert MAX_TOTAL_CANDIDATES >= 2


def test_every_candidate_is_provenance_verified_and_carries_no_verdict():
    location = _locate(_claim("净利润同比下降百分之十二"), [_source()])

    assert location.candidates
    for candidate in location.candidates:
        assert candidate.verified is True
        assert candidate.locator
        assert candidate.reason == ""
        assert not hasattr(candidate, "verdict")
        assert not hasattr(candidate, "strength")


def test_a_candidate_hash_matches_the_recorded_excerpt():
    source = _source()
    location = _locate(_claim("净利润同比下降百分之十二"), [source])

    expected = hashlib.sha256(source.evidence.excerpt.encode("utf-8")).hexdigest()
    assert location.candidates[0].excerpt_sha256 == expected


def test_locators_point_at_the_exact_characters_of_the_saved_body():
    body = BODY
    source = _source(body=body)
    locations = locate_claim_spans(
        [
            _claim("研发费用同比增加百分之三十", claim_id="a"),
            _claim("管理层表示投入仍将继续", claim_id="b"),
        ],
        sources=[source],
    )

    for location in locations:
        for candidate in location.candidates:
            span = candidate.span
            assert body[span.span_start : span.span_end] == span.span_text
            assert span.span_text == span.span_text.strip()
