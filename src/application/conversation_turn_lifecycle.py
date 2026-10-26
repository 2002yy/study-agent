"""M3-QD-2d: the production turn host - start, cancel, disconnect, settle once.

``OwnedConversationBinding`` already knows how to turn a real ``start_turn`` identity into
a single-consumer loop, and says so in its own docstring: *the host must own that
lifecycle*. This module is that host. It adds the three things the binding deliberately
does not do.

**One settlement authority.** The turn settles money exactly once, at close, from the
loop's own receipts. Nothing inside the loop settles: the loop does not know when a turn
ends, and a per-call settle would book a killed turn as a series of clean calls. Close is
reached through a ``finally``, so success, terminal stop, timeout, user cancel and an SSE
disconnect all take the same path.

**Cancellation is polled, not assumed.** ``should_cancel`` is the host's own predicate over
its own repository. Before the turn starts it costs nothing; inside the loop it stops the
next admitted decision. What it cannot do is interrupt a handler already running - the
dispatcher's deadline covers that, and the observation it may still produce is recorded as
unknown rather than as free.

**The window leaves time for the answer.** The loop's deadline is the turn's total minus
the answer reserve minus the settlement reserve, computed in one place. A 25 second action
window is an upper bound on one action, not a licence for research to consume the turn;
if the arithmetic leaves no research time the host refuses to build, because a turn that
starts with a zero-length budget would spend money to discover it had none.
"""

from __future__ import annotations

from contextlib import aclosing
from dataclasses import dataclass, replace
import math
from typing import AsyncGenerator, Callable

from src.application.conversation_action_dispatch import ActionEvent
from src.application.conversation_answer_runner import answer_reservation_id
from src.application.conversation_bounded_loop import LoopEvent, LoopLimits, LoopStopped
from src.application.conversation_decision import ConversationAction
from src.application.conversation_decision_runner import DecisionResult
from src.application.conversation_loop_session import ConversationLoopSession
from src.application.conversation_owned_binding import OwnedConversationBinding
from src.application.conversation_spend_gate import SpendGatedAdmission
from src.domain.spend_settlement import EVIDENCE_WORKER_RECEIPT, evidence_ref
from src.web.action_window import MAX_ACTION_SECONDS, ActionTimePolicy

# ``LoopLimits`` refuses anything above this, so the host caps rather than constructs an
# object it knows will raise.
MAX_TURN_SECONDS = 120.0

CANCELLED = "cancelled"


@dataclass(frozen=True)
class TurnDeadline:
    """The turn's time budget, split so research cannot spend the answer's time.

    ``total_seconds`` is wall clock for the whole turn. ``answer_reserve_seconds`` is held
    back for the final answer and ``settlement_reserve_seconds`` for the receipt and the
    spend settlement. What is left is the research budget, and it has to be positive.
    """

    total_seconds: float = 60.0
    answer_reserve_seconds: float = 12.0
    settlement_reserve_seconds: float = 1.0

    def __post_init__(self) -> None:
        for name, value, allow_zero in (
            ("total", self.total_seconds, False),
            ("answer_reserve", self.answer_reserve_seconds, False),
            ("settlement_reserve", self.settlement_reserve_seconds, True),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
                or (not allow_zero and value == 0)
            ):
                raise ValueError(f"turn_{name}_seconds_out_of_range")
        if self.total_seconds > MAX_TURN_SECONDS:
            raise ValueError("turn_total_seconds_out_of_range")

    @property
    def research_seconds(self) -> float:
        """What the loop may spend on decisions and tools. Never the whole turn."""
        remaining = (
            self.total_seconds
            - self.answer_reserve_seconds
            - self.settlement_reserve_seconds
        )
        if remaining <= 0:
            raise ValueError("turn_leaves_no_time_for_research")
        return min(remaining, MAX_TURN_SECONDS)

    def loop_limits(self, base: LoopLimits | None = None) -> LoopLimits:
        """The supplied limits with the turn's own window. Nothing else is replaced."""
        return replace(base or LoopLimits(), timeout_seconds=self.research_seconds)

    def action_policy(self, base: ActionTimePolicy | None = None) -> ActionTimePolicy:
        """No single action may be given more wall clock than the turn has left."""
        policy = base or ActionTimePolicy()
        return replace(
            policy,
            research_seconds=min(
                policy.research_seconds, self.research_seconds, MAX_ACTION_SECONDS
            ),
        )


@dataclass(frozen=True)
class TurnIdentities:
    """The three identifiers a real turn already owns; nothing new is minted here."""

    thread_id: str
    turn_id: str
    operation_id: str

    def __post_init__(self) -> None:
        for name in ("thread_id", "turn_id", "operation_id"):
            value = getattr(self, name)
            if (
                not isinstance(value, str)
                or not value.strip()
                or len(value) > 160
            ):
                raise ValueError(f"invalid_turn_{name}")


def turn_identities(prepared: object) -> TurnIdentities:
    """Read the identities off a ``PreparedChatTurn`` without importing its service.

    ``start_turn`` returns the thread, the pending turn and - on the turn - the operation
    that owns it. Those are the only three things the loop needs, so the host takes them
    rather than the whole prepared object; it also checks that the turn really belongs to
    the thread, because a mismatch here would let one turn read another's history.
    """

    thread = getattr(prepared, "thread", None)
    turn = getattr(prepared, "turn", None)
    if thread is None or turn is None:
        raise ValueError("not_a_prepared_turn")
    identities = TurnIdentities(
        thread_id=getattr(thread, "id", "") or "",
        turn_id=getattr(turn, "id", "") or "",
        operation_id=getattr(turn, "operation_id", "") or "",
    )
    if getattr(turn, "thread_id", None) != identities.thread_id:
        raise ValueError("prepared_turn_not_owned_by_thread")
    return identities


@dataclass(frozen=True)
class TurnSettlement:
    """What the host can say about the money when the turn is over."""

    settled: tuple[str, ...] = ()
    unresolved: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        return not self.unresolved


class TurnLifecycle:
    """Start, stream, cancel and settle one owned turn.

    The stream is the only surface: a caller that stops reading closes the turn, and
    closing settles. There is deliberately no ``start``/``finish`` pair, because a host
    that forgets ``finish`` would leave money reserved forever and a host that calls it
    twice would need exactly the bookkeeping this class exists to remove.
    """

    def __init__(
        self,
        binding: OwnedConversationBinding,
        *,
        gate: SpendGatedAdmission,
        deadline: TurnDeadline = TurnDeadline(),
        should_cancel: Callable[[], bool] = lambda: False,
    ) -> None:
        if not isinstance(binding, OwnedConversationBinding):
            raise ValueError("invalid conversation binding")
        if not isinstance(gate, SpendGatedAdmission):
            raise ValueError("invalid spend gate")
        if not isinstance(deadline, TurnDeadline):
            raise ValueError("invalid turn deadline")
        if not callable(should_cancel):
            raise ValueError("invalid cancel probe")
        # Fail at construction, not mid-turn: a deadline with nothing left for research
        # is a misconfiguration, and discovering it after the first paid call would mean
        # paying to learn that the turn could not run.
        deadline.research_seconds
        self._binding = binding
        self._gate = gate
        self._deadline = deadline
        self._should_cancel = should_cancel
        self._session: ConversationLoopSession | None = None
        self._settled: list[str] = []
        self._unresolved: tuple[str, ...] = ()

    @property
    def session(self) -> ConversationLoopSession | None:
        """The live session, or ``None`` before the first read. Read-only."""
        return self._session

    @property
    def settlement(self) -> TurnSettlement:
        """Empty until the turn closes; then exactly what was booked."""
        return TurnSettlement(tuple(self._settled), self._unresolved)

    def _cancelled(self) -> bool:
        return bool(self._should_cancel())

    def _attribute(self, event: LoopEvent) -> None:
        """Book the calls this event proves completed. Everything else stays open."""
        if isinstance(event, DecisionResult):
            if event.status == "completed" and event.proposal is not None:
                identity = event.proposal.request_id
                # The loop's own decision result is the receipt for this send: it
                # names the request it belongs to, so the audit cannot attach it to
                # a different call.
                if self._gate.settle_completed(
                    identity,
                    evidence_ref=evidence_ref(
                        kind=EVIDENCE_WORKER_RECEIPT,
                        request_key=identity,
                        receipt=f"decision:{event.status}",
                    ),
                ):
                    self._settled.append(identity)
            return
        if isinstance(event, ActionEvent) and event.stage == ConversationAction.ANSWER:
            if event.status != "observed" or self._session is None:
                return
            # The answer reservation is namespaced apart from the decision's, so a
            # successful answer would otherwise close as "unresolved" - conservative for
            # the budget and wrong for the report.
            identity = answer_reservation_id(self._session.receipt.request_id)
            if self._gate.settle_completed(
                identity,
                evidence_ref=evidence_ref(
                    kind=EVIDENCE_WORKER_RECEIPT,
                    request_key=identity,
                    receipt="answer:observed",
                ),
            ):
                self._settled.append(identity)

    async def stream(self, prepared: object) -> AsyncGenerator[LoopEvent, None]:
        """Stream one turn. Closing the generator closes and settles the turn."""
        identities = turn_identities(prepared)
        if self._cancelled():
            # Nothing has been admitted, so this costs nothing. Emitting the terminal
            # event rather than an empty stream keeps "cancelled" a structured stop
            # reason (Q-9) instead of an absence.
            self._close_books()
            yield LoopStopped(CANCELLED, 0, 0, False, "before_start")
            return
        session = self._binding.start(
            identities.thread_id,
            identities.turn_id,
            identities.operation_id,
            should_cancel=self._should_cancel,
            turn_window_seconds=self._deadline.research_seconds,
            # The gate is handed down rather than read back from the snapshot: the object
            # that settles must be the object the loop reserved on, and the only way to
            # guarantee that is to pass it.
            model_budget=self._gate,
        )
        self._session = session
        try:
            async with aclosing(session.events()) as events:
                async for event in events:
                    self._attribute(event)
                    yield event
        finally:
            # Success, terminal stop, timeout, cancel and disconnect all arrive here.
            # Settling in one place is what makes the settlement authority unique.
            try:
                await session.aclose()
            finally:
                self._close_books()

    def _close_books(self) -> None:
        """Settle whatever is still reserved. Idempotent: the second call is a no-op."""
        self._unresolved = self._gate.settle_unresolved()
