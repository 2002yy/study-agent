"""Offline four-arm harness for the Quality-0 preview.

The preview asks a question the budget modules cannot answer on their own: did
the run that produced an answer stay inside the 45 sends its owner approved?
This module sequences the frozen turns and enforces the send budget at three
levels. It never calls a model.

``ArmExecutor`` is the seam. Offline it is a fake that charges a send and
returns text; a live executor would call the chat entry point, which charges
through ``reserve_call``. Either way the runner is what decides whether the next
turn may start, so an exhausted budget stops the run before the executor is
called again.

One send is charged at all three levels:

    experiment:quality-0     45   the whole preview
    arm:current              20   sends_per_round * turns_per_arm
    round:current:3           4   sends_per_round

The nesting is the point. Binding only the round scope would let every round
spend four sends forever; replacing the outer binding would leave the
experiment ceiling unenforced. ``send_budget_scope`` accumulates, so a single
reservation charges all three, and the refusal names the narrowest scope.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from src.application.send_budget import SendBudget
from src.llm_spend_guard import (
    SendLimitExceeded,
    charge_send,
    send_budget_scope,
)

API_EXECUTION = "api"
MANUAL_EXECUTION = "manual"

COMPLETED = "completed"
FAILED = "failed"
ABORTED = "aborted"
NOT_RUN = "not_run"
MANUAL = "manual"


class ArmPlanError(ValueError):
    """The preview, the task set or the executor wiring cannot form a run."""


@dataclass(frozen=True)
class ArmSpec:
    """One arm of the experiment and the allowance it is approved for."""

    id: str
    execution: str
    sends_per_round: int


@dataclass(frozen=True)
class ArmTurn:
    """One user round of one arm.

    A task with a ``follow_up`` contributes two turns; ``round_index`` is
    1-based because it names the budget scope and the report, and "round 0"
    reads like a task rather than a turn.
    """

    arm_id: str
    round_index: int
    task_id: str
    prompt: str
    is_follow_up: bool = False


class SendCharge(Protocol):
    """The only way an executor is allowed to spend a send."""

    def __call__(self, *, attempts: int = 1) -> None: ...


class ArmExecutor(Protocol):
    """Runs one turn and returns its answer text.

    ``send`` must be called once per physical request, before it leaves the
    process. ``attempts`` is ``retries + 1`` when the SDK may retry internally;
    an executor that leaves retries on must pass them, so the conservative
    number is charged.
    """

    def run_turn(self, turn: ArmTurn, send: SendCharge) -> str: ...


@dataclass(frozen=True)
class TurnRecord:
    """What happened to one turn, whether it ran or not.

    ``answer`` is only meaningful for ``completed``. ``reason`` and ``scope``
    are only set on ``aborted``: the send-limit reason and the scope that
    refused, which is the narrowest one because inner scopes are charged first.
    """

    arm_id: str
    round_index: int
    task_id: str
    status: str
    answer: str = ""
    sends: int = 0
    error: str = ""
    reason: str = ""
    scope: str = ""


@dataclass(frozen=True)
class ArmAbort:
    """Why the run stopped, and where."""

    arm_id: str
    round_index: int
    reason: str
    scope: str
    detail: str


@dataclass(frozen=True)
class ArmRunReport:
    """The durable result of one offline run.

    ``caps`` is what the runner registered and is checked against the preview
    tool's plan. ``usage`` is the budget's own durable count per scope, so a
    restart never reports a number the file disagrees with; it is cumulative for
    the file, not just this run.
    """

    status: str
    experiment: str
    run_id: str
    turns: tuple[TurnRecord, ...] = ()
    abort: ArmAbort | None = None
    caps: Mapping[str, int] = field(default_factory=dict)
    usage: Mapping[str, int] = field(default_factory=dict)

    @property
    def completed_turns(self) -> int:
        return sum(1 for turn in self.turns if turn.status == COMPLETED)

    def usage_of(self, scope: str) -> int:
        return int(self.usage.get(scope, 0))


def arm_specs(preview: Mapping[str, Any]) -> tuple[ArmSpec, ...]:
    """Read the arms from a preview document, refusing anything ambiguous.

    A duplicated id would make two arms share one budget; a manual arm with a
    positive send count would reserve allowance for sends that must never
    happen; an api arm with zero sends could only produce answers nobody paid
    for.
    """

    raw = preview.get("arms")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)) or not raw:
        raise ArmPlanError("preview_arms_empty")

    specs: list[ArmSpec] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, Mapping):
            raise ArmPlanError("preview_arms_invalid")
        arm_id = item.get("id")
        execution = item.get("execution")
        sends = item.get("sends_per_round")
        if not isinstance(arm_id, str) or not arm_id.strip():
            raise ArmPlanError("preview_arms_invalid")
        if arm_id in seen:
            raise ArmPlanError(f"preview_arms_duplicate:{arm_id}")
        seen.add(arm_id)
        if execution not in {API_EXECUTION, MANUAL_EXECUTION}:
            raise ArmPlanError(f"preview_arm_execution_invalid:{arm_id}")
        if isinstance(sends, bool) or not isinstance(sends, int) or sends < 0:
            raise ArmPlanError(f"preview_arm_sends_invalid:{arm_id}")
        if execution == MANUAL_EXECUTION and sends != 0:
            raise ArmPlanError(f"manual_arm_with_sends:{arm_id}")
        if execution == API_EXECUTION and sends < 1:
            raise ArmPlanError(f"api_arm_without_sends:{arm_id}")
        specs.append(ArmSpec(id=arm_id, execution=execution, sends_per_round=sends))
    return tuple(specs)


def _prompts_for(
    preview: Mapping[str, Any], tasks: Mapping[str, Any]
) -> list[tuple[str, str, bool]]:
    """Flatten the selected tasks into (task id, prompt, is follow-up) turns."""

    task_ids = preview.get("task_ids")
    if (
        not isinstance(task_ids, Sequence)
        or isinstance(task_ids, (str, bytes))
        or not task_ids
    ):
        raise ArmPlanError("preview_tasks_empty")
    if any(not isinstance(task_id, str) for task_id in task_ids):
        raise ArmPlanError("preview_tasks_invalid")
    if len(set(task_ids)) != len(task_ids):
        raise ArmPlanError("preview_tasks_duplicate")

    rows = tasks.get("tasks")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise ArmPlanError("tasks_fixture_invalid")
    by_id: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        if isinstance(row, Mapping) and isinstance(row.get("id"), str):
            by_id[row["id"]] = row

    prompts: list[tuple[str, str, bool]] = []
    for task_id in task_ids:
        if not isinstance(task_id, str):
            raise ArmPlanError("preview_tasks_invalid")
        task = by_id.get(task_id)
        if task is None:
            raise ArmPlanError(f"unknown_task:{task_id}")
        prompt = task.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ArmPlanError(f"task_without_prompt:{task_id}")
        prompts.append((task_id, prompt, False))
        follow_up = task.get("follow_up")
        if follow_up is not None:
            if not isinstance(follow_up, str) or not follow_up.strip():
                raise ArmPlanError(f"task_without_follow_up_prompt:{task_id}")
            prompts.append((task_id, follow_up, True))
    return prompts


def plan_turns(
    preview: Mapping[str, Any], tasks: Mapping[str, Any]
) -> dict[str, tuple[ArmTurn, ...]]:
    """Give every arm the same turns, in the same order.

    Fairness is structural: the arms differ by execution, never by which user
    rounds they see.
    """

    specs = arm_specs(preview)
    prompts = _prompts_for(preview, tasks)
    return {
        spec.id: tuple(
            ArmTurn(
                arm_id=spec.id,
                round_index=index,
                task_id=task_id,
                prompt=prompt,
                is_follow_up=is_follow_up,
            )
            for index, (task_id, prompt, is_follow_up) in enumerate(prompts, start=1)
        )
        for spec in specs
    }


def derive_caps(
    specs: Sequence[ArmSpec],
    turns_by_arm: Mapping[str, tuple[ArmTurn, ...]],
    *,
    experiment: str = "quality-0",
) -> dict[str, int]:
    """The three-level caps, derived only from what the preview approved.

    Manual arms get no scope at all: a cap of zero is rejected by the budget
    schema, and a cap above zero would reserve sends that must never happen.
    """

    if not isinstance(experiment, str) or not experiment.strip():
        raise ValueError("experiment name is required")

    caps: dict[str, int] = {}
    experiment_cap = 0
    for spec in specs:
        if spec.execution != API_EXECUTION:
            continue
        arm_turns = turns_by_arm.get(spec.id, ())
        if not arm_turns:
            raise ArmPlanError(f"arm_without_turns:{spec.id}")
        arm_cap = spec.sends_per_round * len(arm_turns)
        caps[f"arm:{spec.id}"] = arm_cap
        for turn in arm_turns:
            caps[f"round:{spec.id}:{turn.round_index}"] = spec.sends_per_round
        experiment_cap += arm_cap

    if experiment_cap <= 0:
        raise ArmPlanError("preview_has_no_api_arm")
    caps[f"experiment:{experiment}"] = experiment_cap
    return caps


def _refusal_scope(exc: SendLimitExceeded) -> str:
    cause = exc.__cause__
    scope = getattr(cause, "scope", None)
    return scope if isinstance(scope, str) else ""


class Quality0ArmRunner:
    """Runs the arms in preview order under one nested send budget."""

    def __init__(
        self,
        *,
        budget: SendBudget,
        experiment: str = "quality-0",
        run_id: str = "preview-1",
    ) -> None:
        if not isinstance(experiment, str) or not experiment.strip():
            raise ValueError("experiment name is required")
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError("run id is required")
        self._budget = budget
        self._experiment = experiment
        self._run_id = run_id

    def run(
        self,
        *,
        preview: Mapping[str, Any],
        tasks: Mapping[str, Any],
        executors: Mapping[str, ArmExecutor],
    ) -> ArmRunReport:
        """Run every turn of every api arm, or stop the whole run.

        A send-limit refusal is not a turn-level failure to record and continue
        past: it means the approved number of sends is gone, so every later turn
        would either spend beyond the approval or produce an answer nobody paid
        for. Both are worse than an aborted run.
        """

        specs = arm_specs(preview)
        turns_by_arm = plan_turns(preview, tasks)
        caps = derive_caps(specs, turns_by_arm, experiment=self._experiment)
        self._require_executors(specs, executors)
        self._budget.register(caps)

        experiment_scope = f"experiment:{self._experiment}"
        executed: list[TurnRecord] = []
        abort: ArmAbort | None = None

        for spec in specs:
            if abort is not None:
                break
            arm_turns = turns_by_arm[spec.id]
            if spec.execution == MANUAL_EXECUTION:
                executed.extend(
                    TurnRecord(
                        arm_id=turn.arm_id,
                        round_index=turn.round_index,
                        task_id=turn.task_id,
                        status=MANUAL,
                    )
                    for turn in arm_turns
                )
                continue

            executor = executors[spec.id]
            with send_budget_scope(
                self._budget, [experiment_scope, f"arm:{spec.id}"]
            ):
                for turn in arm_turns:
                    with send_budget_scope(
                        self._budget, [f"round:{spec.id}:{turn.round_index}"]
                    ):
                        record = self._run_turn(executor, turn)
                    executed.append(record)
                    if record.status == ABORTED:
                        abort = ArmAbort(
                            arm_id=record.arm_id,
                            round_index=record.round_index,
                            reason=record.reason,
                            scope=record.scope,
                            detail=record.error,
                        )
                        break

        records = self._ordered(specs, turns_by_arm, executed)
        if abort is not None:
            status = ABORTED
        elif any(record.status == FAILED for record in records):
            status = "partial"
        else:
            status = COMPLETED
        return ArmRunReport(
            status=status,
            experiment=self._experiment,
            run_id=self._run_id,
            turns=records,
            abort=abort,
            caps=dict(caps),
            usage={scope: self._budget.usage(scope) for scope in caps},
        )

    # -- internals ----------------------------------------------------------
    @staticmethod
    def _require_executors(
        specs: Sequence[ArmSpec], executors: Mapping[str, ArmExecutor]
    ) -> None:
        api_ids = {spec.id for spec in specs if spec.execution == API_EXECUTION}
        missing = sorted(api_ids - set(executors))
        if missing:
            raise ArmPlanError(f"missing_executors:{missing}")
        unknown = sorted(set(executors) - {spec.id for spec in specs})
        if unknown:
            raise ArmPlanError(f"unknown_executors:{unknown}")
        manual = sorted(
            spec.id
            for spec in specs
            if spec.execution == MANUAL_EXECUTION and spec.id in executors
        )
        if manual:
            # The chatgpt arm is run by a human. Wiring an executor to it would
            # make "the manual arm sent an API request" a one-line mistake.
            raise ArmPlanError(f"manual_arm_has_executor:{manual}")

    def _run_turn(self, executor: ArmExecutor, turn: ArmTurn) -> TurnRecord:
        sends = 0

        def send(*, attempts: int = 1) -> None:
            nonlocal sends
            charge_send(
                request_key=(
                    f"{self._run_id}:{turn.arm_id}:{turn.round_index}:{sends + 1}"
                ),
                attempts=attempts,
            )
            sends += 1

        def record(status: str, **extra: Any) -> TurnRecord:
            return TurnRecord(
                arm_id=turn.arm_id,
                round_index=turn.round_index,
                task_id=turn.task_id,
                status=status,
                sends=sends,
                **extra,
            )

        try:
            answer = executor.run_turn(turn, send)
        except SendLimitExceeded as exc:
            return record(
                ABORTED,
                error=str(exc),
                reason=exc.reason,
                scope=_refusal_scope(exc),
            )
        except Exception as exc:  # executor failure is data, not a budget stop
            return record(FAILED, error=f"{type(exc).__name__}: {exc}")

        if not isinstance(answer, str):
            return record(FAILED, error="non_string_answer")
        if sends == 0:
            # An api arm that answered without spending a send claims a model
            # produced it for free. Recording that as a completed turn would put
            # a fabricated data point into the very experiment that exists to
            # compare real answers.
            return record(FAILED, error="completed_turn_without_a_send")
        return record(COMPLETED, answer=answer)

    @staticmethod
    def _ordered(
        specs: Sequence[ArmSpec],
        turns_by_arm: Mapping[str, tuple[ArmTurn, ...]],
        executed: Sequence[TurnRecord],
    ) -> tuple[TurnRecord, ...]:
        """The whole plan, with turns that never ran marked as such."""

        by_key = {(record.arm_id, record.round_index): record for record in executed}
        ordered: list[TurnRecord] = []
        for spec in specs:
            for turn in turns_by_arm[spec.id]:
                record = by_key.get((turn.arm_id, turn.round_index))
                if record is None:
                    record = TurnRecord(
                        arm_id=turn.arm_id,
                        round_index=turn.round_index,
                        task_id=turn.task_id,
                        status=NOT_RUN,
                    )
                ordered.append(record)
        return tuple(ordered)


__all__ = [
    "ABORTED",
    "API_EXECUTION",
    "ArmAbort",
    "ArmExecutor",
    "ArmPlanError",
    "ArmRunReport",
    "ArmSpec",
    "ArmTurn",
    "COMPLETED",
    "FAILED",
    "MANUAL",
    "MANUAL_EXECUTION",
    "NOT_RUN",
    "Quality0ArmRunner",
    "SendCharge",
    "TurnRecord",
    "arm_specs",
    "derive_caps",
    "plan_turns",
]
