from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src.api import app
from src.application.chat_service import ChatDependencies, ChatService, TurnCancelled
from src.application.learning_closure_service import LearningClosureService
from src.application.learning_closure_truth import LearningClosureTruthService
from src.application.learning_outcome_commit import LearningOutcomeCommitService
from src.application.learning_review import LearningReviewService
from src.application.learning_source_evidence import EvidenceConvergenceResult
from src.application.policy_chat_service import (
    ExternalDataPolicyChatService,
    PolicyChatCommand,
)
from src.application.runtime_repository import get_chat_service
from src.domain.learning_truth import (
    ClaimRevision,
    EvidenceBinding,
    LearningGoal,
    LearningTopic,
    NextStep,
    SourceEvidence,
    UnderstandingClaimResult,
    UnderstandingEvidence,
)
from src.mode_manager import RuntimeModes
from src.domain.runtime_entities import ChatTurn
from src.pedagogy.evaluation import SemanticEvaluation
from src.repositories.learning_closure_repository import LearningClosureRepository
from src.repositories.learning_truth_repository import LearningTruthRepository
from src.repositories.pedagogy_eval_repository import PedagogyEvalRepository
from src.task_contract import (
    TaskAwarePedagogyEngine,
    TaskAwarePedagogyEvaluationService,
)
from src.tools.web_agent import WebToolTrace

CLAIM = "二分查找每轮把候选范围减半，所以复杂度是对数级。"
ANSWER = "因为每一步都排除一半候选，所以重复减半直到一个位置；规模从16到8到4到2到1，查询次数随对数增长。"


class Semantic:
    def __init__(self):
        self.decision = "accept"
        self.calls = []

    def evaluate(self, **kwargs):
        self.calls.append(kwargs)
        if self.decision == "unavailable":
            raise RuntimeError("controlled provider failure")
        return SemanticEvaluation(
            claims=("unrelated claim",) if self.decision == "wrong_claim" else (CLAIM,),
            misconceptions=("controlled contradiction",)
            if self.decision == "reject"
            else (),
            reasoning_complete=True,
            transfer_ready=True,
            confidence=0.95,
            evidence_refs=kwargs["evidence"],
        )


class Forbidden:
    def __getattr__(self, name):
        raise AssertionError("Unexpected memory/source call: " + name)


@pytest.fixture(
    params=[ChatService, ExternalDataPolicyChatService], ids=["base", "production"]
)
def harness(request, runtime_test_context):
    context = runtime_test_context
    runtime = context.repository
    truth = LearningTruthRepository(runtime.database)
    session = context.session_service.create_session({})
    topic = truth.create_topic(LearningTopic(title="review"))
    goal, _ = truth.create_goal_for_thread(
        LearningGoal(topic_id=topic.id, objective="Explain binary search"),
        thread_id=session.id,
        focus_pinned=True,
    )
    source = SourceEvidence(
        id="review-source",
        repository="2002yy/study-agent",
        commit_sha="a" * 40,
        tree_sha="b" * 40,
        path="src/review.py",
        file_sha="source-file",
        symbol="search",
        symbol_kind="function",
        start_line=1,
        end_line=4,
    )
    result = LearningOutcomeCommitService(truth).commit(
        topic_id=topic.id,
        goal_id=goal.id,
        claim_text=CLAIM,
        claim_kind="mechanism",
        convergence=EvidenceConvergenceResult(
            primary=EvidenceBinding(source, "primary", 0), candidate_count=1
        ),
    )
    revision = result.revision.revision
    old = UnderstandingEvidence(verified_at="2000-01-01T00:00:00+00:00")
    truth.create_understanding_evidence(
        old, (UnderstandingClaimResult(old.id, revision.id, "pass"),)
    )
    truth.create_next_step(
        NextStep(goal_id=goal.id, text="Original next step", is_primary=True)
    )
    semantic = Semantic()
    deps = ChatDependencies(
        load_runtime_modes=lambda: RuntimeModes(
            memory_mode="confirm", performance_mode="fast"
        ),
        read_memory_bundle=lambda _: {},
        build_role_prompt=lambda *args, **kwargs: "Review feedback",
        route_request=lambda **kwargs: {
            "role": "nahida",
            "mode": "费曼",
            "model_profile": "flash",
            "reason": "test",
        },
        retrieve_local_knowledge=lambda *args, **kwargs: SimpleNamespace(
            to_dict=lambda: {"status": "skipped", "context": "", "results": []}
        ),
        build_messages=lambda **kwargs: [
            {"role": "user", "content": kwargs["user_input"]}
        ],
        chat=lambda *args, **kwargs: "请说明一个适用条件。",
        stream_chat=lambda *args, **kwargs: iter(("请说明一个适用条件。",)),
        chat_max_tokens=lambda _: 1000,
        resolve_web_tools=lambda *args, **kwargs: WebToolTrace(enabled=False),
        pedagogy_engine=TaskAwarePedagogyEngine(),
        pedagogy_evaluation=TaskAwarePedagogyEvaluationService(semantic),
    )
    chat = request.param(runtime, deps)
    evaluations = PedagogyEvalRepository(runtime.database)
    committer = LearningClosureTruthService(truth, Forbidden(), evaluations)
    closures = LearningClosureService(
        LearningClosureRepository(runtime.database),
        context.session_service,
        Forbidden(),
        evaluation_repository=evaluations,
        learning_truth_committer=committer,
        generator=lambda *args, **kwargs: pytest.fail(
            "Review called summary generator"
        ),
        memory_bundle_loader=lambda _: {},
    )
    return SimpleNamespace(
        chat=chat,
        runtime=runtime,
        truth=truth,
        session=session,
        goal=goal,
        revision=revision,
        semantic=semantic,
        closures=closures,
        committer=committer,
        evaluations=evaluations,
    )


def prompt(h, suffix="1"):
    return h.chat.start_review_prompt(
        h.session.id,
        h.revision.id,
        turn_id="review-prompt-" + suffix,
        operation_id="review-op-" + suffix,
    )


def answer(h, prompt_turn, **kwargs):
    command = PolicyChatCommand(
        user_input=ANSWER,
        thread_id=h.session.id,
        review_prompt_turn_id=prompt_turn.id,
        web_policy="off",
        memory_policy="auto",
        cloud_context_policy="allow_local_evidence",
        **kwargs,
    )
    prepared = h.chat.start_turn(command)
    return h.chat.complete_turn(prepared, "请说明一个适用条件。")


def test_real_review_roundtrip_and_same_attempt_replay(harness):
    h = harness
    navigation = h.truth.list_next_steps_for_goal(h.goal.id)
    legacy = h.runtime.get_chat_thread(h.session.id).learning_state
    p = prompt(h)
    assert prompt(h).id == p.id
    a = answer(h, p)
    assert h.runtime.get_chat_thread(h.session.id).learning_state == legacy
    assert len(h.truth.list_understanding_for_revision(h.revision.id)) == 1
    run = h.closures.create_and_execute(h.session.id)
    assert run.status == "preview_ready" and run.memory_run_id is None
    assert (
        run.committed_snapshot["structured_input"]["review_attempt"]["answer_turn_id"]
        == a.id
    )
    assert len(h.truth.list_understanding_for_revision(h.revision.id)) == 1
    completed = h.closures.commit(run.id)
    assert completed.status == "completed", completed.error
    assert h.closures.commit(run.id).status == "completed"
    assert len(h.truth.list_understanding_for_revision(h.revision.id)) == 2
    assert not LearningReviewService(h.truth).build(h.session.id).items[0].due
    assert h.truth.get_goal(h.goal.id) == h.goal
    assert h.truth.list_next_steps_for_goal(h.goal.id) == navigation
    assert h.semantic.calls[-1]["objective"] == h.goal.objective
    assert h.semantic.calls[-1]["expected_concepts"] == (CLAIM,)
    assert len(h.truth.list_revisions(h.revision.claim_id)) == 1


@pytest.mark.parametrize(
    "decision,expected", [("reject", "fail"), ("unavailable", "partial")]
)
def test_failed_or_unavailable_review_records_attempt_without_resetting_due(
    harness, decision, expected
):
    h = harness
    h.semantic.decision = decision
    answer(h, prompt(h))
    run = h.closures.create_and_execute(h.session.id)
    completed = h.closures.commit(run.id)
    assert completed.status == "completed", completed.error
    pairs = h.truth.list_understanding_for_revision(h.revision.id)
    assert len(pairs) == 2 and pairs[-1][1].result == expected
    assert LearningReviewService(h.truth).build(h.session.id).items[0].due
    assert h.truth.get_goal(h.goal.id) == h.goal


def test_preview_prompt_and_ordinary_chat_never_write_understanding(harness):
    h = harness
    LearningReviewService(h.truth).preview_prompt(h.session.id, h.revision.id)
    prompt(h)
    prepared = h.chat.start_turn(
        PolicyChatCommand(
            user_input=ANSWER,
            thread_id=h.session.id,
            web_policy="off",
            memory_policy="auto",
        )
    )
    h.chat.complete_turn(prepared, "Feedback")
    assert "review" not in prepared.route
    assert len(h.truth.list_understanding_for_revision(h.revision.id)) == 1


def test_fresh_pass_between_answer_and_commit_fails_cas(harness):
    h = harness
    answer(h, prompt(h))
    run = h.closures.create_and_execute(h.session.id)
    fresh = UnderstandingEvidence()
    h.truth.create_understanding_evidence(
        fresh, (UnderstandingClaimResult(fresh.id, h.revision.id, "pass"),)
    )
    failed = h.closures.commit(run.id)
    assert failed.status == "failed" and "last pass changed" in failed.error
    assert len(h.truth.list_understanding_for_revision(h.revision.id)) == 2


def test_wrong_claim_accept_is_not_attached_to_review_target(harness):
    h = harness
    h.semantic.decision = "wrong_claim"
    answer(h, prompt(h))
    run = h.closures.create_and_execute(h.session.id)
    failed = h.closures.commit(run.id)
    assert failed.status == "failed" and "different claim" in failed.error
    assert len(h.truth.list_understanding_for_revision(h.revision.id)) == 1


def test_foreign_thread_and_retry_rebinding_are_rejected(harness):
    h = harness
    p = prompt(h)
    with pytest.raises(ValueError, match="this thread"):
        h.chat.start_turn(
            PolicyChatCommand(
                user_input=ANSWER, thread_id="foreign", review_prompt_turn_id=p.id
            )
        )
    prepared = h.chat.start_turn(
        PolicyChatCommand(
            user_input=ANSWER,
            thread_id=h.session.id,
            review_prompt_turn_id=p.id,
            web_policy="off",
        )
    )
    h.chat.interrupt_turn(prepared, "Partial")
    with pytest.raises(ValueError, match="switch review"):
        h.chat.start_turn(
            PolicyChatCommand(
                user_input=ANSWER,
                continuation_of_turn_id=prepared.turn.id,
                review_prompt_turn_id="different",
            )
        )
    with pytest.raises(ValueError, match="switch review"):
        h.chat.start_turn(
            PolicyChatCommand(
                user_input=ANSWER,
                retry_of_turn_id=prepared.turn.id,
                review_prompt_turn_id="different",
            )
        )
    assert len(h.truth.list_understanding_for_revision(h.revision.id)) == 1


def test_start_and_answer_http_flow(harness, runtime_test_context):
    h = harness
    app.dependency_overrides[get_chat_service] = lambda: h.chat
    try:
        client = TestClient(app)
        response = client.post(
            f"/sessions/{h.session.id}/reviews/{h.revision.id}/start",
            json={"turn_id": "http-prompt", "operation_id": "http-op"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "completed"
        response = client.post(
            "/chat",
            json={
                "session_id": h.session.id,
                "user_input": ANSWER,
                "review_prompt_turn_id": "http-prompt",
                "web_policy": "off",
                "cloud_context_policy": "allow_local_evidence",
            },
        )
        assert response.status_code == 200, response.text
        turn = h.runtime.get_chat_turn(response.json()["turn_id"])
        assert turn.route_snapshot["review"]["phase"] == "answer"
        assert len(h.truth.list_understanding_for_revision(h.revision.id)) == 1
    finally:
        app.dependency_overrides.pop(get_chat_service, None)


def test_new_attempt_with_identical_words_is_not_content_deduplicated(harness):
    h = harness
    h.semantic.decision = "reject"
    first_answer = answer(h, prompt(h, "first"))
    first_run = h.closures.create_and_execute(h.session.id)
    assert h.closures.commit(first_run.id).status == "completed"
    h.semantic.decision = "accept"
    second_answer = answer(h, prompt(h, "second"))
    second_run = h.closures.create_and_execute(h.session.id)
    completed = h.closures.commit(second_run.id)
    assert completed.status == "completed", completed.error
    assert first_answer.user_message == second_answer.user_message
    pairs = h.truth.list_understanding_for_revision(h.revision.id)
    assert len(pairs) == 3
    assert pairs[-2][0].id != pairs[-1][0].id
    assert pairs[-2][1].result == "fail" and pairs[-1][1].result == "pass"
    assert not LearningReviewService(h.truth).build(h.session.id).items[0].due


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("revision", "revision changed"),
        ("goal", "goal changed"),
        ("source", "source changed"),
        ("evaluation", "response mismatch"),
    ],
)
def test_transaction_rechecks_freshness_and_ownership(harness, mutation, reason):
    h = harness
    a = answer(h, prompt(h))
    run = h.closures.create_and_execute(h.session.id)
    if mutation == "revision":
        h.truth.commit_revision(
            ClaimRevision(
                claim_id=h.revision.claim_id,
                claim_text="Changed claim",
                source_commit="a" * 40,
                reason="meaning_changed",
            ),
            h.truth.get_revision(h.revision.id).evidence,
            goal_id=h.goal.id,
        )
    elif mutation == "goal":
        other, _ = h.truth.create_goal_for_thread(
            LearningGoal(topic_id=h.goal.topic_id, objective="Different objective"),
            thread_id=h.session.id,
            focus_pinned=True,
        )
        h.truth.focus_goal(other.id, pinned=True)
    elif mutation == "source":
        h.runtime.add_chat_turn(
            ChatTurn(
                thread_id=h.session.id,
                user_message="Later source",
                assistant_message="Later",
                status="completed",
            )
        )
    else:
        with h.runtime.database.connect() as connection:
            connection.execute(
                "UPDATE pedagogy_eval_runs SET learner_input = 'wrong response' WHERE turn_id = ?",
                (a.id,),
            )
    failed = h.closures.commit(run.id)
    assert failed.status == "failed", failed
    assert reason in failed.error, failed.error
    assert len(h.truth.list_understanding_for_revision(h.revision.id)) == 1


@pytest.mark.parametrize(
    "after_commit", [False, True], ids=["before-commit", "after-commit"]
)
def test_crash_retry_writes_at_most_one_attempt(harness, monkeypatch, after_commit):
    h = harness
    answer(h, prompt(h))
    run = h.closures.create_and_execute(h.session.id)
    name = "commit_review_attempt" if after_commit else "_insert_understanding"
    original = getattr(h.truth, name)

    def crash(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("controlled commit crash")

    monkeypatch.setattr(h.truth, name, crash)
    failed = h.closures.commit(run.id)
    assert failed.status == "failed" and "controlled commit crash" in failed.error
    assert len(h.truth.list_understanding_for_revision(h.revision.id)) == (
        2 if after_commit else 1
    )
    monkeypatch.setattr(h.truth, name, original)
    assert h.closures.retry(run.id).status == "preview_ready"
    completed = h.closures.commit(run.id)
    assert completed.status == "completed", completed.error
    assert len(h.truth.list_understanding_for_revision(h.revision.id)) == 2


def test_cancelled_answer_and_prompt_only_are_not_validation(harness):
    h = harness
    p = prompt(h)
    prepared = h.chat.start_turn(
        PolicyChatCommand(
            user_input=ANSWER,
            thread_id=h.session.id,
            review_prompt_turn_id=p.id,
            web_policy="off",
        )
    )
    outcome, _ = h.runtime.request_turn_cancel(
        prepared.turn.id, expected_operation_id=prepared.turn.operation_id
    )
    assert outcome == "accepted"
    h.chat.finish_cancelled_turn(prepared, "partial")
    with pytest.raises(ValueError, match="phase mismatch"):
        h.closures.create_and_execute(h.session.id)
    assert len(h.truth.list_understanding_for_revision(h.revision.id)) == 1


def test_prompt_cancellation_uses_existing_lifecycle(harness, monkeypatch):
    h = harness

    def cancel_check(turn_id, operation_id):
        def cancel(stage):
            h.runtime.request_turn_cancel(turn_id, expected_operation_id=operation_id)
            raise TurnCancelled(stage=stage, turn_id=turn_id, operation_id=operation_id)

        return cancel

    monkeypatch.setattr(h.chat, "_make_cancel_check", cancel_check)
    with pytest.raises(TurnCancelled):
        prompt(h)
    assert h.runtime.get_chat_turn("review-prompt-1").status == "cancelled"
    assert h.runtime.get_chat_thread(h.session.id).active_operation_id is None
    assert len(h.truth.list_understanding_for_revision(h.revision.id)) == 1


def test_full_binding_survives_dialogue_budget(harness):
    from src.application.closure_input_builder import build_structured_closure_input

    h = harness
    p = prompt(h)
    a = answer(h, p)
    turns = h.runtime.list_chat_turns(h.session.id)
    snapshot = build_structured_closure_input(
        thread_id=h.session.id,
        closure_eligibility="learning_summary",
        task_contract={},
        learning_state={},
        all_turns=turns,
        completed_turns=turns,
        evaluation_repository=h.evaluations,
        recent_turn_limit=1,
        message_char_limit=200,
    )
    assert [item["turn_id"] for item in snapshot["recent_dialogue"]] == [a.id]
    assert snapshot["review_attempt"]["binding"]["question"] == p.assistant_message


def test_blocked_goal_remains_blocked_after_successful_review(harness):
    h = harness
    blocked = h.truth.update_goal_status(h.goal.id, "blocked")
    answer(h, prompt(h))
    run = h.closures.create_and_execute(h.session.id)
    completed = h.closures.commit(run.id)
    assert completed.status == "completed", completed.error
    assert h.truth.get_goal(h.goal.id) == blocked


def test_fresh_pass_invalidates_prompt_before_answer(harness):
    h = harness
    p = prompt(h)
    evidence = UnderstandingEvidence(
        method="explain", prompt="another attempt", user_response=ANSWER
    )
    h.truth.create_understanding_evidence(
        evidence, (UnderstandingClaimResult(evidence.id, h.revision.id, "pass"),)
    )
    with pytest.raises(ValueError):
        answer(h, p)
    assert len(h.runtime.list_chat_turns(h.session.id)) == 1
    assert h.runtime.get_chat_thread(h.session.id).active_operation_id is None


@pytest.mark.parametrize("mutation", ["cancel", "digest", "evaluation"])
def test_atomic_guard_rejects_changed_frozen_authority(harness, monkeypatch, mutation):
    h = harness
    a = answer(h, prompt(h))
    run = h.closures.create_and_execute(h.session.id)
    original = h.committer.commit

    def tamper(committing):
        with h.runtime.database.connect() as connection:
            if mutation == "cancel":
                connection.execute(
                    "UPDATE learning_closure_runs SET cancel_requested_at = '2026-10-03' WHERE id = ?",
                    (run.id,),
                )
            elif mutation == "digest":
                connection.execute(
                    "UPDATE learning_closure_runs SET source_hash = 'wrong' WHERE id = ?",
                    (run.id,),
                )
            else:
                connection.execute(
                    "UPDATE pedagogy_eval_runs SET objective = 'wrong' WHERE turn_id = ?",
                    (a.id,),
                )
        return original(committing)

    monkeypatch.setattr(h.committer, "commit", tamper)
    result = h.closures.commit(run.id)
    assert result.status != "completed"
    assert len(h.truth.list_understanding_for_revision(h.revision.id)) == 1


def test_same_attempt_key_with_different_payload_is_rejected(harness, monkeypatch):
    h = harness
    answer(h, prompt(h))
    run = h.closures.create_and_execute(h.session.id)
    original = h.truth.commit_review_attempt

    def crash(**kwargs):
        original(**kwargs)
        raise RuntimeError("after commit crash")

    monkeypatch.setattr(h.truth, "commit_review_attempt", crash)
    assert h.closures.commit(run.id).status == "failed"
    committed_id = h.truth.list_understanding_for_revision(h.revision.id)[-1][0].id
    with h.runtime.database.connect() as connection:
        connection.execute(
            "UPDATE understanding_evidence SET user_response = 'different payload' WHERE id = ?",
            (committed_id,),
        )
    monkeypatch.setattr(h.truth, "commit_review_attempt", original)
    assert h.closures.retry(run.id).status == "preview_ready"
    failed = h.closures.commit(run.id)
    assert failed.status == "failed" and "payload conflict" in failed.error
    assert len(h.truth.list_understanding_for_revision(h.revision.id)) == 2
