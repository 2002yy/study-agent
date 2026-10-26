"""CL-M3 QD-3a: the durable shape of a research that can outlive its process.

The bounded loop and ``SemanticResearchHost`` both assume a process that keeps running. The
moment a research may survive a restart, two questions appear that no in-memory object can
answer: *what actually happened so far* and *which worker is allowed to continue it*. This
module is the vocabulary for those two answers and nothing else - it holds no clock, opens
no database and decides no policy.

Three shapes, each because of a failure mode that was observed rather than imagined.

**The round log is the evidence.** ``ResearchEpisode`` is a *planning* context: §7.5 of the
contract records that it drops ``attempts`` and ``source_leads`` when serialising past
``CONTEXT_CAP``. Persisting the episode and calling it a checkpoint would therefore lose
observations precisely when there are a lot of them - the opposite of the requirement. So
completed rounds are kept append-only, each with its own queries, URLs and facts, and the
state row keeps only the last round's facts as the seed for the next one.

**Quota is an observation.** ``quota_observed`` records what was left when the checkpoint
was written, for planning and for a receipt. It is not the authority - #259's ledger is -
and this module makes the only safe assumption about it: a later checkpoint may lower those
numbers but never raise them. A resumed worker that could raise its own budget would be a
refund with extra steps.

**Identity is derived, not stored.** ``research_request_key`` is a pure function of
``(research_id, round_index, stage)``. Because it does not depend on anything a restart can
lose, replaying a round maps to the key the real ledger already saw, and its
``UNIQUE(experiment_id, request_key)`` rejects the duplicate. Storing the keys instead would
create a second, driftable answer to "was this already paid for".
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Mapping

TIER_STANDARD = "standard"
TIER_DEEP = "deep"
TIERS = frozenset({TIER_STANDARD, TIER_DEEP})

# A research is "running" while a worker holds the lease, "checkpointed" when it is between
# rounds and safe to resume, and the three terminal states below when nothing may continue
# it. ``stopped`` is a normal end (evidence sufficient, no progress, quota); ``cancelled``
# is the user's decision and ``failed`` is an outcome nobody chose.
STATE_RUNNING = "running"
STATE_CHECKPOINTED = "checkpointed"
STATE_STOPPED = "stopped"
STATE_CANCELLED = "cancelled"
STATE_FAILED = "failed"
STATES = frozenset(
    {
        STATE_RUNNING,
        STATE_CHECKPOINTED,
        STATE_STOPPED,
        STATE_CANCELLED,
        STATE_FAILED,
    }
)
TERMINAL_STATES = frozenset({STATE_STOPPED, STATE_CANCELLED, STATE_FAILED})

# Ready to be picked up by a scan: between rounds, or owned by a worker whose lease may
# still be alive (the scan decides that from the timestamp, not from this set).
RESUMABLE_STATES = frozenset({STATE_RUNNING, STATE_CHECKPOINTED})

# The four non-monetary budgets of §10.5. Cost is deliberately absent: it belongs to the
# ledger, and accepting a ``cost`` key here would invite a second place to count money.
QUOTA_KEYS = frozenset({"searches", "reads", "decisions", "tokens"})

# Per-round bounds. Exceeding one is an error rather than a truncation: a checkpoint that
# silently dropped half a round's sources would look complete and be wrong.
MAX_QUERIES_PER_ROUND = 8
MAX_URLS_PER_ROUND = 32
MAX_FACTS_PER_ROUND = 64
# Folded across rounds for resumption. Reaching this is a signal to raise the bound rather
# than to start discarding what earlier rounds found.
MAX_FOLDED_FACTS = 512

_STAGE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

RESEARCH_REQUEST_SCHEMA = "research-round-request-v1"


def _text(value: Any, name: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"invalid_{name}")
    return value


def _identity(value: Any, name: str) -> str:
    return _text(value, name, 160)


def _count(value: Any, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"invalid_{name}")
    return value


def _strings(values: Any, name: str, limit: int, cap: int) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, (list, tuple)):
        raise ValueError(f"invalid_{name}")
    rows = tuple(values)
    if len(rows) > cap:
        raise ValueError(f"{name}_exceeds_round_cap")
    out: list[str] = []
    for row in rows:
        if not isinstance(row, str) or not row.strip() or len(row) > limit:
            raise ValueError(f"invalid_{name}_entry")
        out.append(row)
    # A tuple, not the list above: these fields live on frozen dataclasses, and a mutable
    # list there would be an escape hatch out of the immutability the rest of the code
    # relies on when it hands a checkpoint to another worker.
    return tuple(out)


def quota(observed: Mapping[str, Any] | None) -> dict[str, int]:
    """Validate a quota observation. Unknown keys are rejected, not ignored.

    A misspelled key would otherwise sit in the row doing nothing while the budget it was
    meant to bound went unrecorded, which is the quiet version of losing a limit.
    """
    if observed is None:
        return {}
    if not isinstance(observed, Mapping):
        raise ValueError("invalid_quota")
    out: dict[str, int] = {}
    for key, value in observed.items():
        if key not in QUOTA_KEYS:
            raise ValueError(f"unknown_quota_key:{key}")
        out[str(key)] = _count(value, "quota_value")
    return out


def research_request_key(research_id: str, round_index: int, stage: str) -> str:
    """The admission identity one call in one round always has, in any process.

    Derived rather than recorded, so a restart cannot invent a new identity for work that
    was already paid for. The real ledger rejects the duplicate on its own unique key.
    """
    _identity(research_id, "research_id")
    _count(round_index, "round_index")
    if not isinstance(stage, str) or not _STAGE.match(stage):
        raise ValueError("invalid_research_stage")
    raw = json.dumps(
        [RESEARCH_REQUEST_SCHEMA, research_id, round_index, stage],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return "research:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ResearchRound:
    """One finished round, as it is written down. Append-only once stored."""

    research_id: str
    round_index: int
    question: str
    queries: tuple[str, ...] = ()
    observation_urls: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    stop_reason: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        _identity(self.research_id, "research_id")
        _count(self.round_index, "round_index")
        _text(self.question, "question", 4096)
        object.__setattr__(
            self, "queries", _strings(self.queries, "queries", 500, MAX_QUERIES_PER_ROUND)
        )
        object.__setattr__(
            self,
            "observation_urls",
            _strings(self.observation_urls, "observation_urls", 2048, MAX_URLS_PER_ROUND),
        )
        object.__setattr__(
            self,
            "evidence",
            _strings(self.evidence, "evidence", 4000, MAX_FACTS_PER_ROUND),
        )
        if not isinstance(self.stop_reason, str) or len(self.stop_reason) > 200:
            raise ValueError("invalid_stop_reason")

    def to_json(self) -> dict[str, Any]:
        return {
            "round_index": self.round_index,
            "question": self.question,
            "queries": list(self.queries),
            "observation_urls": list(self.observation_urls),
            "evidence": list(self.evidence),
            "stop_reason": self.stop_reason,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class ResearchState:
    """Where a research is, what it may spend, and which worker owns it."""

    research_id: str
    thread_id: str
    operation_id: str
    original_question: str
    question: str
    tier: str
    round_index: int = 0
    status: str = STATE_RUNNING
    stop_reason: str = ""
    evidence: tuple[str, ...] = ()
    quota_observed: Mapping[str, int] = field(default_factory=dict)
    state_version: int = 1
    lease_owner: str = ""
    lease_expires_at: str = ""
    fencing_token: int = 0
    created_at: str = ""
    updated_at: str = ""
    # QD-3d. The moment the user cancelled, if they did. It is a fact about
    # the research now, so it lives on the state row: the worker that picks
    # the research up next is a different process, and it is the one that
    # would otherwise start the next model call.
    cancel_requested_at: str = ""
    # Whether this research's tier was raised under a recorded authorisation.
    # A receipt, not the authority - the authority is the authorisation row.
    tier_upgrade_authorized: bool = False
    # Calls that were dispatched and whose outcome is not yet known. Kept so a
    # cancellation cannot make an in-flight request look like it never
    # happened: it may have run on the server, and it may have been billed.
    in_flight_calls: int = 0
    observed_calls: int = 0

    def __post_init__(self) -> None:
        _identity(self.research_id, "research_id")
        _identity(self.thread_id, "thread_id")
        _identity(self.operation_id, "operation_id")
        _text(self.original_question, "original_question", 4096)
        _text(self.question, "question", 4096)
        if self.tier not in TIERS:
            raise ValueError("invalid_tier")
        _count(self.round_index, "round_index")
        if self.status not in STATES:
            raise ValueError("invalid_status")
        if not isinstance(self.stop_reason, str) or len(self.stop_reason) > 200:
            raise ValueError("invalid_stop_reason")
        object.__setattr__(
            self, "evidence", _strings(self.evidence, "evidence", 4000, MAX_FACTS_PER_ROUND)
        )
        object.__setattr__(self, "quota_observed", quota(self.quota_observed))
        if type(self.state_version) is not int or self.state_version < 1:
            raise ValueError("invalid_state_version")
        _count(self.fencing_token, "fencing_token")
        _count(self.in_flight_calls, "in_flight_calls")
        _count(self.observed_calls, "observed_calls")
        for name in (
            "lease_owner",
            "lease_expires_at",
            "created_at",
            "updated_at",
            "cancel_requested_at",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or len(value) > 200:
                raise ValueError(f"invalid_{name}")

    @property
    def cancelled(self) -> bool:
        """Whether the user has cancelled this research.

        Read from the cancellation timestamp rather than from the status, so
        that a research which was cancelled and whose status was later
        written by something else is still recognised as cancelled. The
        status is what the *world* sees; this is what the *decision* was.
        """

        return self.cancel_requested_at != ""

    @property
    def next_round_index(self) -> int:
        """The round a resumed worker must run. Never the one that already finished."""
        return self.round_index

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL_STATES

    def owned_by(self, owner: str, fencing_token: int) -> bool:
        """Whether this snapshot still carries the right to write.

        Both halves matter. The owner string catches "a different worker took over"; the
        token catches "the same worker name re-acquired after its lease expired", which the
        owner string alone would happily accept.
        """
        return (
            isinstance(owner, str)
            and owner != ""
            and self.lease_owner == owner
            and self.fencing_token == fencing_token
        )


@dataclass(frozen=True)
class ResearchResume:
    """Everything a fresh worker needs to continue without redoing the first round."""

    state: ResearchState
    rounds: tuple[ResearchRound, ...]

    @property
    def next_round_index(self) -> int:
        return self.state.next_round_index

    @property
    def evidence(self) -> tuple[str, ...]:
        """Facts from every finished round, in round order."""

        folded: list[str] = []
        for record in self.rounds:
            folded.extend(record.evidence)
        if len(folded) > MAX_FOLDED_FACTS:
            raise ValueError("research_evidence_overflow")
        return tuple(folded)

    @property
    def executed_queries(self) -> tuple[str, ...]:
        """Queries already spent. A resume that repeats one of these is paying twice."""

        seen: list[str] = []
        for record in self.rounds:
            for query in record.queries:
                if query not in seen:
                    seen.append(query)
        return tuple(seen)

    @property
    def cancelled(self) -> bool:
        """Whether this research was cancelled by the user."""

        return self.state.cancelled

    @property
    def may_start_new_call(self) -> bool:
        """Whether a worker may dispatch another external call for this research.

        The single guard the executor checks before it spends anything. It is
        a property of the durable state rather than of a parameter, so it
        cannot be forgotten at one call site and remembered at another.
        """

        return not self.state.cancelled and not self.state.terminal

    @property
    def in_flight_calls(self) -> int:
        """Calls that were dispatched and whose outcome is unknown."""

        return self.state.in_flight_calls

    @property
    def observed_calls(self) -> int:
        """Calls that were dispatched, whether or not they have come back."""

        return self.state.observed_calls
