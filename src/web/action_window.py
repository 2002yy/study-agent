"""CL-M3 M3-QC: independent phase timing over one shared action window.

§9.5 / P-2 of ``docs/CL_M3_CAPABILITY_CONTRACT.md`` requires ``answer_then_research`` to
give its two phases independent timing while sharing one overall deadline. The current
dispatch does neither: both phases are checked against the same ``started`` and
``timeout_seconds`` (``conversation_action_dispatch.py``: the pre-flight check and the
check inside ``invoke``), so a preliminary answer may consume the entire window and leave
the research phase with nothing.

This module is the arithmetic only. It owns no clock and no policy about what to do when a
phase overruns; the host (M3-QD) is what applies these deadlines, and keeping the split
here means the guarantee can be tested without standing up a conversation.

The invariant that matters is stated once: **the first phase can never reach the overall
deadline**, so the reserve is structural rather than a matter of the first phase behaving.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

DEFAULT_FIRST_SHARE = 0.6
# The reserve is never smaller than this, even for a very short window: a window too small
# to split is a window in which the second phase cannot run at all, and pretending
# otherwise would only produce a phase that starts and immediately times out.
MIN_RESERVE_SECONDS = 1.0

# Layered policy (§9.5). A conversational turn and a research turn are not the same unit of
# work: five seconds is a plausible bound on choosing and rendering a reply, and no plausible
# bound at all on a search that has to reach the network. Applying one window to both is what
# produced the "answer_then_research gets 5s, of which 1s is reserved for search" situation -
# correct isolation, unusable research.
DEFAULT_CONVERSATIONAL_SECONDS = 5.0
DEFAULT_RESEARCH_SECONDS = 25.0
MAX_ACTION_SECONDS = 30.0


@dataclass(frozen=True)
class ActionWindow:
    """One action window, split into a first phase and a guaranteed reserve."""

    started: float
    total_seconds: float
    first_share: float = DEFAULT_FIRST_SHARE

    def __post_init__(self) -> None:
        if (
            not isinstance(self.started, (int, float))
            or isinstance(self.started, bool)
            or not math.isfinite(self.started)
        ):
            raise ValueError("window_started_not_a_number")
        if (
            not isinstance(self.total_seconds, (int, float))
            or isinstance(self.total_seconds, bool)
            or not math.isfinite(self.total_seconds)
            or self.total_seconds <= 0
        ):
            raise ValueError("window_total_must_be_positive")
        if (
            not isinstance(self.first_share, (int, float))
            or isinstance(self.first_share, bool)
            or not math.isfinite(self.first_share)
            or not 0 < self.first_share < 1
        ):
            # A share of 1 would let the first phase own the whole window, which is exactly
            # the behaviour this module exists to prevent.
            raise ValueError("window_first_share_must_leave_a_reserve")

    @property
    def overall_deadline(self) -> float:
        return self.started + self.total_seconds

    @property
    def reserve_seconds(self) -> float:
        """Time held back for the second phase.

        Two bounds, in this order. The proportional share keeps the split honest for normal
        windows. The floor stops a lopsided ``first_share`` from starving the second phase
        outright. The floor is itself capped at half the window, because a reserve larger
        than the window would make the first deadline precede ``started`` - a phase that is
        expired before it begins.
        """

        proportional = self.total_seconds * (1 - self.first_share)
        floor = min(MIN_RESERVE_SECONDS, self.total_seconds * 0.5)
        return max(proportional, floor)

    @property
    def first_deadline(self) -> float:
        return self.overall_deadline - self.reserve_seconds

    def deadline_for(self, phase: int) -> float:
        """Deadline for phase 0 (preliminary answer) or phase 1 (research)."""

        if phase == 0:
            return self.first_deadline
        if phase == 1:
            return self.overall_deadline
        raise ValueError("window_phase_out_of_range")

    def remaining(self, phase: int, now: float) -> float:
        """Seconds left for ``phase``, floored at zero; never negative by accident."""

        return max(0.0, self.deadline_for(phase) - now)

    def expired(self, phase: int, now: float) -> bool:
        return self.remaining(phase, now) <= 0.0


def split(started: float, total_seconds: float, *, first_share: float = DEFAULT_FIRST_SHARE) -> ActionWindow:
    """Convenience constructor; same validation as the dataclass."""

    return ActionWindow(started=started, total_seconds=total_seconds, first_share=first_share)


@dataclass(frozen=True)
class ActionTimePolicy:
    """How long an action may take, chosen by what kind of action it is.

    The window is picked before the action runs and never extended mid-flight: the two
    phases of ``answer_then_research`` share one ``started``, so the research phase cannot
    buy itself more time by starting late. That is the property the caller depends on, and
    it is why this object returns a window rather than a per-phase timeout.

    ``is_research`` is a boolean rather than a ``ConversationAction`` because this module
    must not import the application layer - the dependency already runs the other way.
    """

    conversational_seconds: float = DEFAULT_CONVERSATIONAL_SECONDS
    research_seconds: float = DEFAULT_RESEARCH_SECONDS
    first_share: float = DEFAULT_FIRST_SHARE

    def __post_init__(self) -> None:
        for name, seconds in (
            ("conversational", self.conversational_seconds),
            ("research", self.research_seconds),
        ):
            if (
                not isinstance(seconds, (int, float))
                or isinstance(seconds, bool)
                or not math.isfinite(seconds)
                or not 0 < seconds <= MAX_ACTION_SECONDS
            ):
                raise ValueError(f"{name}_seconds_out_of_range")

    def window_for(self, *, started: float, is_research: bool) -> ActionWindow:
        total = self.research_seconds if is_research else self.conversational_seconds
        return ActionWindow(
            started=started, total_seconds=total, first_share=self.first_share
        )
