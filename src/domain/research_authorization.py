"""CL-M3 QD-3d: the vocabulary for ending a research, and for spending more.

QD-3a made a research durable and QD-3b made something advance it; QD-3c let
a client watch one without being able to end it. This module holds the three
answers that were still missing, and it holds them as **data** rather than as
behaviour: the policy that decides lives in the repository, this module
decides what a decision may look like.

**Three shapes, each for a reason that was decided rather than discovered.**

**Cancellation is a fact, not an event.** ``cancel_requested_at`` lives on the
research state because a cancellation has to outlive the process that
received it: the worker that picks the research up next is a different
process, and it is the one that would otherwise start the next model call. An
event would have been the wrong shape for the same reason - it is a *fact
about the research now*, and the state row is where facts about the research
now live.

**Progress is a difference, not a count.** ``ResearchProgress`` answers "what
did this round observe that the research had not observed before". The
difference is against *every* earlier round, not the previous one, because a
research that oscillates between two sets of findings would otherwise look
productive forever. A reworded fact attached to a source that was already
read is not new knowledge, which is why the observation - not the wording -
is what the difference is measured on.

**An authorisation is a decision with an author and an expiry.**
``TierAuthorization`` is deliberately not a field on the research state.
``quota_observed`` is an observation of a budget and is rewritten on every
checkpoint; an authorisation is a permission that must survive long enough
to be audited, and that a different operation identity may not inherit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any

# The two tiers of §10.6 R-1. A tier names a budget envelope, not a model.
TIER_STANDARD = "standard"
TIER_DEEP = "deep"
TIERS = frozenset({TIER_STANDARD, TIER_DEEP})

# The three states an authorisation may be in. ``pending`` is the state a
# *request* is in, and it grants nothing.
AUTHORIZATION_PENDING = "pending"
AUTHORIZATION_APPROVED = "approved"
AUTHORIZATION_DENIED = "denied"
AUTHORIZATION_EXPIRED = "expired"
AUTHORIZATION_STATES = frozenset(
    {
        AUTHORIZATION_PENDING,
        AUTHORIZATION_APPROVED,
        AUTHORIZATION_DENIED,
        AUTHORIZATION_EXPIRED,
    }
)

# The stop reason written when a research ends because two rounds in a row
# produced no effective gain. The state is ``stopped``, not ``failed``: the
# research ended on purpose and what it found is still true.
STOP_REASON_NO_PROGRESS = "no_information_gain"

# The stop reason written when the user cancels.
STOP_REASON_CANCELLED = "user_cancelled"

# An identifier may contain the characters that an ISO timestamp has, because
# the default request id is derived from one. The set is still narrow: no
# spaces, no path separators, nothing that could be mistaken for a path or a
# command.
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+-]{0,159}$")


def _identifier(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.match(value):
        raise ValueError(f"invalid_{name}")
    return value


def _text(value: Any, name: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"invalid_{name}")
    return value


def _count(value: Any, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"invalid_{name}")
    return value


def _money(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"invalid_{name}")
    if value < 0:
        raise ValueError(f"invalid_{name}")
    return float(value)


def _timestamp(value: Any, name: str) -> str:
    """A timestamp must be comparable, so it must parse."""

    if not isinstance(value, str) or not value.strip() or len(value) > 64:
        raise ValueError(f"invalid_{name}")
    try:
        datetime.fromisoformat(value)
    except ValueError:
        raise ValueError(f"invalid_{name}") from None
    return value


def _is_expired(valid_until: str, now: str) -> bool:
    """Whether an authorisation has run out at ``now``.

    The comparison is on the parsed instants rather than on the strings:
    two ISO timestamps in different offsets do not compare correctly as text,
    and an expiry that is decided by string comparison can be wrong by hours.
    """

    if not valid_until:
        return False
    try:
        deadline = datetime.fromisoformat(valid_until)
        moment = datetime.fromisoformat(now)
    except ValueError:
        return True
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment >= deadline


@dataclass(frozen=True)
class ResearchProgress:
    """What one round observed that the research had not observed before.

    The empty case is the interesting one: ``has_gain`` is False exactly when
    the round learned nothing new. A research that compares only the previous
    round would find a difference whenever it oscillates, so both differences
    here are against *all* earlier rounds.
    """

    new_evidence: tuple[str, ...] = ()
    new_observation_urls: tuple[str, ...] = ()
    rounds_considered: int = 0

    @property
    def has_gain(self) -> bool:
        """Whether this round taught the research something it did not know.

        A new *fact* is what counts. A source that was never read is worth
        reporting - it was read, and a later round may learn from it - but on
        its own it is not knowledge: the contract says "新观察不等于有效增量",
        and a round that opens a page and comes back with no new fact has
        produced a page-turn, not a finding.

        Counting a bare new source would let a research read an endless supply
        of fresh pages that say nothing, each one resetting the no-progress
        counter - which is the "跑满时长" the contract forbids.

        The two fields are not redundant: ``new_observation_urls`` says what
        was read, ``new_evidence`` says what was learned, and only the second
        one is an increment.
        """

        return bool(self.new_evidence)

    def as_dict(self) -> dict[str, Any]:
        return {
            "new_evidence": list(self.new_evidence),
            "new_observation_urls": list(self.new_observation_urls),
            "rounds_considered": self.rounds_considered,
            "has_gain": self.has_gain,
        }


@dataclass(frozen=True)
class TierUpgradeRequest:
    """A research asking to move up a tier. Grants nothing by itself."""

    request_id: str
    research_id: str
    operation_id: str
    from_tier: str
    to_tier: str
    reason: str = ""
    requested_calls: int = 0
    requested_cost: float = 0.0
    status: str = AUTHORIZATION_PENDING
    requested_at: str = ""

    def __post_init__(self) -> None:
        _identifier(self.request_id, "request_id")
        _identifier(self.research_id, "research_id")
        _identifier(self.operation_id, "operation_id")
        if self.from_tier not in TIERS:
            raise ValueError("invalid_from_tier")
        if self.to_tier not in TIERS:
            raise ValueError("invalid_to_tier")
        if self.status not in AUTHORIZATION_STATES:
            raise ValueError("invalid_authorization_status")
        _text(self.reason, "reason", 2000)
        _count(self.requested_calls, "requested_calls")
        _money(self.requested_cost, "requested_cost")
        if self.requested_at:
            _timestamp(self.requested_at, "requested_at")

    @property
    def approved(self) -> bool:
        return self.status == AUTHORIZATION_APPROVED


@dataclass(frozen=True)
class TierAuthorization:
    """A user's decision about one upgrade request.

    The author, the moment and the expiry are all required. An authorisation
    without an author is not an authorisation - it is a flag - and one
    without an expiry is a permission that never ends, which is not what
    "this time, this much" means.
    """

    request_id: str
    research_id: str
    operation_id: str
    status: str = AUTHORIZATION_PENDING
    approver: str = ""
    scope: str = ""
    valid_until: str = ""
    max_calls: int = 0
    max_cost: float = 0.0
    decided_at: str = ""
    requested_at: str = ""

    def __post_init__(self) -> None:
        _identifier(self.request_id, "request_id")
        _identifier(self.research_id, "research_id")
        _identifier(self.operation_id, "operation_id")
        if self.status not in AUTHORIZATION_STATES:
            raise ValueError("invalid_authorization_status")
        if self.approver:
            _text(self.approver, "approver", 160)
        if self.scope:
            _text(self.scope, "scope", 500)
        _count(self.max_calls, "max_calls")
        _money(self.max_cost, "max_cost")
        if self.valid_until:
            _timestamp(self.valid_until, "valid_until")
        if self.decided_at:
            _timestamp(self.decided_at, "decided_at")
        if self.requested_at:
            _timestamp(self.requested_at, "requested_at")

    @property
    def approved(self) -> bool:
        return self.status == AUTHORIZATION_APPROVED

    def has_expired(self, now: str) -> bool:
        """Whether the clock has passed this grant's deadline.

        This is the expiry question alone, with no question about whether the
        grant was approved in the first place. ``is_valid_at`` answers the
        combined question and is what the upgrade path uses; this one is what
        the record-keeping path uses, because a grant that was never approved
        has nothing to expire.
        """

        return _is_expired(self.valid_until, now)

    def is_valid_at(self, now: str) -> bool:
        """Whether this authorisation still grants an upgrade at ``now``.

        Four things must hold, and all four are checked here rather than at
        the call sites: it was approved, it has not expired, it belongs to
        this research, and it belongs to this operation identity.
        """

        if not self.approved:
            return False
        if _is_expired(self.valid_until, now):
            return False
        return True

    def covers(self, calls: int, cost: float) -> bool:
        """Whether the grant is big enough for what is about to be spent."""

        if calls < 0 or cost < 0:
            return False
        if self.max_calls and calls > self.max_calls:
            return False
        if self.max_cost and cost > self.max_cost:
            return False
        return True

    def as_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "research_id": self.research_id,
            "operation_id": self.operation_id,
            "status": self.status,
            "approver": self.approver,
            "scope": self.scope,
            "valid_until": self.valid_until,
            "max_calls": self.max_calls,
            "max_cost": self.max_cost,
            "decided_at": self.decided_at,
            "requested_at": self.requested_at,
        }


__all__ = [
    "AUTHORIZATION_APPROVED",
    "AUTHORIZATION_DENIED",
    "AUTHORIZATION_EXPIRED",
    "AUTHORIZATION_PENDING",
    "AUTHORIZATION_STATES",
    "STOP_REASON_CANCELLED",
    "STOP_REASON_NO_PROGRESS",
    "TIER_DEEP",
    "TIER_STANDARD",
    "TIERS",
    "ResearchProgress",
    "TierAuthorization",
    "TierUpgradeRequest",
]
