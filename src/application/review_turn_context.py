"""Shared read-only review resolution for both chat preparation seams."""

from dataclasses import replace
from typing import Protocol

from src.application.learning_review import LearningReviewService, ReviewUnavailable
from src.domain.review_turn import ReviewTurnBinding, read_review_snapshot, review_time
from src.pedagogy.types import LearningState
from src.repositories.learning_truth_repository import LearningTruthRepository
from src.repositories.runtime_repository import RuntimeRepository
from src.domain.runtime_entities import ChatTurn


class ReviewAnswerCommand(Protocol):
    @property
    def review_prompt_turn_id(self) -> str | None: ...

    @property
    def thread_id(self) -> str | None: ...


def require_current_review(
    truth: LearningTruthRepository, binding: ReviewTurnBinding
) -> None:
    goal = truth.get_focus_goal(binding.thread_id)
    if (
        goal is None
        or goal.id != binding.goal_id
        or goal.objective != binding.objective
    ):
        raise ValueError("Review goal changed")
    try:
        preview = LearningReviewService(truth).preview_prompt(
            binding.thread_id, binding.claim_revision_id
        )
    except ReviewUnavailable as exc:
        raise ValueError("Review revision changed or unavailable") from exc
    if review_time(preview.last_validated_at) != review_time(binding.last_validated_at):
        raise ValueError("Review validation changed")
    revision = truth.get_revision(binding.claim_revision_id)
    if revision is None or revision.revision.claim_text != binding.claim_text:
        raise ValueError("Review revision changed")
    if tuple(item.source.id for item in revision.evidence) != binding.evidence_ids:
        raise ValueError("Review source binding changed")


def resolve_review_answer(
    repository: RuntimeRepository,
    command: ReviewAnswerCommand,
    persisted_turn: ChatTurn | None = None,
) -> ReviewTurnBinding | None:
    bound = None
    requested = command.review_prompt_turn_id
    if persisted_turn is not None:
        raw = persisted_turn.route_snapshot.get("review")
        if raw is None:
            if requested:
                raise ValueError("Retry/continuation cannot add review binding")
            return None
        bound = read_review_snapshot(raw, phase="answer")
        if requested and requested != bound.prompt_turn_id:
            raise ValueError("Retry/continuation cannot switch review binding")
        requested = bound.prompt_turn_id
    if not requested:
        return None
    prompt = repository.get_chat_turn(requested)
    if (
        prompt is None
        or prompt.status != "completed"
        or prompt.thread_id != command.thread_id
    ):
        raise ValueError("Review prompt is not a completed turn in this thread")
    binding = read_review_snapshot(prompt.route_snapshot.get("review"), phase="prompt")
    if binding.prompt_turn_id != prompt.id or binding.thread_id != prompt.thread_id:
        raise ValueError("Review prompt ownership mismatch")
    if (
        binding.question != prompt.assistant_message
        or prompt.cancel_requested_at is not None
    ):
        raise ValueError("Review prompt content mismatch")
    if persisted_turn is not None and binding != bound:
        raise ValueError("Persisted review binding changed")
    require_current_review(LearningTruthRepository(repository.database), binding)
    return binding


def review_evaluation_inputs(
    binding: ReviewTurnBinding | None,
    state: LearningState,
    expected: tuple[str, ...],
    evidence: tuple[str, ...],
) -> tuple[LearningState, tuple[str, ...], tuple[str, ...]]:
    if binding is None:
        return state, expected, evidence
    return (
        replace(state, objective=binding.objective, protocol="feynman_diagnosis"),
        (binding.claim_text,),
        binding.evidence_ids,
    )
