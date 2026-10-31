"""Answer-claim binder v3 segment-protocol tests (RQ1-C answer batch).

The binder never trusts the model to invent claim identity. The server splits
the immutable final answer into segments (s1, s2, ...) and the producer must
classify EVERY segment: missing, duplicate or unknown segment refs reject the
whole binding, an asserted/qualified factual segment without positive
evidence support rejects it, ``contradicts`` never satisfies support, and
only ``uncertainty``-classified wording is exempt from evidence.
"""

from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

from src.application.answer_claim_binder import (
    ANSWER_CLAIM_BINDER_PRODUCER,
    AnswerClaimBindingRequest,
    AnswerClaimBindingRow,
    bind_answer_claims,
    factual_claims_fully_bound,
    segment_answer_with_stats,
)
from src.domain.answer_claims import (
    AnswerClaimSnapshotV1,
    answer_content_hash,
    deterministic_claim_id,
)

_ANSWER = "该版本已正式发布。另外该版本没有修复安全漏洞。"  # two factual segments
_ANSWER_ONE = "该版本已正式发布。"
_CLAIM_ONE = "该版本已正式发布。"
_CLAIM_TWO = "另外该版本没有修复安全漏洞。"
_RESEARCH_CLAIM_ID = "research_claim_1"


def _row(evidence_id: str = "evidence_abc123", **extra: Any) -> AnswerClaimBindingRow:
    return AnswerClaimBindingRow(
        evidence_id=evidence_id,
        claim_id=extra.get("claim_id", _RESEARCH_CLAIM_ID),
        title=extra.get("title", "Example release"),
        url=extra.get("url", "https://official.example/release"),
        source_role=extra.get("source_role", "official_statement"),
        source_cluster_id=extra.get("source_cluster_id", "cluster_1"),
        relation=extra.get("relation", "supports"),
        strength=extra.get("strength", "strong"),
        locator=extra.get("locator", "第四段"),
        anchored_spans=extra.get("anchored_spans", ("official confirmation",)),
        caveats=extra.get("caveats", ()),
    )


def _segment(
    ref: str,
    kind: str,
    *,
    status: str = "",
    support: Sequence[str] = (),
) -> dict[str, Any]:
    entry: dict[str, Any] = {"segment_ref": ref, "kind": kind}
    if status:
        entry["status"] = status
    if support:
        entry["evidence_support"] = list(support)
    else:
        entry["evidence_support"] = []
    return entry


def _payload(segments: list[dict[str, Any]], *, refused: bool = False) -> str:
    return json.dumps(
        {"refused": refused, "segments": segments}, ensure_ascii=False
    )


def _request(
    answer: str = "", rows: tuple[AnswerClaimBindingRow, ...] = ()
) -> AnswerClaimBindingRequest:
    return AnswerClaimBindingRequest(
        question="该版本发布了吗？",
        final_answer=answer or _ANSWER,
        evidence_rows=rows,
    )


def _snapshot_of(model_result: Any) -> Any:
    return model_result.snapshot


def _claim_id(answer: str, claim_text: str) -> str:
    return deterministic_claim_id(
        answer_hash=answer_content_hash(answer), claim_text=claim_text
    )


def test_binds_every_factual_segment_to_existing_evidence() -> None:
    request = _request(rows=(_row(), _row("evidence_def456")))
    row_ids = {row.evidence_id for row in request.evidence_rows}

    def model_fn(messages: Sequence[Mapping[str, Any]]) -> str:
        system = str(messages[0]["content"])
        user = str(messages[1]["content"])
        assert "[s1]" in user and "[s2]" in user
        assert "segment_ref" in system
        return _payload(
            [
                _segment("s1", "factual", status="asserted", support=("evidence_abc123",)),
                _segment("s2", "factual", status="asserted", support=("evidence_def456",)),
            ]
        )

    bound = bind_answer_claims(request=request, model_fn=model_fn)
    snapshot = bound.snapshot
    assert snapshot.status == "validated"
    assert snapshot.producer == ANSWER_CLAIM_BINDER_PRODUCER
    assert bound.attempt_count == 1
    assert len(snapshot.claims) == 2
    texts = {claim.text for claim in snapshot.claims}
    assert texts == {_CLAIM_ONE, _CLAIM_TWO}
    assert all(claim.kind == "factual" for claim in snapshot.claims)
    linked_ids = {link.evidence_id for link in snapshot.claim_links}
    assert linked_ids == row_ids
    assert all(
        link.support_type == "direct_support" for link in snapshot.claim_links
    )


def test_server_deterministic_claim_identity_never_from_model() -> None:
    request = _request(answer=_ANSWER_ONE, rows=(_row(),))
    model_claims: dict[str, str] = {}

    def model_fn(messages: Sequence[Mapping[str, Any]]) -> str:
        model_claims["answer"] = "".join(str(m["content"]) for m in messages)
        return _payload(
            [_segment("s1", "factual", status="asserted", support=("evidence_abc123",))]
        )

    snapshot = _snapshot_of(bind_answer_claims(request=request, model_fn=model_fn))
    assert snapshot.status == "validated"
    assert snapshot.claims[0].id == _claim_id(_ANSWER_ONE, _CLAIM_ONE)
    assert all(link.claim_id == snapshot.claims[0].id for link in snapshot.claim_links)


def test_missing_segment_ref_rejects_the_whole_binding() -> None:
    """P0: an uncovered factual statement must never vanish."""
    request = _request(rows=(_row(), _row("evidence_def456")))

    def model_fn(messages: Sequence[Mapping[str, Any]]) -> str:
        return _payload(
            [_segment("s1", "factual", status="asserted", support=("evidence_abc123",))]
        )

    bound = bind_answer_claims(request=request, model_fn=model_fn)
    snapshot = bound.snapshot
    assert snapshot.status == "rejected"
    assert snapshot.reason == "segment_coverage_mismatch"


def test_empty_segments_on_factual_answer_is_rejected() -> None:
    """P0 regression: factual candidate + empty claims + empty links => BLOCKED."""
    request = _request(rows=(_row(),))

    def model_fn(messages: Sequence[Mapping[str, Any]]) -> str:
        return _payload([])

    bound = bind_answer_claims(request=request, model_fn=model_fn)
    snapshot = bound.snapshot
    assert snapshot.status == "rejected"
    assert snapshot.reason == "segment_coverage_mismatch"
    assert snapshot.claims == ()


def test_duplicate_segment_ref_rejects_the_whole_binding() -> None:
    request = _request(rows=(_row(), _row("evidence_def456")))

    def model_fn(messages: Sequence[Mapping[str, Any]]) -> str:
        return _payload(
            [
                _segment("s1", "factual", status="asserted", support=("evidence_abc123",)),
                _segment("s1", "factual", status="asserted", support=("evidence_def456",)),
            ]
        )

    snapshot = _snapshot_of(bind_answer_claims(request=request, model_fn=model_fn))
    assert snapshot.status == "rejected"
    assert snapshot.reason == "segment_coverage_mismatch"


def test_unknown_segment_ref_rejects_the_whole_binding() -> None:
    request = _request(rows=(_row(),))

    def model_fn(messages: Sequence[Mapping[str, Any]]) -> str:
        return _payload(
            [_segment("s99", "factual", status="asserted", support=("evidence_abc123",))]
        )

    snapshot = _snapshot_of(bind_answer_claims(request=request, model_fn=model_fn))
    assert snapshot.status == "rejected"
    assert snapshot.reason == "segment_coverage_mismatch"


def test_factual_segment_without_support_is_rejected() -> None:
    """P0: an asserted factual claim with zero eligible evidence is blocked."""
    request = _request(rows=(_row(),))

    def model_fn(messages: Sequence[Mapping[str, Any]]) -> str:
        return _payload(
            [
                _segment("s1", "factual", status="asserted", support=("evidence_abc123",)),
                _segment("s2", "factual", status="asserted"),
            ]
        )

    snapshot = _snapshot_of(bind_answer_claims(request=request, model_fn=model_fn))
    assert snapshot.status == "rejected"
    assert snapshot.reason == "unbound_factual_segment"


def test_qualified_factual_still_requires_support() -> None:
    """P0: qualified wording is no evidence-free escape hatch."""
    request = _request(rows=(_row(),))

    def without_support(messages: Sequence[Mapping[str, Any]]) -> str:
        return _payload(
            [
                _segment("s1", "factual", status="asserted", support=("evidence_abc123",)),
                _segment("s2", "factual", status="qualified"),
            ]
        )

    rejected = _snapshot_of(bind_answer_claims(request=request, model_fn=without_support))
    assert rejected.status == "rejected"
    assert rejected.reason == "unbound_factual_segment"

    def with_support(messages: Sequence[Mapping[str, Any]]) -> str:
        return _payload(
            [
                _segment("s1", "factual", status="asserted", support=("evidence_abc123",)),
                _segment("s2", "factual", status="qualified", support=("evidence_abc123",)),
            ]
        )

    accepted = _snapshot_of(bind_answer_claims(request=request, model_fn=with_support))
    assert accepted.status == "validated"
    kinds = {claim.status for claim in accepted.claims}
    assert kinds == {"asserted", "qualified"}


def test_uncertainty_segment_needs_no_evidence() -> None:
    answer = "该版本已正式发布。以上说法未能独立核实。"

    def model_fn(messages: Sequence[Mapping[str, Any]]) -> str:
        return _payload(
            [
                _segment("s1", "factual", status="asserted", support=("evidence_abc123",)),
                _segment("s2", "uncertainty"),
            ]
        )

    bound = bind_answer_claims(
        request=_request(answer=answer, rows=(_row(),)), model_fn=model_fn
    )
    snapshot = bound.snapshot
    assert snapshot.status == "validated"
    assert len(snapshot.claims) == 1
    assert snapshot.claims[0].kind == "factual"


def test_non_factual_segment_with_support_is_rejected() -> None:
    answer = "该版本已正式发布。建议查阅官方文档。"

    def model_fn(messages: Sequence[Mapping[str, Any]]) -> str:
        return _payload(
            [
                _segment("s1", "factual", status="asserted", support=("evidence_abc123",)),
                _segment("s2", "recommendation", support=("evidence_abc123",)),
            ]
        )

    snapshot = _snapshot_of(
        bind_answer_claims(request=_request(answer=answer, rows=(_row(),)), model_fn=model_fn)
    )
    assert snapshot.status == "rejected"
    assert snapshot.reason == "non_factual_segment_support"


def test_unknown_evidence_id_fails_closed() -> None:
    request = _request(answer=_ANSWER_ONE, rows=(_row(),))

    def model_fn(messages: Sequence[Mapping[str, Any]]) -> str:
        return _payload(
            [_segment("s1", "factual", status="asserted", support=("evidence_not_in_rows",))]
        )

    snapshot = _snapshot_of(bind_answer_claims(request=request, model_fn=model_fn))
    assert snapshot.status == "rejected"
    assert snapshot.reason == "unknown_evidence_id"


def test_malformed_structured_output_fails_closed_with_retry() -> None:
    request = _request(rows=(_row(),))
    calls = {"count": 0}

    def broken(messages: Sequence[Mapping[str, Any]]) -> str:
        calls["count"] += 1
        if calls["count"] == 1:
            return "not json at all"
        return _payload(
            [
                _segment("s1", "factual", status="asserted", support=("evidence_abc123",)),
                _segment("s2", "factual", status="asserted", support=("evidence_abc123",)),
            ]
        )

    snapshot = _snapshot_of(
        bind_answer_claims(request=request, model_fn=broken, max_attempts=2)
    )
    assert snapshot.status == "validated"
    assert calls["count"] == 2


def test_provider_exception_fails_closed_without_leaking_raw_error() -> None:
    request = _request(rows=(_row(),))

    def exploding(messages: Sequence[Mapping[str, Any]]) -> str:
        raise RuntimeError("raw provider body with secret detail")

    snapshot = _snapshot_of(bind_answer_claims(request=request, model_fn=exploding))
    assert snapshot.status == "rejected"
    assert snapshot.reason == "producer_failed:RuntimeError"
    assert "secret detail" not in snapshot.reason
    assert "secret detail" not in snapshot.to_dict()["reason"]


def test_provider_failure_then_malformed_uses_last_error_reason() -> None:
    request = _request(rows=(_row(),))
    attempts = {"count": 0}

    def flaky(messages: Sequence[Mapping[str, Any]]) -> str:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise TimeoutError("timeout")
        return "not json either"

    snapshot = _snapshot_of(
        bind_answer_claims(request=request, model_fn=flaky, max_attempts=2)
    )
    assert snapshot.status == "rejected"
    assert snapshot.reason == "malformed_structured_output"


def test_producer_refusal_is_rejected() -> None:
    request = _request(rows=(_row(),))

    def refusing(messages: Sequence[Mapping[str, Any]]) -> str:
        return _payload([], refused=True)

    snapshot = _snapshot_of(bind_answer_claims(request=request, model_fn=refusing))
    assert snapshot.status == "rejected"
    assert snapshot.reason == "producer_refused"


def test_final_answer_text_is_never_modified() -> None:
    request = _request(rows=(_row(),))
    original = request.final_answer

    def model_fn(messages: Sequence[Mapping[str, Any]]) -> str:
        return _payload(
            [_segment("s1", "factual", status="asserted", support=("evidence_abc123",))]
        )

    bound = bind_answer_claims(request=request, model_fn=model_fn)
    assert request.final_answer == original
    assert bound.snapshot.answer_hash == answer_content_hash(original)
    assert answer_content_hash(original + " 附加文本") != bound.snapshot.answer_hash


def test_factual_claims_fully_bound_requires_positive_support() -> None:
    """P0: contradicts never satisfies the publication support requirement."""
    request = _request(answer=_ANSWER_ONE, rows=(_row(),))

    def model_fn(messages: Sequence[Mapping[str, Any]]) -> str:
        return _payload(
            [_segment("s1", "factual", status="asserted", support=("evidence_abc123",))]
        )

    snapshot = _snapshot_of(bind_answer_claims(request=request, model_fn=model_fn))
    assert factual_claims_fully_bound(snapshot) is True

    forged = AnswerClaimSnapshotV1(
        answer_hash=snapshot.answer_hash,
        claims=snapshot.claims,
        claim_links=tuple(
            link.__class__(
                claim_id=link.claim_id,
                evidence_id=link.evidence_id,
                support_type="contradicts",
                confidence=link.confidence,
            )
            for link in snapshot.claim_links
        ),
        producer=snapshot.producer,
        status="validated",
        reason=snapshot.reason,
    )
    assert factual_claims_fully_bound(forged) is False


def test_factual_claims_fully_bound_counts_qualified_as_required() -> None:
    claim_one = _claim_id(_ANSWER, _CLAIM_ONE)
    claim_two = _claim_id(_ANSWER, _CLAIM_TWO)
    claims = tuple(
        _claim(text, _ANSWER, _claim_id(_ANSWER, text))
        for text in (_CLAIM_ONE, _CLAIM_TWO)
    )
    snapshot = AnswerClaimSnapshotV1(
        answer_hash=answer_content_hash(_ANSWER),
        claims=claims,
        claim_links=(
            _link(claim_one, "evidence_abc123"),
            _link(claim_two, "evidence_abc123"),
        ),
        producer=ANSWER_CLAIM_BINDER_PRODUCER,
        status="validated",
    )
    assert factual_claims_fully_bound(snapshot) is True
    unbound_second = AnswerClaimSnapshotV1(
        answer_hash=snapshot.answer_hash,
        claims=claims,
        claim_links=(_link(claim_one, "evidence_abc123"),),
        producer=snapshot.producer,
        status="validated",
    )
    assert factual_claims_fully_bound(unbound_second) is False


def test_overlong_or_too_many_segments_fail_closed_without_provider_call() -> None:
    long_answer = "该版本已正式发布。" + "x" * 2000
    calls = {"count": 0}

    def model_fn(messages: Sequence[Mapping[str, Any]]) -> str:
        calls["count"] += 1
        return _payload([])

    bound = bind_answer_claims(
        request=_request(answer=long_answer, rows=(_row(),)), model_fn=model_fn
    )
    assert bound.snapshot.status == "rejected"
    assert bound.snapshot.reason == "answer_not_segmentable"
    assert bound.segment_stats["overflow_reason"] == "segment_chars"
    assert calls["count"] == 0


def test_too_many_short_segments_fail_closed_without_provider_call() -> None:
    # The char limit is not the only ceiling: 17 ordinary sentences are rejected
    # even though every one of them is short. This is the shape that blocked 13
    # of the 20 archived answers.
    answer = "该版本已正式发布。" * 17
    calls = {"count": 0}

    def model_fn(messages: Sequence[Mapping[str, Any]]) -> str:
        calls["count"] += 1
        return _payload([])

    bound = bind_answer_claims(
        request=_request(answer=answer, rows=(_row(),)), model_fn=model_fn
    )

    assert bound.snapshot.status == "rejected"
    assert bound.snapshot.reason == "answer_not_segmentable"
    assert bound.segment_stats["overflow_reason"] == "segment_count"
    assert bound.segment_stats["raw_nonempty_segment_count"] == 17
    assert calls["count"] == 0


def test_the_segment_count_limit_is_exclusive_at_sixteen() -> None:
    sixteen, accepted_stats = segment_answer_with_stats("该版本已正式发布。" * 16)
    seventeen, rejected_stats = segment_answer_with_stats("该版本已正式发布。" * 17)

    assert len(sixteen) == 16
    assert accepted_stats["accepted"] is True
    assert accepted_stats["overflow_reason"] == ""
    assert seventeen == ()
    assert rejected_stats["accepted"] is False
    assert rejected_stats["overflow_reason"] == "segment_count"


def test_a_truncated_segment_prompt_is_refused_instead_of_partially_bound() -> None:
    # Sixteen segments are within the count limit, but their rendered prompt
    # exceeds the context budget. Truncating it would ask the producer to
    # classify segments it never saw, so the binding must fail closed.
    answer = "。".join("该版本" + "甲" * 990 + "已发布" for _ in range(16)) + "。"
    calls = {"count": 0}

    def model_fn(messages: Sequence[Mapping[str, Any]]) -> str:
        calls["count"] += 1
        return _payload([])

    bound = bind_answer_claims(
        request=_request(answer=answer, rows=(_row(),)), model_fn=model_fn
    )

    assert bound.snapshot.status == "rejected"
    assert bound.snapshot.reason == "answer_context_truncated"
    assert bound.segment_stats["context_truncated"] is True
    assert calls["count"] == 0


def test_chinese_and_english_sentence_splitting_is_deterministic() -> None:
    answer = "版本 A 已发布. It fixes bugs. 该版本未修复安全漏洞！"

    def model_fn(messages: Sequence[Mapping[str, Any]]) -> str:
        return _payload(
            [
                _segment("s1", "factual", status="asserted", support=("evidence_abc123",)),
                _segment("s2", "factual", status="asserted", support=("evidence_def456",)),
                _segment("s3", "factual", status="asserted", support=("evidence_abc123",)),
            ]
        )

    bound = bind_answer_claims(
        request=_request(answer=answer, rows=(_row(), _row("evidence_def456"))),
        model_fn=model_fn,
    )
    assert bound.snapshot.status == "validated"
    assert len(bound.snapshot.claims) == 3
    assert all(claim.text in answer for claim in bound.snapshot.claims)


def test_context_contains_segment_refs_and_bounded_evidence_only() -> None:
    request = _request(
        rows=(
            _row(),
            AnswerClaimBindingRow(
                evidence_id="evidence_body_1",
                claim_id=_RESEARCH_CLAIM_ID,
                title="Full body",
                url="https://example.com/body",
                relation="supports",
                strength="strong",
            ),
        )
    )
    seen: list[str] = []

    def model_fn(messages: Sequence[Mapping[str, Any]]) -> str:
        content = str(messages[0]["content"]) + str(messages[1]["content"])
        seen.append(content)
        return _payload(
            [
                _segment("s1", "factual", status="asserted", support=("evidence_abc123",)),
                _segment("s2", "factual", status="asserted", support=("evidence_body_1",)),
            ]
        )

    snapshot = _snapshot_of(bind_answer_claims(request=request, model_fn=model_fn))
    assert snapshot.status == "validated"
    rendered = "\n".join(seen)
    assert "full page body must never leave" not in rendered


def _claim(text: str, answer: str, claim_id: str) -> Any:
    from src.domain.answer_claims import AnswerClaimV1

    return AnswerClaimV1(
        id=claim_id,
        text=text,
        kind="factual",
        status="asserted",
        source="provider_structured",
    )


def _link(claim_id: str, evidence_id: str) -> Any:
    from src.domain.evidence import ClaimEvidenceLinkV1

    return ClaimEvidenceLinkV1(
        claim_id=claim_id,
        evidence_id=evidence_id,
        support_type="direct_support",
        confidence=1.0,
    )
