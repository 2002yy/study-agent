"""CL-M3 QD-3e: a controllable executor, so the failure modes can be *asked for*.

**Why this exists.** QD-3a/3b/3c tested the persistent research with hand-written
stubs: one that records what it saw, one that fails, one that returns nothing.
That is enough to test the happy path and one failure at a time, but it cannot
test the failure modes that matter most - the ones where **two things happen at
once**:

- a worker dies *after* the model call was billed but *before* the round was
  written down;
- a research is cancelled *between* the executor reading the state and the
  executor starting a call;
- the quota runs out *in the middle* of a round that has already spent
  something;
- two workers scan the same research at the same time.

Each of those needs a specific interleaving, and an interleaving that is
written by hand in each test is an interleaving that only ever happens the way
that test wrote it. This module makes the interleaving **the thing under
test**: the executor is given a *script* of steps, and each step says what to
do and what may be observed while doing it.

**The executor's contract is deliberately narrow.** It is handed a
``ResearchResume`` and a ``ResearchLease`` and it returns an
``AdvanceOutcome`` or ``None``. A script therefore cannot do anything the
coordinator does not already permit - it can only choose *when* to look at
what is around it and *what* to return. The scenarios below are all
scenarios of the production contract, not scenarios the test framework
invented.

**The steps are ordered and the observer is called between them.** A step may
observe the repository (has the research been cancelled? has the quota
changed? is another worker holding the lease?) and that observation happens
*inside* the round, which is exactly the window where the real races live.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from src.application.research_coordinator import AdvanceOutcome, ResearchLease
from src.domain.research_state import ResearchResume, ResearchRound


@dataclass(frozen=True)
class ScriptedStep:
    """One thing the executor does, and what it may look at while doing it.

    ``observe`` is called with the resume and the lease *inside* the round,
    before the step returns. It may look at the repository, at the lease, or
    at anything else - it is the injection point for the interleaving.
    """

    action: str = "advance"
    observe: Callable[[ResearchResume, ResearchLease], None] | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.action, str) or not self.action:
            raise ValueError("invalid_script_action")
        if self.observe is not None and not callable(self.observe):
            raise ValueError("invalid_script_observer")
        if not isinstance(self.payload, dict):
            raise ValueError("invalid_script_payload")


class ScriptedExecutor:
    """An executor that follows a script, one step per round.

    The script is a list of steps. Each invocation of the executor consumes
    the next step. When the script runs out, the executor **declines** -
    it returns ``None`` - because that is what a real executor does when it
    has nothing more to do, and it is the coordinator's job to notice.

    Every invocation is recorded in ``calls``, so a test can assert not only
    that the run went the way it should but also **how many times** the
    executor was entered. A test that cannot see the count cannot tell a
    "ran once" from a "ran and was retried".
    """

    def __init__(
        self,
        script: Sequence[ScriptedStep] = (),
        *,
        round_factory: Callable[[ResearchResume], ResearchRound] | None = None,
    ) -> None:
        self.script = tuple(script)
        self.round_factory = round_factory or _default_round
        self.calls: list[ResearchResume] = []
        self.leases: list[ResearchLease] = []
        self.steps_taken: list[str] = []

    def __call__(
        self, resume: ResearchResume, lease: ResearchLease
    ) -> AdvanceOutcome | None:
        index = len(self.calls)
        self.calls.append(resume)
        self.leases.append(lease)
        if index >= len(self.script):
            # Out of script: decline. The coordinator records nothing, which
            # is the honest outcome for "the executor had nothing to do".
            return None
        step = self.script[index]
        self.steps_taken.append(step.action)
        if step.observe is not None:
            step.observe(resume, lease)
        return self._outcome(resume, lease, step)

    def _outcome(
        self, resume: ResearchResume, lease: ResearchLease, step: ScriptedStep
    ) -> AdvanceOutcome | None:
        action = step.action
        payload = dict(step.payload)
        if action == "decline":
            return None
        if action == "raise":
            raise RuntimeError(payload.get("message", "scripted executor failure"))
        if action == "checkpoint":
            return AdvanceOutcome(
                round_record=self.round_factory(resume),
                status=payload.get("status", "checkpointed"),
                stop_reason=payload.get("stop_reason", ""),
                quota_observed=payload.get("quota_observed"),
                question=payload.get("question", ""),
            )
        if action == "stop":
            return AdvanceOutcome(
                round_record=self.round_factory(resume),
                status="stopped",
                stop_reason=payload.get("stop_reason", "scripted_stop"),
                quota_observed=payload.get("quota_observed"),
            )
        raise ValueError(f"unknown_script_action:{action}")


def _default_round(resume: ResearchResume) -> ResearchRound:
    """A round that says something new, so the research makes progress.

    The default has to produce a *new* observation, because a research whose
    rounds all say the same thing is stopped by the no-progress rule - which
    would make every scenario that uses the default end early for a reason
    that has nothing to do with the scenario.
    """

    index = resume.next_round_index
    return ResearchRound(
        research_id=resume.state.research_id,
        round_index=index,
        question=resume.state.question,
        queries=(f"query-{index}",),
        observation_urls=(f"https://example.invalid/{index}",),
        evidence=(f"fact-{index}",),
        created_at=resume.state.updated_at,
    )


def scripted_round(
    *,
    queries: Sequence[str] = (),
    observation_urls: Sequence[str] = (),
    evidence: Sequence[str] = (),
) -> Callable[[ResearchResume], ResearchRound]:
    """A round factory with fixed content, for the scenarios that need one.

    The no-progress rule compares against *all* earlier rounds, so a test
    that wants "this round adds nothing" must produce a round whose
    observation was already seen. A factory is the only way to say that
    precisely, because the content depends on the round index.
    """

    def factory(resume: ResearchResume) -> ResearchRound:
        index = resume.next_round_index
        return ResearchRound(
            research_id=resume.state.research_id,
            round_index=index,
            question=resume.state.question,
            queries=tuple(queries),
            observation_urls=tuple(observation_urls),
            evidence=tuple(evidence),
            created_at=resume.state.updated_at,
        )

    return factory
