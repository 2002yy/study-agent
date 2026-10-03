"""Production semantic-write orchestration for P2-D durable learning truth.

Ordinary chat turns never call this service. It is invoked only from the explicit
LearningClosure commit boundary after the source ChatThread is verified current.
Generated closure output is treated as candidate input: trusted GitHub source
identity is reloaded from the committed closure snapshot and evidence convergence
runs again before any Claim/Hypothesis write.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from src.application.learning_outcome_commit import (
    LearningOutcomeCommitResult,
    LearningOutcomeCommitService,
)
from src.application.learning_semantic_closure import LearningSemanticClosureService
from src.application.learning_semantic_closure import _map_evaluation_result
from src.application.learning_source_evidence import (
    EvidenceConvergenceResult,
    LearningSourceEvidenceService,
)
from src.domain.learning_closure import LearningClosureRun
from src.domain.review_turn import ReviewTurnBinding
from src.domain.runtime_entities import utc_now
from src.domain.learning_truth import (
    LearnerMisconception,
    ClaimRevisionBundle,
    LearningGoal,
    LearningTopic,
    NextStep,
    SourceEvidence,
    UnderstandingEvidence,
)
from src.pedagogy.evaluation import PedagogyEvalRun
from src.repositories.learning_truth_repository import LearningTruthRepository
from src.repositories.pedagogy_eval_repository import PedagogyEvalRepository

_VALIDATION_MOVES = {
    "elicit_claim": "explain",
    "invite_explanation": "explain",
    "request_reexplanation": "explain",
    "request_prediction": "apply",
    "transfer": "apply",
    "transfer_test": "apply",
    "test_example": "practice",
}


@dataclass(frozen=True)
class LearningClosureTruthResult:
    status: str
    goal_id: str = ""
    claim_revision_id: str = ""
    hypothesis_id: str = ""
    understanding_id: str = ""
    validation_status: str = ""


class LearningClosureTruthService:
    """Commit one frozen semantic-closure candidate into durable learning truth."""

    def __init__(
        self,
        repository: LearningTruthRepository,
        source_evidence: LearningSourceEvidenceService,
        evaluation_repository: PedagogyEvalRepository,
    ) -> None:
        self.repository = repository
        self.source_evidence = source_evidence
        self.evaluation_repository = evaluation_repository
        self.outcomes = LearningOutcomeCommitService(repository)
        self.semantic_closure = LearningSemanticClosureService(repository)

    def commit(self, run: LearningClosureRun) -> LearningClosureTruthResult:
        if run.closure_eligibility != "learning_summary":
            return LearningClosureTruthResult(status="not_learning_closure")
        structured_input = _structured_input(run)
        if "review_attempt" in structured_input:
            return self._commit_review(run, structured_input)

        candidate = _candidate(run.generated_result)
        if candidate is None:
            return LearningClosureTruthResult(status="no_candidate")
        structured_input = _structured_input(run)
        source = _source_for_candidate(structured_input, candidate)
        if source is None:
            return LearningClosureTruthResult(status="candidate_source_missing")

        evaluation = self._evaluation(candidate, structured_input)
        if evaluation is None:
            return LearningClosureTruthResult(status="evaluation_missing")
        if evaluation.final_decision != "accept":
            return LearningClosureTruthResult(status="validation_not_accepted")
        if not _claim_owned_by_evaluation(candidate["claim_text"], evaluation):
            return LearningClosureTruthResult(status="candidate_claim_mismatch")

        objective = _objective(evaluation, structured_input, source)
        topic, goal = self._focus_or_create_goal(
            run,
            objective=objective,
            repo_url=source["repo_url"],
        )

        # 168: observations become suspected durable misconceptions; never auto-confirmed.
        self._promote_misconceptions(goal.id, evaluation)

        convergence = self.source_evidence.search_and_converge(
            source["repo_url"],
            source["query"],
            ref=source["commit_sha"],
        )
        outcome = self._commit_or_reuse_outcome(
            topic_id=topic.id,
            goal_id=goal.id,
            candidate=candidate,
            convergence=convergence,
        )
        if outcome.hypothesis is not None:
            self._ensure_primary_next_step(
                goal.id,
                candidate.get("next_step")
                or "重新获取可靠源码证据后，再验证这个假设。",
            )
            return LearningClosureTruthResult(
                status="hypothesis",
                goal_id=goal.id,
                hypothesis_id=outcome.hypothesis.id,
            )

        if outcome.revision is None:
            return LearningClosureTruthResult(status="no_outcome", goal_id=goal.id)

        revision = outcome.revision.revision
        validation = _validation_context(structured_input, candidate, evaluation)
        if validation is None:
            self._ensure_primary_next_step(goal.id, candidate.get("next_step") or "")
            return LearningClosureTruthResult(
                status="claim_unverified",
                goal_id=goal.id,
                claim_revision_id=revision.id,
            )

        method, prompt = validation
        existing_understanding = self._matching_understanding(
            revision.id,
            method=method,
            prompt=prompt,
            user_response=evaluation.learner_input,
        )
        if existing_understanding is not None:
            stored, result = existing_understanding
            return LearningClosureTruthResult(
                status="claim_validated",
                goal_id=goal.id,
                claim_revision_id=revision.id,
                understanding_id=stored.id,
                validation_status=result,
            )

        next_step_text = ""
        if not self._active_primary_next_step(goal.id):
            next_step_text = candidate.get("next_step") or _default_next_step()
        closure = self.semantic_closure.close(
            goal_id=goal.id,
            target_revision_ids=(revision.id,),
            method=method,
            prompt=prompt,
            evaluation_run=evaluation,
            # Confirming one Claim is not the same action as completing the whole Goal.
            # Goal completion remains an explicit semantic/user action.
            goal_status="active",
            next_step_text=next_step_text,
        )
        return LearningClosureTruthResult(
            status="claim_validated",
            goal_id=goal.id,
            claim_revision_id=revision.id,
            understanding_id=closure.understanding.id if closure.understanding else "",
            validation_status=closure.validation_status,
        )

    def _commit_review(self, run, structured_input) -> LearningClosureTruthResult:
        attempt = structured_input["review_attempt"]
        if not isinstance(attempt, dict) or set(attempt) != {"binding", "answer_turn_id", "evaluation_id"}:
            raise ValueError("Invalid frozen review attempt")
        binding = ReviewTurnBinding.from_dict(attempt["binding"])
        if attempt["answer_turn_id"] != run.last_completed_turn_id:
            raise ValueError("Review answer source mismatch")
        evaluation = self.evaluation_repository.get_for_turn(run.last_completed_turn_id)
        if evaluation is None or evaluation.id != attempt["evaluation_id"]:
            raise ValueError("Review evaluation missing/mismatched")
        if evaluation.final_decision == "accept" and not _claim_owned_by_evaluation(binding.claim_text, evaluation):
            raise ValueError("Review accepted a different claim")
        result = _map_evaluation_result(evaluation)
        understanding = UnderstandingEvidence(
            id=_stable_id("understanding_review", run.id, run.last_completed_turn_id, evaluation.id),
            method=binding.method, prompt=binding.question, user_response=evaluation.learner_input,
        )
        stored = self.repository.commit_review_attempt(
            run=run, binding=binding, evaluation=evaluation, understanding=understanding, result=result,
        )
        return LearningClosureTruthResult(
            status="review_" + result, goal_id=binding.goal_id,
            claim_revision_id=binding.claim_revision_id, understanding_id=stored.id,
            validation_status=result,
        )

    def _evaluation(
        self,
        candidate: dict[str, str],
        structured_input: dict[str, Any],
    ) -> PedagogyEvalRun | None:
        turn_id = candidate.get("evaluation_turn_id", "")
        expected_id = candidate.get("evaluation_id", "")
        if not turn_id or not expected_id:
            return None
        run = self.evaluation_repository.get_for_turn(turn_id)
        if run is None or run.id != expected_id:
            return None
        frozen = structured_input.get("final_pedagogy_evaluation")
        if not isinstance(frozen, dict) or str(frozen.get("id") or "") != run.id:
            return None
        return run

    def _focus_or_create_goal(
        self,
        run: LearningClosureRun,
        *,
        objective: str,
        repo_url: str,
    ) -> tuple[LearningTopic, LearningGoal]:
        normalized_objective = _normalize(objective)

        # Reuse only the same semantic objective. A new topic/objective may become
        # the current focus, but the previous active Goal remains durable and can
        # be focused again later rather than receiving unrelated Claims.
        for existing in self.repository.list_goals_for_thread(run.thread_id):
            if (
                existing.status in {"active", "blocked"}
                and _normalize(existing.objective) == normalized_objective
            ):
                topic = self.repository.get_topic(existing.topic_id)
                if topic is None:
                    raise ValueError(f"Learning topic not found: {existing.topic_id}")
                self.repository.focus_goal(existing.id)
                return topic, existing

        topic_id = _stable_id("topic", run.thread_id, repo_url)
        topic = self.repository.get_topic(topic_id)
        if topic is None:
            topic = self.repository.create_topic(
                LearningTopic(
                    id=topic_id,
                    title=_topic_title(repo_url, objective),
                    scope="project",
                )
            )

        goal_id = _stable_id("goal", run.id, objective)
        existing_goal = self.repository.get_goal(goal_id)
        if existing_goal is not None:
            if existing_goal.status in {"active", "blocked"}:
                self.repository.focus_goal(existing_goal.id)
            return topic, existing_goal
        goal, _context = self.repository.create_goal_for_thread(
            LearningGoal(
                id=goal_id,
                topic_id=topic.id,
                objective=objective,
                status="active",
            ),
            thread_id=run.thread_id,
            focus_pinned=False,
        )
        return topic, goal

    def _commit_or_reuse_outcome(
        self,
        *,
        topic_id: str,
        goal_id: str,
        candidate: dict[str, str],
        convergence: EvidenceConvergenceResult,
    ) -> LearningOutcomeCommitResult:
        claim_text = candidate["claim_text"]
        if not convergence.claim_ready or convergence.primary is None:
            reason = convergence.unresolved_reason or "insufficient_evidence"
            for hypothesis in self.repository.list_hypotheses_for_goal(goal_id):
                if (
                    hypothesis.resolved_by_claim_id is None
                    and _normalize(hypothesis.text) == _normalize(claim_text)
                    and hypothesis.unresolved_reason == reason
                ):
                    return LearningOutcomeCommitResult(
                        outcome="hypothesis",
                        hypothesis=hypothesis,
                    )
            return self.outcomes.commit(
                topic_id=topic_id,
                goal_id=goal_id,
                claim_text=claim_text,
                claim_kind=candidate["claim_kind"],
                scope=candidate["scope"],
                convergence=convergence,
            )

        matching = self._matching_revision(
            goal_id,
            claim_text=claim_text,
            claim_kind=candidate["claim_kind"],
            scope=candidate["scope"],
            convergence=convergence,
        )
        if matching is not None:
            claim = self.repository.get_claim(matching.revision.claim_id)
            if claim is None:
                raise ValueError(f"Learning claim not found: {matching.revision.claim_id}")
            return LearningOutcomeCommitResult(
                outcome="claim",
                claim=claim,
                revision=matching,
            )
        return self.outcomes.commit(
            topic_id=topic_id,
            goal_id=goal_id,
            claim_text=claim_text,
            claim_kind=candidate["claim_kind"],
            scope=candidate["scope"],
            convergence=convergence,
        )

    def _matching_revision(
        self,
        goal_id: str,
        *,
        claim_text: str,
        claim_kind: str,
        scope: str,
        convergence: EvidenceConvergenceResult,
    ) -> ClaimRevisionBundle | None:
        assert convergence.primary is not None
        expected_primary = _source_identity(convergence.primary.source)
        for bundle in reversed(self.repository.list_goal_revisions(goal_id)):
            if _normalize(bundle.revision.claim_text) != _normalize(claim_text):
                continue
            claim = self.repository.get_claim(bundle.revision.claim_id)
            if claim is None or claim.claim_kind != claim_kind or claim.scope != scope:
                continue
            primary = next(
                (item for item in bundle.evidence if item.role == "primary"),
                None,
            )
            if primary is not None and _source_identity(primary.source) == expected_primary:
                return bundle
        return None

    def _matching_understanding(
        self,
        revision_id: str,
        *,
        method: str,
        prompt: str,
        user_response: str,
    ) -> tuple[UnderstandingEvidence, str] | None:
        for evidence, result in self.repository.list_understanding_for_revision(revision_id):
            if (
                evidence.method == method
                and _normalize(evidence.prompt) == _normalize(prompt)
                and _normalize(evidence.user_response) == _normalize(user_response)
            ):
                return evidence, result.result
        return None

    def _active_primary_next_step(self, goal_id: str) -> NextStep | None:
        return next(
            (
                item
                for item in self.repository.list_next_steps_for_goal(goal_id)
                if item.status == "active" and item.is_primary
            ),
            None,
        )

    def _promote_misconceptions(
        self, goal_id: str, evaluation: PedagogyEvalRun
    ) -> None:
        """168.2: first sighting -> suspected; repeat -> count+1; NEVER auto-confirm."""
        descriptions: list[str] = []
        if evaluation.semantic_result is not None:
            descriptions.extend(
                str(item) for item in evaluation.semantic_result.misconceptions
            )
        raw = evaluation.deterministic_result.get("misconceptions", ())
        if isinstance(raw, (list, tuple)):
            descriptions.extend(str(item) for item in raw)
        seen: set[str] = set()
        for description in descriptions:
            text = description.strip()
            if not text or text.lower() in seen:
                continue
            seen.add(text.lower())
            existing = self.repository.find_misconception_by_description(
                goal_id, text
            )
            if existing is None:
                self.repository.create_misconception(
                    LearnerMisconception(
                        goal_id=goal_id,
                        description=text,
                        status="suspected",
                        occurrence_count=1,
                        source_eval_ref=evaluation.id,
                    )
                )
            else:
                # Repeat observation raises the count but never confirms.
                self.repository.update_misconception(
                    LearnerMisconception(
                        id=existing.id,
                        goal_id=goal_id,
                        description=existing.description,
                        status=existing.status,
                        occurrence_count=existing.occurrence_count + 1,
                        source_eval_ref=existing.source_eval_ref,
                        first_seen_at=existing.first_seen_at,
                        last_seen_at=utc_now(),
                    )
                )

    def _ensure_primary_next_step(self, goal_id: str, text: str) -> NextStep | None:
        existing = self._active_primary_next_step(goal_id)
        if existing is not None or not text.strip():
            return existing
        goal = self.repository.get_goal(goal_id)
        if goal is None or goal.status in {"completed", "abandoned"}:
            return None
        return self.repository.create_next_step(
            NextStep(goal_id=goal_id, text=text.strip(), is_primary=True)
        )


def _candidate(generated_result: dict[str, Any]) -> dict[str, str] | None:
    raw = generated_result.get("durable_learning_candidate")
    if not isinstance(raw, dict):
        return None
    required = ("source_ref", "claim_text", "claim_kind", "scope")
    candidate = {str(key): str(value or "").strip() for key, value in raw.items()}
    if any(not candidate.get(key) for key in required):
        return None
    return candidate


def _structured_input(run: LearningClosureRun) -> dict[str, Any]:
    value = run.committed_snapshot.get("structured_input")
    if not isinstance(value, dict):
        raise ValueError("Learning closure has no structured input snapshot")
    return value


def _source_for_candidate(
    structured_input: dict[str, Any],
    candidate: dict[str, str],
) -> dict[str, str] | None:
    source_ref = candidate.get("source_ref", "")
    for raw in structured_input.get("github_learning_sources", []):
        if not isinstance(raw, dict) or str(raw.get("source_ref") or "") != source_ref:
            continue
        source = {
            "source_ref": source_ref,
            "repo_url": str(raw.get("repo_url") or "").strip(),
            "query": str(raw.get("query") or "").strip(),
            "commit_sha": str(raw.get("commit_sha") or "").strip(),
        }
        if source["repo_url"] and source["query"] and source["commit_sha"]:
            return source
    return None


def _objective(
    evaluation: PedagogyEvalRun,
    structured_input: dict[str, Any],
    source: dict[str, str],
) -> str:
    if evaluation.objective.strip():
        return evaluation.objective.strip()
    committed = structured_input.get("committed_learning_state")
    if isinstance(committed, dict):
        objective = str(committed.get("objective") or "").strip()
        if objective:
            return objective
    return f"理解源码：{source['query']}"


def _validation_context(
    structured_input: dict[str, Any],
    candidate: dict[str, str],
    evaluation: PedagogyEvalRun,
) -> tuple[str, str] | None:
    turn_id = candidate.get("evaluation_turn_id", "")
    dialogue = structured_input.get("recent_dialogue")
    if not isinstance(dialogue, list):
        return None
    for index, item in enumerate(dialogue):
        if not isinstance(item, dict) or str(item.get("turn_id") or "") != turn_id:
            continue
        if index <= 0:
            return None
        previous = dialogue[index - 1]
        if not isinstance(previous, dict):
            return None
        method = _VALIDATION_MOVES.get(str(previous.get("pedagogy_move") or ""))
        prompt = str(previous.get("assistant_message") or "").strip()
        if not method or not prompt:
            return None
        return method, prompt[:1800]
    return None


def _default_next_step() -> str:
    return "围绕当前源码命题再做一次应用或迁移验证。"


def _claim_owned_by_evaluation(claim_text: str, evaluation: PedagogyEvalRun) -> bool:
    normalized = _normalize(claim_text)
    semantic = evaluation.semantic_result
    if semantic is not None and semantic.claims:
        return normalized in {_normalize(item) for item in semantic.claims if item.strip()}
    return bool(
        evaluation.deterministic_result.get("is_claim") is True
        and normalized == _normalize(evaluation.learner_input)
    )


def _topic_title(repo_url: str, objective: str) -> str:
    repository = repo_url.rstrip("/").split("/")[-1] or "源码学习"
    title = f"{repository} · {objective}".strip(" ·")
    return title[:240]


def _stable_id(prefix: str, *parts: str) -> str:
    material = "\u0000".join(str(part or "").strip() for part in parts)
    digest = sha256(material.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


def _normalize(value: str) -> str:
    return " ".join(str(value or "").split()).casefold()


def _source_identity(source: SourceEvidence) -> tuple[object, ...]:
    return (
        source.repository,
        source.commit_sha,
        source.tree_sha,
        source.path,
        source.file_sha,
        source.symbol,
        source.symbol_kind,
        source.start_line,
        source.end_line,
        source.evidence_kind,
    )
