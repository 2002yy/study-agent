"""Cross-lingual support verification: positive and negative controls.

The binder no longer requires a literal copy of an English page. It accepts a
faithful Chinese statement when the producer returns the exact source sentence
it relied on, and the server can verify that the sentence really occurs in the
cited page. The negatives below are the important half: an unsupported claim, a
wrong source, a fabricated quotation, a wrong number and an invalid synthesis
must all stay rejected.
"""

from __future__ import annotations

import json
import re
from typing import Any, Mapping, Sequence

import pytest

from src.application.answer_claim_binder import (
    AnswerClaimBindingRequest,
    AnswerClaimBindingRow,
    bind_answer_claims,
    substantive_claims_fully_bound,
)
from src.domain.answer_claims import AnswerClaimSnapshotV1

EVIDENCE_ID = "tool_read_1"
OTHER_EVIDENCE_ID = "tool_read_2"
CLAIM_ID = "inline_tool_read"

QUESTION = (
    "帮我调研一个部署决策：我有一个单用户聊天应用，FastAPI 后端，"
    "聊天记录存在 SQLite，准备启动 4 个 worker，同时运行后台资料索引任务。"
    "我应该继续用 SQLite WAL，还是迁移 PostgreSQL？"
)

WAL_PAGE = (
    "Write-Ahead Logging. In WAL mode readers do not block writers and writers "
    "do not block readers. Only one writer can hold the write lock at a time. "
    "A writer holds the lock until its transaction commits. WAL mode requires "
    "shared memory, so every process must run on the same host and the database "
    "file must live on a local disk; it does not work over a network filesystem."
)

OTHER_PAGE = (
    "PostgreSQL uses multi-version concurrency control so readers never block "
    "writers. A long transaction keeps old row versions alive."
)


def _row(
    evidence_id: str = EVIDENCE_ID,
    *,
    body: str = WAL_PAGE,
    claim_id: str = CLAIM_ID,
) -> AnswerClaimBindingRow:
    return AnswerClaimBindingRow(
        evidence_id=evidence_id,
        claim_id=claim_id,
        title="SQLite Write-Ahead Logging",
        url=f"https://sqlite.org/{evidence_id}.html",
        source_role="public_page",
        source_cluster_id="sqlite.org",
        relation="read",
        strength="",
        locator="",
        anchored_spans=(),
        caveats=("read_by_inline_tool_loop",),
        grounding_text=body,
    )


def _request(
    answer: str, *, rows: Sequence[AnswerClaimBindingRow] = ()
) -> AnswerClaimBindingRequest:
    return AnswerClaimBindingRequest(
        question=QUESTION,
        final_answer=answer,
        evidence_rows=tuple(rows) if rows else (_row(),),
    )


def _entry(
    ref: str,
    *,
    kind: str = "source_fact",
    status: str = "asserted",
    support: Sequence[str] = (),
    support_claims: Sequence[Mapping[str, Any]] = (),
    research_claim_id: str = CLAIM_ID,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"segment_ref": ref, "kind": kind}
    if kind in {"source_fact", "factual", "synthesis", "recommendation"}:
        payload["status"] = status
        payload["research_claim_id"] = research_claim_id
    if support:
        payload["evidence_support"] = list(support)
    if support_claims:
        payload["support_claims"] = [dict(item) for item in support_claims]
    return payload


def _payload(entries: Sequence[Mapping[str, Any]], *, refused: bool = False) -> str:
    return json.dumps({"refused": refused, "segments": list(entries)}, ensure_ascii=False)


def _bind(answer: str, entries: FactoryEntries, *, rows: Sequence[AnswerClaimBindingRow] = ()):
    return bind_answer_claims(
        request=_request(answer, rows=rows),
        model_fn=lambda messages: _payload(entries(messages)),
    )


FactoryEntries = Any


def _quoted(quote: str, relation: str = "paraphrase", evidence_id: str = EVIDENCE_ID):
    return {"evidence_id": evidence_id, "relation": relation, "source_quote": quote}


def _assert_rejected(bound, reason: str) -> AnswerClaimSnapshotV1:
    snapshot = bound.snapshot
    assert snapshot.status == "rejected"
    assert snapshot.reason == reason
    assert snapshot.claims == ()
    return snapshot


def _assert_withheld(bound, reason: str) -> AnswerClaimSnapshotV1:
    """The claim is dropped from the published text, never silently kept."""

    snapshot = bound.snapshot
    assert snapshot.status == "validated"
    assert bound.withheld and bound.withheld[0]["reason"] == reason
    assert bound.withheld[0]["segment"] not in bound.published_text
    assert all(claim.text != bound.withheld[0]["segment"] for claim in snapshot.claims)
    return snapshot


def test_faithful_chinese_translation_is_supported_by_the_source_sentence() -> None:
    answer = "WAL 模式下同一时刻只允许一个写事务，写者持有写锁直到事务提交。"
    bound = _bind(
        answer,
        lambda messages: [
            _entry(
                "s1",
                support_claims=[
                    _quoted(
                        "Only one writer can hold the write lock at a time.",
                    )
                ],
            )
        ],
    )
    snapshot = bound.snapshot
    assert snapshot.status == "validated"
    assert snapshot.claim_links[0].support_type == "indirect_support"
    assert snapshot.claim_links[0].confidence >= 0.7
    assert substantive_claims_fully_bound(snapshot) is True


def test_chinese_synonym_rewrite_is_supported_by_a_second_sentence() -> None:
    answer = "在 WAL 下读操作不会阻塞写入，写入也不会阻塞读取。"
    bound = _bind(
        answer,
        lambda messages: [
            _entry(
                "s1",
                support_claims=[
                    _quoted(
                        "In WAL mode readers do not block writers and writers do not block readers."
                    )
                ],
            )
        ],
    )
    assert bound.snapshot.status == "validated"


def test_an_exaggerated_conclusion_is_rejected_as_contradicted() -> None:
    answer = "因此 SQLite 在 WAL 模式下可以无限并发写入。"
    bound = _bind(
        answer,
        lambda messages: [
            _entry(
                "s1",
                support_claims=[
                    _quoted(
                        "Only one writer can hold the write lock at a time.",
                        relation="contradicts",
                    )
                ],
            )
        ],
    )
    _assert_rejected(bound, "claim_contradicted")


def test_a_real_page_that_does_not_support_the_fact_is_withheld() -> None:
    answer = "WAL 模式可以跨 NFS 网络文件系统安全运行。"
    bound = _bind(
        answer,
        lambda messages: [_entry("s1")],
    )
    _assert_withheld(bound, "unbound_factual_segment")


def test_a_citation_to_the_wrong_source_is_rejected() -> None:
    """The quotation must occur in the page the claim cites."""

    answer = "WAL 模式下同一时刻只允许一个写事务。"
    rows = (_row(), _row(OTHER_EVIDENCE_ID, body=OTHER_PAGE))
    bound = _bind(
        answer,
        lambda messages: [
            _entry(
                "s1",
                support_claims=[
                    _quoted(
                        "Only one writer can hold the write lock at a time.",
                        evidence_id=OTHER_EVIDENCE_ID,
                    )
                ],
            )
        ],
        rows=rows,
    )
    _assert_rejected(bound, "unverified_source_quote")


def test_a_fabricated_quotation_is_rejected() -> None:
    answer = "WAL 模式下同一时刻只允许一个写事务。"
    bound = _bind(
        answer,
        lambda messages: [
            _entry(
                "s1",
                support_claims=[
                    _quoted("SQLite allows unlimited concurrent writers in WAL.")
                ],
            )
        ],
    )
    _assert_rejected(bound, "unverified_source_quote")


def test_a_correct_fact_with_a_wrong_number_is_rejected() -> None:
    answer = "官方建议为 WAL 配置 4 个后台检查点线程。"
    bound = _bind(
        answer,
        lambda messages: [
            _entry(
                "s1",
                support_claims=[
                    _quoted(
                        "Only one writer can hold the write lock at a time."
                    )
                ],
            )
        ],
    )
    _assert_rejected(bound, "claim_specifics_not_in_source")


def test_two_true_facts_do_not_authorize_an_unsupported_inference() -> None:
    answer = "读不阻塞写，写不阻塞读，所以单表可以支持 8 个并发写入者。"
    bound = _bind(
        answer,
        lambda messages: [
            _entry(
                "s1",
                kind="synthesis",
                support_claims=[
                    _quoted(
                        "In WAL mode readers do not block writers and writers do not block readers."
                    )
                ],
            )
        ],
    )
    _assert_rejected(bound, "claim_specifics_not_in_source")


def test_a_synthesis_with_verified_premises_is_published_as_an_inference() -> None:
    answer = "读不阻塞写且只有一个写者，因此单用户场景下写入不是主要瓶颈。"
    bound = _bind(
        answer,
        lambda messages: [
            _entry(
                "s1",
                kind="synthesis",
                support_claims=[
                    _quoted(
                        "Only one writer can hold the write lock at a time."
                    )
                ],
            )
        ],
    )
    snapshot = bound.snapshot
    assert snapshot.status == "validated"
    assert snapshot.claims[0].kind == "synthesis"
    assert substantive_claims_fully_bound(snapshot) is True


def test_insufficient_source_material_must_stay_uncertain() -> None:
    answer = "这一点无法从现有资料确认。"
    bound = _bind(answer, lambda messages: [_entry("s1", kind="uncertainty")])
    snapshot = bound.snapshot
    assert snapshot.status == "validated"
    assert snapshot.claims[0].kind == "uncertainty"
    assert snapshot.claim_links == ()


def test_a_recommendation_without_a_specific_number_needs_no_citation() -> None:
    answer = "建议先保留 WAL，并观察后台索引任务的事务长度。"
    bound = _bind(answer, lambda messages: [_entry("s1", kind="recommendation")])
    snapshot = bound.snapshot
    assert snapshot.status == "validated"
    assert snapshot.claims[0].kind == "recommendation"
    assert substantive_claims_fully_bound(snapshot) is True


def test_a_recommendation_cannot_smuggle_an_uncited_number() -> None:
    answer = "建议把 worker 数量调整为 4。"
    bound = _bind(answer, lambda messages: [_entry("s1", kind="recommendation")])
    _assert_withheld(bound, "unsupported_specific_claim")


def test_a_restated_setup_is_a_premise_grounded_in_the_question() -> None:
    answer = "你的应用是单用户聊天应用，聊天记录存在 SQLite。"
    bound = _bind(answer, lambda messages: [_entry("s1", kind="premise")])
    snapshot = bound.snapshot
    assert snapshot.status == "validated"
    assert snapshot.claims[0].kind == "premise"
    assert snapshot.claim_links == ()
    assert substantive_claims_fully_bound(snapshot) is True


def test_a_premise_that_invents_a_number_is_withheld() -> None:
    answer = "你的应用是单用户聊天应用，并且已经启动了 12 个 worker。"
    bound = _bind(answer, lambda messages: [_entry("s1", kind="premise")])
    _assert_withheld(bound, "premise_not_in_question")


def test_a_premise_cannot_carry_source_support() -> None:
    answer = "你的应用是单用户聊天应用。"
    bound = _bind(
        answer,
        lambda messages: [
            _entry("s1", kind="premise", support_claims=[
                _quoted("Only one writer can hold the write lock at a time.")
            ])
        ],
    )
    _assert_rejected(bound, "premise_with_support")


def test_a_premise_may_carry_an_inert_claim_id_and_status() -> None:
    """A provider that fills every field must not cost the answer its premise.

    ``research_claim_id`` with an empty support list authorizes nothing, so it
    is recorded rather than rejected.
    """

    answer = "你的应用是单用户聊天应用。"
    bound = _bind(
        answer,
        lambda messages: [
            _entry("s1", kind="premise", research_claim_id=CLAIM_ID)
        ],
    )
    snapshot = bound.snapshot
    assert snapshot.status == "validated"
    assert snapshot.claims[0].kind == "premise"


def test_a_synthesis_may_reuse_a_number_from_the_question() -> None:
    answer = "在单用户场景下，4 个 worker 的并发写入不会突破单写者限制。"
    bound = _bind(
        answer,
        lambda messages: [
            _entry(
                "s1",
                kind="synthesis",
                support_claims=[
                    _quoted("Only one writer can hold the write lock at a time.")
                ],
            )
        ],
    )
    assert bound.snapshot.status == "validated"


def test_a_multi_sentence_quote_passes_only_when_every_sentence_is_real() -> None:
    genuine = (
        "Only one writer can hold the write lock at a time. "
        "A writer holds the lock until its transaction commits."
    )
    bound = _bind(
        "WAL 下写者持有写锁直到事务提交。",
        lambda messages: [
            _entry("s1", support_claims=[_quoted(genuine)])
        ],
    )
    assert bound.snapshot.status == "validated"

    stitched = (
        "Only one writer can hold the write lock at a time. "
        "SQLite supports unlimited concurrent writers."
    )
    bound = _bind(
        "WAL 下写者持有写锁直到事务提交。",
        lambda messages: [
            _entry("s1", support_claims=[_quoted(stitched)])
        ],
    )
    _assert_rejected(bound, "unverified_source_quote")


def test_citation_labels_are_not_claim_numbers() -> None:
    from src.application.answer_claim_binder import _specific_tokens

    assert _specific_tokens("[web-4](https://docs.example/x) 引的就是这条。") == set()
    assert _specific_tokens("见 [3]，共 4 个连接。") == {"4"}
    assert _specific_tokens("建议把连接数设为 4。") == {"4"}


def test_a_long_structured_answer_is_verified_in_batches_and_published() -> None:
    """The 133-unit shape that used to be rejected wholesale."""

    lines = [
        f"第{chr(0x4E00 + index)}说：WAL 模式下读不阻塞写，写入由写锁排队处理，后台索引应缩短事务。"
        for index in range(40)
    ]
    answer = "\n\n".join(lines)
    calls: list[int] = []

    def model(messages: Sequence[Mapping[str, Any]]) -> str:
        entries = re.findall(r"\[(s\d+)\] ", str(messages[1]["content"]))
        calls.append(len(entries))
        return _payload(
            [
                _entry(
                    ref,
                    support_claims=[
                        _quoted(
                            "In WAL mode readers do not block writers and writers do not block readers."
                        )
                    ],
                )
                for ref in entries
            ]
        )

    bound = bind_answer_claims(request=_request(answer), model_fn=model)
    assert bound.snapshot.status == "validated"
    assert len(bound.snapshot.claims) == 40
    assert sum(calls) == 40
    assert len(calls) > 1
    assert all(size <= 16 for size in calls)


@pytest.mark.parametrize("failure_batch", [1, 2])
def test_a_failure_in_one_batch_rejects_the_whole_answer(failure_batch: int) -> None:
    answer = "\n\n".join(
        "WAL 模式下只有一个写者，读请求不会阻塞写入。" for _ in range(40)
    )
    calls = {"count": 0}

    def model(messages: Sequence[Mapping[str, Any]]) -> str:
        calls["count"] += 1
        entries = re.findall(r"\[(s\d+)\] ", str(messages[1]["content"]))
        if calls["count"] == failure_batch:
            raise TimeoutError("provider_timeout")
        return _payload(
            [
                _entry(
                    ref,
                    support_claims=[
                        _quoted("Only one writer can hold the write lock at a time.")
                    ],
                )
                for ref in entries
            ]
        )

    bound = bind_answer_claims(
        request=_request(answer),
        model_fn=model,
        max_attempts=1,
    )
    snapshot = bound.snapshot
    assert snapshot.status == "rejected"
    assert snapshot.reason.startswith(f"batch_{failure_batch}_of_")
    assert snapshot.reason.endswith("producer_failed:TimeoutError")
    assert snapshot.claims == ()
