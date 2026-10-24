"""CL-M3 M3-QD (first cut): the loop that makes a second query depend on the first result.

This is the piece the contract calls the core of search autonomy (§7.8, item four): not
"plan three queries and run them in order", but *new information changing the next step*.

Everything here is real code except two injected collaborators: the completion the planner
calls (a model, or a scripted stand-in) and the executor that turns a query into call
records. The planning adapter, the observation projection, the stop reasons and the
admission gate are the production implementations from M3-QA, M3-QB and M3-QC.

Two boundaries this module keeps:

* **Causality is recorded, not asserted by the caller.** ``RoundRecord.observation_seen_by_model``
  is what the planner's payload actually contained when the round was planned, so a test can
  require that the second query was produced *after* the first observation entered the
  payload - rather than inferring it from two queries happening to differ.
* **Search results are observations, never evidence.** The episode carries bounded planning
  context; nothing here promotes a read to a published claim.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Any, Callable, Mapping, Sequence

from src.web.semantic_observation import (
    CONTINUE,
    STOP_BUDGET_EXHAUSTED,
    STOP_EVIDENCE_SUFFICIENT,
    absorb,
    new_lead_urls,
    next_phase,
)
from src.web.semantic_admission import validate_tool_call
from src.web.semantic_planner import PlanningIdentity, SemanticQueryPlanner
from src.web.semantic_recovery import ResearchEpisode

DEFAULT_MAX_ROUNDS = 3


@dataclass(frozen=True)
class RoundRecord:
    """What one round did, in the order the loop actually did it."""

    round_index: int
    queries: tuple[dict[str, str], ...]
    observation_urls: tuple[str, ...]
    stop_reason: str
    observation_seen_by_model: bool


@dataclass
class TurnResult:
    rounds: list[RoundRecord] = field(default_factory=list)
    stop_reason: str = ""
    episode: ResearchEpisode | None = None
    cancelled: bool = False

    @property
    def queries(self) -> list[str]:
        return [row["query"] for record in self.rounds for row in record.queries]


class SemanticResearchHost:
    """Run planning rounds until a stop reason is reached.

    ``execute`` is the only way a query reaches the outside world. It receives the planned
    queries and returns call records shaped exactly like the executor's (``name``,
    ``arguments``, ``result``), which is what the observation projection already consumes.
    """

    def __init__(
        self,
        *,
        planner: SemanticQueryPlanner,
        execute: Callable[[Sequence[dict[str, str]]], list[dict[str, Any]]],
        is_public_url: Callable[[Any], bool],
        episode: ResearchEpisode,
        operation_id: str,
        should_cancel: Callable[[], bool] = lambda: False,
        max_rounds: int = DEFAULT_MAX_ROUNDS,
        budget_remaining: Callable[[], int] = lambda: DEFAULT_MAX_ROUNDS,
        window_seconds: float = 30.0,
        quota: Any | None = None,
    ) -> None:
        if type(max_rounds) is not int or max_rounds < 1:
            raise ValueError("host_max_rounds")
        if not isinstance(episode, ResearchEpisode):
            raise ValueError("host_episode")
        self._planner = planner
        self._execute = execute
        self._is_public_url = is_public_url
        self._episode = episode
        self._operation_id = operation_id
        self._should_cancel = should_cancel
        self._max_rounds = max_rounds
        self._budget_remaining = budget_remaining
        self._quota = quota
        self._deadline = time.monotonic() + window_seconds

    @property
    def episode(self) -> ResearchEpisode:
        return self._episode

    def run_turn(self, latest: str, *, history: str = "") -> TurnResult:
        result = TurnResult(episode=self._episode)
        for round_index in range(self._max_rounds):
            identity = PlanningIdentity(self._operation_id, round_index)
            if self._quota is not None:
                # One reservation per round, keyed by the round identity. Replaying the
                # same round must not buy quota again, so the refusal is a stop reason and
                # not a retry.
                verdict = self._quota.reserve(identity.key, 0, 0)
                if verdict != "reserved":
                    result.episode = self._episode
                    result.stop_reason = STOP_BUDGET_EXHAUSTED
                    return result
            planned = self._planner.plan(
                self._episode, latest, identity=identity, deadline=self._deadline,
                history=history,
            )
            # The model's own judgement is the only route to "evidence sufficient".
            if planned.decision.intent in {"ANSWER", "ABSTAIN"}:
                # The episode carries every observation gathered so far; an early stop must
                # not hand the caller the episode it started with.
                result.episode = self._episode
                result.stop_reason = STOP_EVIDENCE_SUFFICIENT
                return result

            previous_leads = list(self._episode.source_leads)
            calls = self._execute(planned.queries)
            self._episode = absorb(self._episode, calls, is_public_url=self._is_public_url)
            fresh = new_lead_urls(previous_leads, self._episode.source_leads)

            # Whether the observations reached the planner is a fact about this round's
            # payload, recorded by the adapter - not a guess made afterwards.
            seen = planned.observation_available
            record = RoundRecord(
                round_index=round_index,
                queries=tuple(dict(row) for row in planned.queries),
                observation_urls=tuple(sorted(fresh)),
                stop_reason=CONTINUE,
                observation_seen_by_model=seen,
            )

            reason = next_phase(
                cancelled=self._should_cancel(),
                budget_remaining=min(self._budget_remaining(), self._max_rounds - round_index - 1),
                new_leads=len(fresh),
                model_intent=planned.decision.intent,
            )
            if reason != CONTINUE:
                result.rounds.append(replace_stop(record, reason))
                result.episode = self._episode
                result.stop_reason = reason
                result.cancelled = reason == "cancelled"
                return result
            result.rounds.append(record)

        result.stop_reason = STOP_BUDGET_EXHAUSTED
        result.episode = self._episode
        return result


class SemanticToolHandler:
    """The ``USE_TOOL`` seam: Q-11 checked before any executor runs.

    The loop registers handlers by ``ConversationAction``, so the tool name in a proposal is
    untrusted input. This adapter refuses on four independent grounds and only then runs the
    round, which is what keeps "the tool name exists" from becoming "this action may use it".
    """

    def __init__(
        self,
        host: SemanticResearchHost,
        *,
        registry: Mapping[str, Any],
        permitted: frozenset[str],
        budget_remaining: Callable[[], int],
    ) -> None:
        self._host = host
        self._registry = registry
        self._permitted = permitted
        self._budget_remaining = budget_remaining
        self.refusals: list[str] = []

    def run(self, *, action: str, tool: str, arguments: Any) -> TurnResult | None:
        decision = validate_tool_call(
            action=action,
            tool=tool,
            registry=self._registry,
            permitted=self._permitted,
            budget_remaining=self._budget_remaining(),
            arguments=arguments,
        )
        if not decision.allowed:
            self.refusals.append(decision.reason)
            return None
        latest = str((arguments or {}).get("latest") or self._host.episode.original_question)
        return self._host.run_turn(latest)


def replace_stop(record: RoundRecord, reason: str) -> RoundRecord:
    return RoundRecord(
        round_index=record.round_index,
        queries=record.queries,
        observation_urls=record.observation_urls,
        stop_reason=reason,
        observation_seen_by_model=record.observation_seen_by_model,
    )

