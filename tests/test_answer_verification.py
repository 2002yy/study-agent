from dataclasses import replace
import threading
import time

import pytest

from src.application.answer_claim_binder import AnswerClaimBindingRow
from src.application.answer_verification import (
    AnswerVerificationInputs,
    BoundaryProposal,
    CalculationProposal,
    QuoteProposal,
    observe_answer_verification,
    observe_answer_verification_bounded,
)
from src.application.chat_service import ChatCommand
from src.application.exact_calculation import check_boundary, check_calculation
from src.domain.answer_claims import answer_content_hash
from src.web.research.evidence_binding import document_from_read
from tests.test_chat_service import _service


def quote_inputs(text="Rated output is 18 W.", candidate="Candidate"):
    document = document_from_read("read-1", "https://example.org/spec", text.encode())
    quote = QuoteProposal(
        "rq-1",
        "ev-1",
        document.read_id,
        document.source_url,
        document.content_sha256,
        document.payload_sha256,
        (0, len(document.text)),
        document.text,
    )
    row = AnswerClaimBindingRow(
        "ev-1", "rq-1", url=document.source_url, relation="supports", strength="strong"
    )
    return AnswerVerificationInputs(
        answer_content_hash(candidate),
        (document,),
        (row,),
        (quote,),
        evidence_reads=(
            (
                "ev-1",
                document.read_id,
                document.content_sha256,
                document.payload_sha256,
            ),
        ),
    )


def test_exact_read_quote_reuses_ledger_but_never_grants_semantic_support():
    report = observe_answer_verification("Candidate", quote_inputs())
    assert report["quotes"][0]["status"] == "PASS"
    assert report["semantic_support"] == "UNKNOWN"
    assert not report["publication_authority"]
    assert report["coverage"]["calculations"] == "NOT_OBSERVED"


def test_real_source_wrong_direct_quote_is_detected():
    inputs = quote_inputs()
    inputs = replace(
        inputs, quotes=(replace(inputs.quotes[0], text="Rated output is 22 W."),)
    )
    assert (
        observe_answer_verification("Candidate", inputs)["quotes"][0]["reason"]
        == "quote_mismatch"
    )


def test_identical_text_different_read_version_cannot_be_substituted():
    inputs = quote_inputs()
    document = document_from_read(
        "read-1", "https://example.org/spec", b"<b>Rated output is 18 W.</b>"
    )
    # Visible content is identical; payload version has changed.
    assert document.text == inputs.documents[0].text
    report = observe_answer_verification(
        "Candidate", replace(inputs, documents=(document,))
    )
    assert report["quotes"][0]["reason"] == "read_binding_mismatch"


def test_correct_paraphrase_is_not_rejected_as_a_false_quote():
    inputs = quote_inputs("The measured pressure fell by about one fifth.")
    proposal = replace(inputs.quotes[0], kind="paraphrase", text="压力约降低20%。")
    report = observe_answer_verification(
        "Candidate", replace(inputs, quotes=(proposal,))
    )
    assert report["quotes"][0]["status"] == "UNKNOWN"
    assert report["quotes"][0]["reason"] == "paraphrase_requires_semantic_verification"


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"claim_id": "rq-other"}, "claim_evidence_mismatch"),
        ({"evidence_id": "ev-other"}, "claim_evidence_mismatch"),
        ({"source_url": "https://example.org/other"}, "evidence_source_mismatch"),
        ({"content_sha256": "0" * 64}, "evidence_read_version_mismatch"),
    ],
)
def test_quote_lineage_negative_controls(change, reason):
    inputs = quote_inputs()
    proposal = replace(inputs.quotes[0], **change)
    check = observe_answer_verification(
        "Candidate", replace(inputs, quotes=(proposal,))
    )["quotes"][0]
    assert check["status"] == "FAIL"
    assert check["reason"] == reason


@pytest.mark.parametrize("strength", ["0.6", "nan", "inf"])
def test_existing_support_strength_is_not_promoted(strength):
    inputs = quote_inputs()
    inputs = replace(
        inputs, evidence_rows=(replace(inputs.evidence_rows[0], strength=strength),)
    )
    assert (
        observe_answer_verification("Candidate", inputs)["quotes"][0]["status"]
        == "FAIL"
    )


def test_no_snapshot_or_duplicate_read_does_not_guess_a_version():
    inputs = quote_inputs()
    for documents in ((), inputs.documents * 2):
        check = observe_answer_verification(
            "Candidate", replace(inputs, documents=documents)
        )["quotes"][0]
        assert check["status"] == "UNKNOWN"


def test_empty_metadata_and_invalid_span_are_unknown():
    inputs = quote_inputs()
    for change in ({"span": (False, 3)}, {"span": (0, 1000)}):
        check = observe_answer_verification(
            "Candidate", replace(inputs, quotes=(replace(inputs.quotes[0], **change),))
        )["quotes"][0]
        assert check["status"] == "UNKNOWN"


def test_evidence_from_old_read_cannot_be_attached_to_a_new_same_url_read():
    inputs = quote_inputs()
    updated = document_from_read(
        "read-2", "https://example.org/spec", b"New output is 21 W."
    )
    quote = replace(
        inputs.quotes[0],
        read_id=updated.read_id,
        content_sha256=updated.content_sha256,
        payload_sha256=updated.payload_sha256,
        text=updated.text,
        span=(0, len(updated.text)),
    )
    report = observe_answer_verification(
        "Candidate", replace(inputs, documents=(updated,), quotes=(quote,))
    )
    assert report["quotes"][0]["reason"] == "evidence_read_version_mismatch"


def test_missing_server_evidence_read_join_cannot_be_inferred_from_url():
    inputs = quote_inputs()
    assert (
        observe_answer_verification("Candidate", replace(inputs, evidence_reads=()))[
            "quotes"
        ][0]["status"]
        == "UNKNOWN"
    )


def test_wrong_formula_with_correct_arithmetic_never_becomes_verified():
    check = check_calculation(
        "length + width", "7", variables={"length": "3", "width": "4"}
    )
    # A proposed area formula is wrong; this checker certifies no interpretation.
    assert check.status == "PASS"
    assert check.semantic_support == "UNKNOWN"


def test_formula_correct_numeric_result_wrong_is_detected():
    assert check_calculation("9.9 * 0.1", "0.98").status == "FAIL"
    assert check_calculation("9.9 * 0.1", "0.99").status == "PASS"


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('echo unsafe')",
        "x.y",
        "x[0]",
        "sum([1,2])",
        "2 ** 100000",
        "1 / 0",
        "True + 1",
        "1e100000",
        "1_000 + 2",
        "+".join(["1"] * 100),
    ],
)
def test_unsafe_unsupported_and_excessive_expressions_are_unknown(expression):
    assert check_calculation(expression, "0").status == "UNKNOWN"


def test_rounding_requires_explicit_policy_and_no_float_tolerance():
    assert check_calculation("1 / 3", "0.333").status == "FAIL"
    assert check_calculation("1 / 3", "0.333", places=3).status == "PASS"
    assert check_calculation("2.5", "3", places=0, rounding="half_up").status == "PASS"
    assert (
        check_calculation("2.5", "3", places=0, rounding="half_even").status == "FAIL"
    )
    assert (
        check_calculation("2.5", "3", places=0, rounding="unknown").status == "UNKNOWN"
    )


def boundary(**changes):
    arguments = dict(
        left="7 + 2*x",
        right="1 + 5*x",
        variable="x",
        claimed="2",
        below="1",
        above="3",
        below_relation=">",
        above_relation="<",
    )
    arguments.update(changes)
    return check_boundary(**arguments)


def test_boundary_correct_but_sides_reversed_is_detected():
    assert boundary().status == "PASS"
    assert (
        boundary(below_relation="<", above_relation=">").reason
        == "boundary_sides_reversed"
    )
    assert boundary(claimed="3").reason == "boundary_mismatch"
    assert boundary(below="2").status == "UNKNOWN"
    assert boundary(left="x*x").status == "UNKNOWN"


def test_full_report_unknown_and_stale_candidate_and_input_caps():
    inputs = AnswerVerificationInputs(answer_content_hash("Candidate"))
    assert observe_answer_verification("Candidate", inputs)["status"] == "UNKNOWN"
    assert (
        observe_answer_verification("Other", inputs)["reason"]
        == "candidate_identity_mismatch"
    )
    inputs = replace(inputs, calculations=(CalculationProposal("1+1", "2"),) * 33)
    assert observe_answer_verification("Candidate", inputs)["reason"] == "input_limit"


def test_calculation_and_boundary_proposals_share_one_shadow_api():
    inputs = AnswerVerificationInputs(
        answer_content_hash("Candidate"),
        original_question="mass 3; boundary 7 2 1 5",
        calculations=(
            CalculationProposal(
                "2 * mass",
                "6",
                (("mass", "3"),),
                formula_origin=("user_given", ""),
            ),
        ),
        boundaries=(
            BoundaryProposal(
                "7+2*x", "1+5*x", "x", "2", "1", "3", ">", "<",
                formula_origin=("user_given", ""),
            ),
        ),
    )
    report = observe_answer_verification("Candidate", inputs)
    assert report["status"] == "PASS"
    assert report["model_calls"] == 0
    assert report["semantic_support"] == "UNKNOWN"


def test_unverified_formula_origin_cannot_read_as_pass():
    # Same arithmetic, but the formula premises are not located in the question
    # or an owned read: PASS arithmetic must not upgrade to verified support.
    inputs = AnswerVerificationInputs(
        answer_content_hash("Candidate"),
        calculations=(CalculationProposal("2 * 3", "6", formula_origin=("model_recall", "")),),
    )
    report = observe_answer_verification("Candidate", inputs)
    assert report["calculations"][0]["status"] == "PASS"
    assert report["calculations"][0]["verified_support"] is False
    assert report["status"] == "UNKNOWN"


def test_chat_shadow_records_wrong_calculation_without_changing_answer(tmp_path):
    service, repository = _service(tmp_path)
    prepared = service.start_turn(
        ChatCommand(user_input="Explain force", thread_id="verification-shadow")
    )
    candidate = "The result is 5."
    inputs = AnswerVerificationInputs(
        answer_content_hash(candidate),
        calculations=(CalculationProposal("2 * 3", "5"),),
    )
    prepared = replace(prepared, answer_verification_inputs=inputs)
    completed = service.complete_turn(prepared, candidate)
    restored = repository.get_chat_turn(completed.id)
    assert restored.assistant_message == candidate
    assert restored.rag_snapshot["answer_verification_shadow"]["status"] == "FAIL"
    assert not restored.rag_snapshot["answer_verification_shadow"][
        "publication_authority"
    ]
    assert "answer_verification_shadow" not in prepared.rag


def test_chat_default_has_no_shadow_or_extra_model_call(tmp_path):
    service, repository = _service(tmp_path)
    prepared = service.start_turn(
        ChatCommand(user_input="Explain force", thread_id="default-shadow")
    )
    completed = service.complete_turn(prepared, "Answer")
    assert (
        "answer_verification_shadow"
        not in repository.get_chat_turn(completed.id).rag_snapshot
    )


def test_shadow_failure_and_stalled_worker_do_not_change_business_state(monkeypatch):
    from src.application import answer_verification as module

    release, started, finished = threading.Event(), threading.Event(), threading.Event()

    def stalled(*args):
        started.set()
        release.wait(timeout=2)
        finished.set()
        return {"status": "FAIL"}

    monkeypatch.setattr(module, "observe_answer_verification", stalled)
    try:
        report = observe_answer_verification_bounded("Candidate", quote_inputs())
        assert started.is_set()
        assert report["status"] == "UNKNOWN"
        assert not report["publication_authority"]
        assert not finished.is_set()
    finally:
        release.set()
    assert finished.wait(timeout=2)


def test_missing_and_corrupt_input_cannot_masquerade_as_zero_errors():
    inputs = quote_inputs()
    assert (
        observe_answer_verification(
            "Candidate", replace(inputs, quotes=(), evidence_reads=())
        )["status"]
        == "UNKNOWN"
    )
    document = replace(inputs.documents[0], text="Changed server snapshot")
    report = observe_answer_verification(
        "Candidate", replace(inputs, documents=(document,))
    )
    assert report["quotes"][0]["reason"] == "read_content_hash_mismatch"


def test_shadow_never_starts_after_research_deadline(monkeypatch):
    from src.application import answer_verification as module

    called = []
    monkeypatch.setattr(
        module, "observe_answer_verification", lambda *args: called.append(True)
    )
    report = observe_answer_verification_bounded(
        "Candidate", quote_inputs(), deadline=time.monotonic() - 1
    )
    assert report["status"] == "UNKNOWN"
    assert called == []
