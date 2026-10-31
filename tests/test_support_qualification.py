"""A3 controls: what a verified passage plus a verdict is allowed to buy.

The decisive case is the one #321 blocked: a verified paraphrase cannot pass the
literal binder rule, but with a server qualification it must be able to publish.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

from src.application.answer_claim_binder import (
    AnswerClaimBindingRequest,
    AnswerClaimBindingRow,
    bind_answer_claims,
    claim_grounded_in_text,
)
from src.domain.answer_claims import answer_content_hash, deterministic_claim_id
from src.web.research.claim_span_provenance import verify_claim_span
from src.web.research.read_evidence import ReadEvidence
from src.web.research.support_qualification import (
    CONTRADICTS,
    INSUFFICIENT,
    REASON_EVIDENCE_OUTSIDE_PASSAGE,
    REASON_INVALID_VERDICT,
    REASON_OTHER_CLAIM,
    REASON_UNKNOWN_PASSAGE,
    SUPPORTS,
    UNRESOLVED_CONFLICT,
    ClaimJudgement,
    decide_claim_support,
    passage_key,
)

BODY = "公司公告显示，研发费用同比增加百分之三十，净利润同比下降百分之十二。"
PASSAGE = "研发费用同比增加百分之三十，净利润同比下降百分之十二"
CLAIM = "研发投入上升使利润下滑"
URL = "https://news.example/earnings"
READ_ID = "read_a1"
EVIDENCE_ID = "tool_read_1"


def _verified(claim_text: str = CLAIM, body: str = BODY):
    record = ReadEvidence.build(url=URL, excerpt=body, read_id=READ_ID)
    start = body.index(PASSAGE)
    candidate = {
        "claim_id": "claim_x",
        "claim_text": claim_text,
        "evidence_id": EVIDENCE_ID,
        "url": URL,
        "read_id": READ_ID,
        "span_start": start,
        "span_end": start + len(PASSAGE),
        "span_text": PASSAGE,
        "excerpt_sha256": record.content_sha256,
    }
    return verify_claim_span(
        candidate,
        evidence=[record],
        evidence_ids={EVIDENCE_ID},
        evidence_urls={EVIDENCE_ID: URL},
    )


def _decision(candidates, judgements):
    return decide_claim_support("claim_x", candidates=candidates, judgements=judgements)


def test_a_verified_support_qualifies_a_paraphrase():
    candidate = _verified()
    decision = _decision(
        [candidate],
        [
            ClaimJudgement(
                claim_id="claim_x",
                passage_key=passage_key(candidate),
                verdict=SUPPORTS,
                evidence_span=PASSAGE,
            )
        ],
    )

    assert decision.publishable is True
    assert decision.verdict == SUPPORTS
    assert len(decision.qualified) == 1
    row = decision.qualified[0].as_binding_row()
    assert row["grounding_text"] == ""
    assert row["relation"] == "supports"
    assert row["locator"] == candidate.locator
    assert row["anchored_spans"] == [PASSAGE]


def test_the_qualified_row_is_what_makes_the_paraphrase_publishable():
    # The literal rule alone refuses this paraphrase, which is the whole reason
    # the qualification layer exists.
    assert claim_grounded_in_text(CLAIM, BODY) is False

    candidate = _verified(claim_text=CLAIM)
    decision = _decision(
        [candidate],
        [
            ClaimJudgement(
                claim_id="claim_x",
                passage_key=passage_key(candidate),
                verdict=SUPPORTS,
                evidence_span=PASSAGE,
            )
        ],
    )
    answer = CLAIM + "。"
    claim_id = deterministic_claim_id(
        answer_hash=answer_content_hash(answer), claim_text=CLAIM
    )
    row = AnswerClaimBindingRow(
        **{**decision.qualified[0].as_binding_row(), "claim_id": claim_id}
    )

    def model_fn(messages: Sequence[Mapping[str, Any]]) -> str:
        return json.dumps(
            {
                "refused": False,
                "segments": [
                    {
                        "segment_ref": "s1",
                        "kind": "factual",
                        "status": "asserted",
                        "research_claim_id": claim_id,
                        "evidence_support": [EVIDENCE_ID],
                    }
                ],
            },
            ensure_ascii=False,
        )

    bound = bind_answer_claims(
        request=AnswerClaimBindingRequest(
            question="利润为什么下降", final_answer=answer, evidence_rows=(row,)
        ),
        model_fn=model_fn,
    )

    assert bound.snapshot.status == "validated"
    assert len(bound.snapshot.claim_links) == 1


def test_a_contradiction_blocks_publication_even_with_support_present():
    candidate = _verified()
    decision = _decision(
        [candidate],
        [
            ClaimJudgement(
                claim_id="claim_x",
                passage_key=passage_key(candidate),
                verdict=SUPPORTS,
                evidence_span=PASSAGE,
            ),
            ClaimJudgement(
                claim_id="claim_x",
                passage_key=passage_key(candidate),
                verdict=CONTRADICTS,
                evidence_span=PASSAGE,
            ),
        ],
    )

    assert decision.publishable is False
    assert decision.verdict == UNRESOLVED_CONFLICT
    assert decision.qualified == ()


def test_a_lone_contradiction_is_not_a_conclusion():
    candidate = _verified()
    decision = _decision(
        [candidate],
        [
            ClaimJudgement(
                claim_id="claim_x",
                passage_key=passage_key(candidate),
                verdict=CONTRADICTS,
                evidence_span=PASSAGE,
            )
        ],
    )

    assert decision.publishable is False
    assert decision.verdict == CONTRADICTS


def test_a_judgement_that_quotes_text_outside_the_passage_is_refused():
    candidate = _verified()
    decision = _decision(
        [candidate],
        [
            ClaimJudgement(
                claim_id="claim_x",
                passage_key=passage_key(candidate),
                verdict=SUPPORTS,
                evidence_span="收入增长导致利润上升",
            )
        ],
    )

    assert decision.publishable is False
    assert decision.verdict == INSUFFICIENT
    assert decision.refused[0]["reason"] == REASON_EVIDENCE_OUTSIDE_PASSAGE


def test_a_judgement_about_an_unknown_passage_is_refused():
    candidate = _verified()
    decision = _decision(
        [candidate],
        [
            ClaimJudgement(
                claim_id="claim_x",
                passage_key="read_other:0-10",
                verdict=SUPPORTS,
                evidence_span=PASSAGE,
            )
        ],
    )

    assert decision.publishable is False
    assert decision.refused[0]["reason"] == REASON_UNKNOWN_PASSAGE


def test_a_judgement_for_another_claim_is_refused():
    candidate = _verified()
    decision = _decision(
        [candidate],
        [
            ClaimJudgement(
                claim_id="claim_other",
                passage_key=passage_key(candidate),
                verdict=SUPPORTS,
                evidence_span=PASSAGE,
            )
        ],
    )

    assert decision.publishable is False
    assert decision.refused[0]["reason"] == REASON_OTHER_CLAIM


def test_an_unknown_verdict_is_refused():
    candidate = _verified()
    decision = _decision(
        [candidate],
        [
            ClaimJudgement(
                claim_id="claim_x",
                passage_key=passage_key(candidate),
                verdict="probably",
                evidence_span=PASSAGE,
            )
        ],
    )

    assert decision.publishable is False
    assert decision.refused[0]["reason"] == REASON_INVALID_VERDICT


def test_no_verified_passage_means_no_qualification():
    unverified = verify_claim_span(
        {
            "claim_id": "claim_x",
            "claim_text": CLAIM,
            "evidence_id": EVIDENCE_ID,
            "url": URL,
            "read_id": READ_ID,
            "span_start": 0,
            "span_end": 5,
            "span_text": "完全不相关的句子",
            "excerpt_sha256": hashlib.sha256(BODY.encode("utf-8")).hexdigest(),
        },
        evidence=[ReadEvidence.build(url=URL, excerpt=BODY, read_id=READ_ID)],
        evidence_ids={EVIDENCE_ID},
        evidence_urls={EVIDENCE_ID: URL},
    )

    decision = _decision(
        [unverified],
        [
            ClaimJudgement(
                claim_id="claim_x",
                passage_key=passage_key(unverified),
                verdict=SUPPORTS,
                evidence_span="完全不相关的句子",
            )
        ],
    )

    assert decision.publishable is False
    assert decision.verdict == INSUFFICIENT


def test_duplicate_supports_from_one_passage_are_deduplicated():
    candidate = _verified()
    same = ClaimJudgement(
        claim_id="claim_x",
        passage_key=passage_key(candidate),
        verdict=SUPPORTS,
        evidence_span=PASSAGE,
    )

    decision = _decision([candidate], [same, same])

    assert decision.publishable is True
    assert len(decision.qualified) == 1


def test_no_judgement_means_insufficient_not_publishable():
    decision = _decision([_verified()], [])

    assert decision.publishable is False
    assert decision.verdict == INSUFFICIENT
