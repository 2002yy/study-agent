"""CL-M3 M3-QA: the middle planning adapter.

Implements the frozen rulings in ``docs/CL_M3_CAPABILITY_CONTRACT.md``:

* §7.2 - a **middle adapter**, never a wrapper around the whole
  ``PersistentWebToolAgent.resolve()``. This module only produces query plans and hands
  observation state back to the outer loop; it never searches, never publishes and never
  grants evidence authority.
* §7.4 - one **fresh controlled session per planning round**. ``ResearchSemanticSession``
  refuses a second ``interpret()`` for the same stage, so re-planning a round by reusing a
  session is impossible by construction. Identity is derived from operation id + round index
  + stage, which is stable and deduplicable by the admission layer (M3-QC).
* §7.5 - ``episode_context()`` may drop ``attempts`` / ``source_leads`` when the payload hits
  ``CONTEXT_CAP``. A round therefore records whether observations actually reached the
  planner, and refuses to be described as "replanned from observation" when they did not.
* §7.6 - ``original_rq_removed`` is re-implemented here. Bypassing ``resolve()`` does not
  bypass the guarantee; it moves the obligation into this adapter.

This module deliberately contains no metering and no logging. Every real model call is made
by the session it is given, so M3-QC can meter it by wrapping the completion inside the
session factory - which is exactly why the factory is injectable.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Callable

from src.web.semantic_recovery import (
    ResearchDecision,
    ResearchEpisode,
    ResearchSemanticSession,
)

SESSION_STAGE = "research_turn_interpretation"
OBSERVATION_FIELDS = ("attempts", "source_leads")
NON_RESEARCH_INTENTS = frozenset({"ABSTAIN", "ANSWER"})


@dataclass(frozen=True)
class PlanningIdentity:
    """Stable identity for one planning round of one operation."""

    operation_id: str
    round_index: int
    stage: str = SESSION_STAGE

    def __post_init__(self) -> None:
        if not isinstance(self.operation_id, str) or not self.operation_id.strip():
            raise ValueError("identity_operation")
        if type(self.round_index) is not int or self.round_index < 0:
            raise ValueError("identity_round")
        if not isinstance(self.stage, str) or not self.stage.strip():
            raise ValueError("identity_stage")

    @property
    def key(self) -> str:
        """Stable, order-independent key for admission and de-duplication."""
        return f"{self.operation_id}#r{self.round_index}#{self.stage}"


@dataclass(frozen=True)
class PlanningRound:
    """The outcome of one planning round.

    ``episode`` is ``None`` only for a new topic, where the host must open a fresh episode
    (M3-QD owns episode creation, not this adapter).
    """

    identity: PlanningIdentity
    decision: ResearchDecision
    queries: tuple[dict[str, str], ...]
    episode: ResearchEpisode | None
    new_topic: bool
    omitted: tuple[str, ...]
    observation_available: bool

    def assert_may_claim_observation_driven(self) -> None:
        """Refuse the phrase "replanned from observation" when it would be a false claim.

        Two ways it can be false: this is the first round (there is nothing to observe yet),
        or the observations were dropped from the context by the §7.5 degradation path, or
        the episode carries no observations at all.
        """

        if self.identity.round_index == 0:
            raise ValueError("observation_claim_on_first_round")
        if not self.observation_available:
            raise ValueError("observation_not_visible")


SessionFactory = Callable[[PlanningIdentity, float], ResearchSemanticSession]


def bounded_session_factory(
    *,
    completion: Callable[..., str],
    should_cancel: Callable[[], bool],
    history_allowed: bool = False,
) -> SessionFactory:
    """Build the default factory: a fresh bounded session per planning round."""

    def factory(identity: PlanningIdentity, deadline: float) -> ResearchSemanticSession:
        return ResearchSemanticSession(
            completion,
            deadline=deadline,
            should_cancel=should_cancel,
            history_allowed=history_allowed,
        )

    return factory


class SemanticQueryPlanner:
    """Middle adapter: model-chosen queries, existing executor, observation back out."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def plan(
        self,
        episode: ResearchEpisode,
        latest: str,
        *,
        identity: PlanningIdentity,
        deadline: float,
        history: str = "",
        active_task_exists: bool = True,
    ) -> PlanningRound:
        """Plan one round of queries.

        ``deadline`` is a ``time.monotonic()`` instant supplied by the caller, never read
        from a module-level window. CL-M3 §9.5 requires the ``answer_then_research`` phases
        to be timed independently while sharing one overall deadline (P-2); taking the
        deadline as an argument is what lets the host hand this phase its own slice of the
        same budget without changing this interface.
        """

        # §7.4: a brand new session every round; a reused one would raise semantic_call_limit.
        session = self._session_factory(identity, deadline)
        decision = session.interpret(
            episode,
            latest,
            history=history,
            active_task_exists=active_task_exists,
        )

        omitted = tuple(session.last_context.get("omitted", ())) if session.last_context else ()
        survived = not any(field in omitted for field in OBSERVATION_FIELDS)
        # §7.5: observations exist and were not dropped by the context cap.
        observation_available = survived and bool(episode.attempts or episode.source_leads)

        queries = tuple(decision.proposed_queries)

        if decision.intent in NON_RESEARCH_INTENTS:
            # The host decides what to do; there is no episode merge and no query plan.
            return PlanningRound(
                identity=identity,
                decision=decision,
                queries=(),
                episode=episode,
                new_topic=False,
                omitted=omitted,
                observation_available=observation_available,
            )

        if decision.intent == "NEW_RESEARCH":
            return PlanningRound(
                identity=identity,
                decision=decision,
                queries=queries,
                episode=None,
                new_topic=True,
                omitted=omitted,
                observation_available=observation_available,
            )

        # §7.6: the same guarantee the old chain applies in persistent_web_agent, moved here.
        old = {row["id"]: row["question"] for row in episode.questions}
        proposed = {row["id"]: row["question"] for row in decision.unresolved_questions}
        if not set(old) <= set(proposed):
            raise ValueError("original_rq_removed")
        frozen = [
            {"id": row["id"], "question": old.get(row["id"], row["question"])}
            for row in decision.unresolved_questions
        ]
        after = replace(
            episode,
            questions=frozen,
            constraints={**episode.constraints, **decision.constraints_delta},
        )
        return PlanningRound(
            identity=identity,
            decision=decision,
            queries=queries,
            episode=after,
            new_topic=False,
            omitted=omitted,
            observation_available=observation_available,
        )


def plan_queries(
    planner: SemanticQueryPlanner,
    episode: ResearchEpisode,
    latest: str,
    *,
    identity: PlanningIdentity,
    deadline: float,
    history: str = "",
    active_task_exists: bool = True,
) -> dict[str, Any]:
    """Flat, JSON-safe view for the outer loop; carries no authority of its own."""

    round_result = planner.plan(
        episode,
        latest,
        identity=identity,
        deadline=deadline,
        history=history,
        active_task_exists=active_task_exists,
    )
    return {
        "identity": round_result.identity.key,
        "intent": round_result.decision.intent,
        "subject": round_result.decision.subject,
        "queries": [dict(row) for row in round_result.queries],
        "new_topic": round_result.new_topic,
        "omitted": list(round_result.omitted),
        "observation_available": round_result.observation_available,
        "episode": round_result.episode.to_dict() if round_result.episode else None,
    }
