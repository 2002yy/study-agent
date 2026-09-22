"""§98 P2-A2a candidate resolution contract.

Fixes a semantic error that A1a merely exposed::

    read_outcome exists  !=  candidate completed

A read outcome is the **history of one backend attempt or policy decision**. It
answers "what did a backend do with this candidate?", and nothing more. Whether
the candidate is *finished* is a different question, because the reader chain may
still have a legitimate next backend::

    candidate
        -> backend attempt / policy decision
        -> is there still a legal fallback?
             YES -> not completed (fallback pending / policy deferred)
             NO  -> terminal (resolved, or chain exhausted)

Five lifecycle states
---------------------

``resolved``          a backend produced a usable result, or the resource is
                      truthfully terminal (``not_found``).
``fallback_pending``  this backend did not settle the candidate and another
                      backend in the chain may still try it.
``policy_deferred``   the backend was **not** attempted (circuit open, backend
                      disabled); the candidate is untouched, not finished.
``run_blocked``       the run can no longer schedule it (window/budget). It is
                      *not* a content fact about the URL, and it must never be
                      dressed up as a completed read.
``chain_exhausted``   every allowed reader has been tried and none settled it.

Two rules are frozen here:

* ``read_outcome`` is history; only this module decides lifecycle.
* A policy skip may never consume a candidate, and may never become a claim
  about the URL.

This module is pure: it reads outcomes plus a backend chain and returns
resolutions. It owns no state, writes no ledger, and never touches evidence,
support or the Gate. A2a deliberately does not wire any alternate backend: the
default chain is the single reader the runtime already uses, so behaviour is
unchanged until A2b/A2d extend the chain.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Sequence

# ---------------------------------------------------------------------------
# Lifecycle vocabulary
# ---------------------------------------------------------------------------

RESOLVED = "resolved"
FALLBACK_PENDING = "fallback_pending"
POLICY_DEFERRED = "policy_deferred"
RUN_BLOCKED = "run_blocked"
CHAIN_EXHAUSTED = "chain_exhausted"

RESOLUTION_STATES: tuple[str, ...] = (
    RESOLVED,
    FALLBACK_PENDING,
    POLICY_DEFERRED,
    RUN_BLOCKED,
    CHAIN_EXHAUSTED,
)

#: The reader chain the runtime actually has today. A2b/A2d will extend it (for
#: example with the existing Wigolo reader); nothing else changes because of it.
DEFAULT_READER_CHAIN: tuple[str, ...] = ("native_http",)

#: Canonical states after which the resource itself is settled.
TERMINAL_STATES = frozenset({"success", "not_found"})

#: Canonical states that another backend may still settle.
ALTERNATE_ELIGIBLE_STATES = frozenset(
    {
        "shell_page",
        "js_required",
        "anti_bot",
        "login_required",
        "http_denied",
        "rate_limited",
        "invalid_content",
        "connect_failure",
        "dns_failure",
        "tls_failure",
        "timeout",
        "reset",
        "backend_failure",
    }
)

#: Canonical state of a run that can no longer schedule reads.
RUN_BLOCKED_STATE = "budget_exhausted"

SKIP_PREFIX = "read_skipped:"
FAILED_ERROR_CODE = "read_failed"


@dataclass(frozen=True)
class AttemptFact:
    """One durable attempt fact, as read from the cursor."""

    backend: str
    retrieval_state: str
    attempted: bool
    status: str
    error_code: str = ""

    @property
    def settled(self) -> bool:
        return bool(self.attempted) and self.retrieval_state in TERMINAL_STATES

    @property
    def needs_alternate(self) -> bool:
        return bool(self.attempted) and self.retrieval_state in ALTERNATE_ELIGIBLE_STATES

    @property
    def blocked_run(self) -> bool:
        return self.retrieval_state == RUN_BLOCKED_STATE

    @property
    def skipped(self) -> bool:
        return not self.attempted


@dataclass(frozen=True)
class CandidateResolution:
    """The lifecycle of one candidate, plus why it is where it is."""

    candidate_id: str
    state: str
    attempted_backends: tuple[str, ...] = ()
    remaining_backends: tuple[str, ...] = ()
    last_state: str = ""
    last_backend: str = ""
    skip_reason: str = ""

    @property
    def terminal(self) -> bool:
        """The reader chain has reached its end (the old ``completed``)."""

        return self.state in (RESOLVED, CHAIN_EXHAUSTED)

    @property
    def reschedulable(self) -> bool:
        """May this run still plan a read for it?"""

        return self.state in (FALLBACK_PENDING, POLICY_DEFERRED)

    @property
    def may_try_another_backend(self) -> bool:
        return self.state == FALLBACK_PENDING

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "state": self.state,
            "terminal": self.terminal,
            "reschedulable": self.reschedulable,
            "attempted_backends": list(self.attempted_backends),
            "remaining_backends": list(self.remaining_backends),
            "last_state": self.last_state,
            "last_backend": self.last_backend,
            "skip_reason": self.skip_reason,
        }


def skip_reason_from_error_code(error_code: str) -> str:
    """Recover the policy reason from a skipped outcome (bounded token)."""

    text = str(error_code or "")
    if not text.startswith(SKIP_PREFIX):
        return ""
    return text[len(SKIP_PREFIX) :][:120]


def error_code_for_skip(skip_reason: str) -> str:
    """Durable token for a policy skip, leaving real failures unchanged."""

    return f"{SKIP_PREFIX}{str(skip_reason or '')[:120]}"


def attempt_fact_from_outcome(outcome: Any) -> AttemptFact:
    """Build one attempt fact from a ``RuntimeReadOutcome`` (or a mapping)."""

    if isinstance(outcome, Mapping):
        get = outcome.get
    else:
        get = lambda key, default=None: getattr(outcome, key, default)  # noqa: E731
    retrieval_state = str(get("retrieval_state", "") or "")
    attempted = get("attempted", None)
    if attempted is None:
        # Legacy rows predate the flag: a recorded outcome meant a real attempt.
        attempted = True
    status = str(get("status", "") or "")
    if status == "success":
        retrieval_state = retrieval_state or "success"
    elif not retrieval_state:
        retrieval_state = "backend_failure"
    return AttemptFact(
        backend=str(get("backend", "") or ""),
        retrieval_state=retrieval_state,
        attempted=bool(attempted),
        status=status,
        error_code=str(get("error_code", "") or ""),
    )


def resolve_candidate(
    candidate_id: str,
    facts: Sequence[AttemptFact],
    *,
    backend_chain: Sequence[str] = DEFAULT_READER_CHAIN,
    health_state_for: Callable[[str, str], str] | None = None,
    host: str = "",
) -> CandidateResolution:
    """Decide one candidate's lifecycle from its attempt history."""

    chain = tuple(dict.fromkeys(str(item) for item in backend_chain if str(item)))
    attempted_backends = tuple(
        dict.fromkeys(fact.backend for fact in facts if fact.attempted and fact.backend)
    )
    untried = tuple(item for item in chain if item not in attempted_backends)
    remaining = _eligible_remaining(
        untried, host=host, health_state_for=health_state_for
    )

    # A settled attempt wins outright: nothing later may unsettle it.
    for fact in facts:
        if fact.settled:
            return CandidateResolution(
                candidate_id=candidate_id,
                state=RESOLVED,
                attempted_backends=attempted_backends,
                remaining_backends=remaining,
                last_state=fact.retrieval_state,
                last_backend=fact.backend,
            )

    last = facts[-1] if facts else None
    if last is None:
        # Never attempted. If the chain still has a usable backend it is ahead of
        # it; if the only backends are health-blocked it is deferred (not done);
        # only an empty chain is truly exhausted.
        if remaining:
            state = FALLBACK_PENDING
        elif untried:
            state = POLICY_DEFERRED
        else:
            state = CHAIN_EXHAUSTED
        return CandidateResolution(
            candidate_id=candidate_id,
            state=state,
            remaining_backends=remaining,
        )

    skip_reason = skip_reason_from_error_code(last.error_code)

    if last.blocked_run:
        # The run ran out of window/budget. Not a content fact, not completed.
        return CandidateResolution(
            candidate_id=candidate_id,
            state=RUN_BLOCKED,
            attempted_backends=attempted_backends,
            remaining_backends=remaining,
            last_state=last.retrieval_state,
            last_backend=last.backend,
            skip_reason=skip_reason,
        )

    if last.needs_alternate:
        return CandidateResolution(
            candidate_id=candidate_id,
            state=FALLBACK_PENDING if remaining else CHAIN_EXHAUSTED,
            attempted_backends=attempted_backends,
            remaining_backends=remaining,
            last_state=last.retrieval_state,
            last_backend=last.backend,
        )

    # A policy skip: the backend was never attempted, so the candidate is
    # untouched. It may still be tried (here or by another backend).
    if remaining:
        state = FALLBACK_PENDING
    elif untried:
        state = POLICY_DEFERRED
    else:
        state = CHAIN_EXHAUSTED
    return CandidateResolution(
        candidate_id=candidate_id,
        state=state,
        attempted_backends=attempted_backends,
        remaining_backends=remaining,
        last_state=last.retrieval_state,
        last_backend=last.backend,
        skip_reason=skip_reason,
    )


def _eligible_remaining(
    remaining: Sequence[str],
    *,
    host: str,
    health_state_for: Callable[[str, str], str] | None,
) -> tuple[str, ...]:
    """Filter the remaining chain by health (A2c supplies the callable).

    Without a health callable nothing is filtered: A2a does not make scheduling
    decisions, it only reports what is still legally available.
    """

    if health_state_for is None or not host:
        return tuple(remaining)
    eligible = []
    for backend in remaining:
        state = str(health_state_for(backend, host) or "")
        if state in ("", "closed", "half_open"):
            eligible.append(backend)
    return tuple(eligible)


def resolve_candidates(
    facts_by_candidate: Mapping[str, Sequence[AttemptFact]],
    *,
    backend_chain: Sequence[str] = DEFAULT_READER_CHAIN,
    health_state_for: Callable[[str, str], str] | None = None,
    hosts_by_candidate: Mapping[str, str] | None = None,
) -> dict[str, CandidateResolution]:
    """Resolve every candidate that has any attempt history."""

    hosts = hosts_by_candidate or {}
    return {
        candidate_id: resolve_candidate(
            candidate_id,
            facts,
            backend_chain=backend_chain,
            health_state_for=health_state_for,
            host=str(hosts.get(candidate_id) or ""),
        )
        for candidate_id, facts in facts_by_candidate.items()
    }


def group_facts_by_candidate(outcomes: Iterable[Any]) -> dict[str, list[AttemptFact]]:
    """Group read outcomes into per-candidate attempt history (order kept)."""

    grouped: dict[str, list[AttemptFact]] = {}
    for outcome in outcomes:
        candidate_id = str(
            outcome.get("candidate_id")
            if isinstance(outcome, Mapping)
            else getattr(outcome, "candidate_id", "")
        )
        if not candidate_id:
            continue
        grouped.setdefault(candidate_id, []).append(attempt_fact_from_outcome(outcome))
    return grouped


def terminal_candidate_ids(
    outcomes: Iterable[Any],
    *,
    backend_chain: Sequence[str] = DEFAULT_READER_CHAIN,
) -> tuple[str, ...]:
    """The single definition of "this candidate's reader chain has ended"."""

    grouped = group_facts_by_candidate(outcomes)
    resolved = resolve_candidates(grouped, backend_chain=backend_chain)
    return tuple(
        candidate_id
        for candidate_id, resolution in resolved.items()
        if resolution.terminal
    )


def resolution_summary(
    outcomes: Iterable[Any],
    *,
    backend_chain: Sequence[str] = DEFAULT_READER_CHAIN,
) -> dict[str, Any]:
    """Diagnostics: how many candidates sit in each lifecycle state."""

    grouped = group_facts_by_candidate(outcomes)
    resolved = resolve_candidates(grouped, backend_chain=backend_chain)
    counts: dict[str, int] = {state: 0 for state in RESOLUTION_STATES}
    for resolution in resolved.values():
        counts[resolution.state] = counts.get(resolution.state, 0) + 1
    return {
        "candidates": len(resolved),
        "counts": counts,
        "deferred": sorted(
            candidate_id
            for candidate_id, resolution in resolved.items()
            if resolution.state in (POLICY_DEFERRED, FALLBACK_PENDING)
        )[:40],
    }


__all__ = [
    "ALTERNATE_ELIGIBLE_STATES",
    "AttemptFact",
    "CHAIN_EXHAUSTED",
    "CandidateResolution",
    "DEFAULT_READER_CHAIN",
    "FAILED_ERROR_CODE",
    "FALLBACK_PENDING",
    "POLICY_DEFERRED",
    "RESOLUTION_STATES",
    "RESOLVED",
    "RUN_BLOCKED",
    "RUN_BLOCKED_STATE",
    "SKIP_PREFIX",
    "TERMINAL_STATES",
    "attempt_fact_from_outcome",
    "error_code_for_skip",
    "group_facts_by_candidate",
    "resolve_candidate",
    "resolve_candidates",
    "resolution_summary",
    "skip_reason_from_error_code",
    "terminal_candidate_ids",
]
