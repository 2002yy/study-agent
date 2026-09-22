"""§99 P2-A2b progressive routing authority.

The single place that answers: **after this backend produced this outcome, what
does the candidate do next?**

Before A2b the answer was spread across three places - the §71C-3a escalation
path inside a read, A2a's default alternate-eligible set, and the breaker's skip -
and any two of them could decide to try another backend. From A2b there is exactly
one decision point:

::

    native read -> canonical retrieval_state (+ adequacy reason)
        -> ProgressiveRoutingAuthority
        -> exactly one next action

The authority **decides but never executes**. It makes no network call, keeps no
state, writes no ledger, and never touches evidence, support or the Gate. A2c's
scheduler and A2d's Wigolo wiring both consume its decision; until they do, the
authority is inert and today's behaviour is unchanged.

Actions
-------

``resolve``            the candidate is settled (usable content, or a terminal
                       resource outcome such as ``not_found``).
``try_backend(name)``  hand the candidate to that backend next.
``defer``              nothing is executable now, but the candidate is not
                       finished (for example every alternate is health-blocked).
``block_run``          the run can no longer schedule reads (window/budget).
``exhaust``            every allowed reader was tried or is incapable.

Capabilities, not names
-----------------------

Routing must never branch on ``if backend == "wigolo"``. Backends declare
capabilities and the matrix asks for the capability an outcome needs:

``plain_http`` · ``content_extraction`` · ``js_render`` · ``session`` ·
``anti_bot_recovery`` · ``pdf``

That is also what lets A3 plug a browser or extraction backend in without
touching the matrix.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

from src.web.research.retrieval_backends import FORBIDDEN_AUTHORITY_FIELDS

# ---------------------------------------------------------------------------
# Capability contract
# ---------------------------------------------------------------------------

CAP_PLAIN_HTTP = "plain_http"
CAP_CONTENT_EXTRACTION = "content_extraction"
CAP_JS_RENDER = "js_render"
CAP_SESSION = "session"
CAP_ANTI_BOT_RECOVERY = "anti_bot_recovery"
CAP_PDF = "pdf"

BACKEND_CAPABILITIES: tuple[str, ...] = (
    CAP_PLAIN_HTTP,
    CAP_CONTENT_EXTRACTION,
    CAP_JS_RENDER,
    CAP_SESSION,
    CAP_ANTI_BOT_RECOVERY,
    CAP_PDF,
)


@dataclass(frozen=True)
class BackendCapability:
    """What a backend can do, declared rather than inferred from its name."""

    name: str
    capabilities: frozenset[str] = frozenset()

    def supports(self, required: frozenset[str]) -> bool:
        return required.issubset(self.capabilities)

    def to_dict(self) -> dict[str, Any]:
        return {"backend": self.name, "capabilities": sorted(self.capabilities)}


#: The backends that exist today. A3 will declare a browser/extraction backend
#: here; nothing in the matrix changes because of it.
DEFAULT_BACKENDS: tuple[BackendCapability, ...] = (
    BackendCapability(
        name="native_http",
        capabilities=frozenset({CAP_PLAIN_HTTP, CAP_CONTENT_EXTRACTION}),
    ),
    BackendCapability(
        name="wigolo_http",
        capabilities=frozenset({CAP_PLAIN_HTTP, CAP_CONTENT_EXTRACTION, CAP_JS_RENDER}),
    ),
    BackendCapability(
        name="wigolo_browser",
        capabilities=frozenset(
            {
                CAP_PLAIN_HTTP,
                CAP_CONTENT_EXTRACTION,
                CAP_JS_RENDER,
                CAP_SESSION,
                CAP_ANTI_BOT_RECOVERY,
                CAP_PDF,
            }
        ),
    ),
)


def capability_registry(
    backends: Sequence[BackendCapability] | None = None,
) -> dict[str, BackendCapability]:
    return {item.name: item for item in (backends or DEFAULT_BACKENDS)}


# ---------------------------------------------------------------------------
# Backend availability (policy / provider) - NOT target health
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BackendAvailability:
    """Whether a backend may be used at all right now.

    Two distinct facts live here, and neither is about the target host:

    * ``configured`` - the backend is enabled for this deployment (a switch);
    * ``available`` - the provider itself can serve requests (a daemon that is
      down, an unconfigured client, a missing capability).

    A provider outage must **never** be recorded against
    ``(backend, target_host)`` health: the target was never contacted. A2c
    introduces availability only; provider-level health/breakers are deliberately
    not built here.
    """

    backend: str
    configured: bool = True
    available: bool = True
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "configured": bool(self.configured),
            "available": bool(self.available),
            "reason": self.reason,
        }


REASON_NOT_CAPABLE = "capability_not_satisfied"
REASON_ALREADY_ATTEMPTED = "already_attempted"
REASON_DISABLED = "disabled"
REASON_PROVIDER_UNAVAILABLE = "provider_unavailable"
REASON_UNHEALTHY = "target_health_open"
REASON_NOT_DECLARED = "backend_not_declared"


@dataclass(frozen=True)
class EligibilityInputs:
    """Everything one eligibility verdict may depend on."""

    backend: str
    required_capabilities: frozenset[str] = frozenset()
    attempted_backends: tuple[str, ...] = ()
    #: The backend that just produced the outcome; never the "next" one.
    current_backend: str = ""
    host: str = ""
    availability: Mapping[str, BackendAvailability] | None = None


@dataclass(frozen=True)
class BackendEligibility:
    """One backend's verdict, with the reason it was refused."""

    backend: str
    eligible: bool
    reason: str = ""
    capability_ok: bool = True
    already_attempted: bool = False
    configured: bool = True
    provider_available: bool = True
    health_state: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "eligible": bool(self.eligible),
            "reason": self.reason,
            "capability_ok": bool(self.capability_ok),
            "already_attempted": bool(self.already_attempted),
            "configured": bool(self.configured),
            "provider_available": bool(self.provider_available),
            "health_state": self.health_state,
        }


def backend_eligibility(
    inputs: EligibilityInputs,
    *,
    backends: Sequence[BackendCapability] | None = None,
    health_state_for: Callable[[str, str], str] | None = None,
) -> BackendEligibility:
    """The single verdict on whether one backend may be used for one candidate.

    Shared by :func:`route` (post-outcome) and :func:`schedulable_now`
    (pre-attempt), so the two phases can never disagree about capability,
    attempt history, availability or target health.
    """

    registry = capability_registry(backends)
    declaration = registry.get(inputs.backend)
    if declaration is None:
        return BackendEligibility(
            backend=inputs.backend, eligible=False, reason=REASON_NOT_DECLARED
        )

    capability_ok = declaration.supports(inputs.required_capabilities)

    tried = set(inputs.attempted_backends)
    if inputs.current_backend:
        tried.add(inputs.current_backend)
    already_attempted = inputs.backend in tried

    availability = (inputs.availability or {}).get(inputs.backend)
    configured = availability.configured if availability else True
    provider_available = availability.available if availability else True

    health_state = ""
    if health_state_for is not None and inputs.host:
        health_state = str(health_state_for(inputs.backend, inputs.host) or "")

    reason = ""
    if not capability_ok:
        reason = REASON_NOT_CAPABLE
    elif already_attempted:
        reason = REASON_ALREADY_ATTEMPTED
    elif not configured:
        reason = REASON_DISABLED
    elif not provider_available:
        reason = REASON_PROVIDER_UNAVAILABLE
    elif health_state in ("open", "cooldown"):
        reason = REASON_UNHEALTHY

    return BackendEligibility(
        backend=inputs.backend,
        eligible=not reason,
        reason=reason,
        capability_ok=capability_ok,
        already_attempted=already_attempted,
        configured=configured,
        provider_available=provider_available,
        health_state=health_state,
    )


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

ACTION_RESOLVE = "resolve"
ACTION_TRY_BACKEND = "try_backend"
ACTION_DEFER = "defer"
ACTION_BLOCK_RUN = "block_run"
ACTION_EXHAUST = "exhaust"

ROUTING_ACTIONS: tuple[str, ...] = (
    ACTION_RESOLVE,
    ACTION_TRY_BACKEND,
    ACTION_DEFER,
    ACTION_BLOCK_RUN,
    ACTION_EXHAUST,
)

REASON_USABLE_CONTENT = "usable_content"
REASON_TERMINAL_RESOURCE = "terminal_resource_outcome"
REASON_RUN_BLOCKED = "run_blocked"
REASON_ALL_TRIED = "all_backends_tried"
REASON_NO_CAPABLE = "no_capable_backend"
REASON_ALL_BLOCKED = "all_capable_backends_unhealthy"
REASON_UNSUPPORTED_CONTENT = "unsupported_content"
REASON_POLICY_SKIP = "policy_skip_other_backend"
REASON_TRANSPORT_FAILURE = "transport_failure_alternate"
REASON_ACCESS_DENIED = "access_denied_alternate"
REASON_RATE_LIMITED = "rate_limited_alternate"
REASON_RENDERED_NEEDED = "rendered_backend_required"
REASON_SESSION_NEEDED = "session_backend_required"
REASON_ANTI_BOT_NEEDED = "anti_bot_backend_required"
REASON_ADEQUACY = "adequacy_reason_routed"

# ---------------------------------------------------------------------------
# Route matrix
# ---------------------------------------------------------------------------

#: Capability an outcome needs from the *next* backend. A state absent here needs
#: only a working alternate (``plain_http``).
STATE_CAPABILITY_REQUIREMENTS: Mapping[str, frozenset[str]] = {
    "shell_page": frozenset({CAP_JS_RENDER}),
    "js_required": frozenset({CAP_JS_RENDER}),
    "anti_bot": frozenset({CAP_ANTI_BOT_RECOVERY}),
    "login_required": frozenset({CAP_SESSION}),
    "http_denied": frozenset({CAP_PLAIN_HTTP}),
    "rate_limited": frozenset({CAP_PLAIN_HTTP}),
    "invalid_content": frozenset({CAP_CONTENT_EXTRACTION}),
    "connect_failure": frozenset({CAP_PLAIN_HTTP}),
    "dns_failure": frozenset({CAP_PLAIN_HTTP}),
    "tls_failure": frozenset({CAP_PLAIN_HTTP}),
    "timeout": frozenset({CAP_PLAIN_HTTP}),
    "reset": frozenset({CAP_PLAIN_HTTP}),
    "backend_failure": frozenset({CAP_PLAIN_HTTP}),
}

#: ``invalid_content`` is too coarse on its own, so the adequacy reason refines it.
ADEQUACY_CAPABILITY_REQUIREMENTS: Mapping[str, frozenset[str]] = {
    "short_doc": frozenset({CAP_CONTENT_EXTRACTION}),
    "js_shell": frozenset({CAP_JS_RENDER}),
    "anti_bot_or_error": frozenset({CAP_ANTI_BOT_RECOVERY}),
    "malformed_binary": frozenset(),  # nothing can rescue it
}

#: Adequacy reasons that no reader can settle.
UNRECOVERABLE_ADEQUACY_REASONS = frozenset({"malformed_binary"})

#: Outcomes that settle the candidate without producing content.
TERMINAL_RESOURCE_STATES = frozenset({"not_found"})

#: Policy outcomes: the backend was not attempted.
POLICY_SKIP_STATES = frozenset({"budget_exhausted"})

TRANSPORT_STATES = frozenset(
    {
        "connect_failure",
        "dns_failure",
        "tls_failure",
        "timeout",
        "reset",
        "backend_failure",
    }
)


@dataclass(frozen=True)
class RoutingContext:
    """Everything one routing decision may depend on."""

    candidate_id: str
    current_backend: str
    retrieval_state: str
    adequacy_reason: str = ""
    attempted: bool = True
    attempted_backends: tuple[str, ...] = ()
    available_backends: tuple[str, ...] = ()
    host: str = ""
    #: Informational only: window gating stays where it already lives (the
    #: runtime's deadline policy). The router never invents a threshold.
    remaining_seconds: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "current_backend": self.current_backend,
            "retrieval_state": self.retrieval_state,
            "adequacy_reason": self.adequacy_reason,
            "attempted": self.attempted,
            "attempted_backends": list(self.attempted_backends),
            "available_backends": list(self.available_backends),
            "host": self.host,
            "remaining_seconds": self.remaining_seconds,
        }


@dataclass(frozen=True)
class RoutingDecision:
    """Exactly one next action, plus why it was chosen."""

    candidate_id: str
    action: str
    next_backend: str = ""
    reason: str = ""
    required_capabilities: frozenset[str] = field(default_factory=frozenset)
    terminal: bool = False
    usable_content: bool = False
    considered_backends: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "action": self.action,
            "next_backend": self.next_backend,
            "reason": self.reason,
            "required_capabilities": sorted(self.required_capabilities),
            "terminal": bool(self.terminal),
            "usable_content": bool(self.usable_content),
            "considered_backends": list(self.considered_backends),
        }


def _eligible(
    context: RoutingContext,
    required: frozenset[str],
    registry: Mapping[str, BackendCapability],
    health_state_for: Callable[[str, str], str] | None,
    availability: Mapping[str, BackendAvailability] | None = None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Split the untried chain into (capable and healthy, capable but unavailable).

    Delegates every per-backend question to :func:`backend_eligibility`, so the
    post-outcome router and the pre-attempt scheduler can never disagree about
    what "this backend is usable" means.
    """

    capable: list[str] = []
    blocked: list[str] = []
    for backend in context.available_backends:
        verdict = backend_eligibility(
            EligibilityInputs(
                backend=backend,
                required_capabilities=required,
                attempted_backends=context.attempted_backends,
                current_backend=context.current_backend,
                host=context.host,
                availability=availability,
            ),
            backends=tuple(registry.values()),
            health_state_for=health_state_for,
        )
        if verdict.eligible:
            capable.append(backend)
        elif verdict.reason in (REASON_UNHEALTHY, REASON_PROVIDER_UNAVAILABLE):
            blocked.append(backend)
    return tuple(capable), tuple(blocked)


def route(
    context: RoutingContext,
    *,
    backends: Sequence[BackendCapability] | None = None,
    health_state_for: Callable[[str, str], str] | None = None,
) -> RoutingDecision:
    """Decide the single next action for one candidate.

    Precedence is fixed: a settled outcome first, then a blocked run, then the
    outcome's capability requirement, then exhaustion versus deferral.
    """

    registry = capability_registry(backends)
    state = str(context.retrieval_state or "")
    adequacy = str(context.adequacy_reason or "")

    def decision(
        action: str,
        *,
        next_backend: str = "",
        reason: str = "",
        required: frozenset[str] = frozenset(),
        terminal: bool = False,
        usable: bool = False,
        considered: tuple[str, ...] = (),
    ) -> RoutingDecision:
        return RoutingDecision(
            candidate_id=context.candidate_id,
            action=action,
            next_backend=next_backend,
            reason=reason,
            required_capabilities=required,
            terminal=terminal,
            usable_content=usable,
            considered_backends=considered,
        )

    # 1. Settled outcomes.
    if state == "success":
        return decision(
            ACTION_RESOLVE,
            reason=REASON_USABLE_CONTENT,
            terminal=True,
            usable=True,
        )
    if state in TERMINAL_RESOURCE_STATES:
        return decision(
            ACTION_RESOLVE,
            reason=REASON_TERMINAL_RESOURCE,
            terminal=True,
            usable=False,
        )

    # 2. The run cannot schedule anything.
    if state in POLICY_SKIP_STATES:
        return decision(ACTION_BLOCK_RUN, reason=REASON_RUN_BLOCKED)

    # 3. Unrecoverable content shapes never route anywhere.
    if state == "invalid_content" and adequacy in UNRECOVERABLE_ADEQUACY_REASONS:
        return decision(ACTION_EXHAUST, reason=REASON_UNSUPPORTED_CONTENT, terminal=True)

    # 4. What does this outcome need from the next backend?
    required = STATE_CAPABILITY_REQUIREMENTS.get(state, frozenset())
    reason = {
        "shell_page": REASON_RENDERED_NEEDED,
        "js_required": REASON_RENDERED_NEEDED,
        "anti_bot": REASON_ANTI_BOT_NEEDED,
        "login_required": REASON_SESSION_NEEDED,
        "http_denied": REASON_ACCESS_DENIED,
        "rate_limited": REASON_RATE_LIMITED,
    }.get(state, "")
    if state in TRANSPORT_STATES:
        reason = REASON_TRANSPORT_FAILURE
    if state == "invalid_content":
        required = ADEQUACY_CAPABILITY_REQUIREMENTS.get(adequacy, required)
        reason = REASON_ADEQUACY if adequacy else REASON_TRANSPORT_FAILURE
    if not context.attempted and not reason:
        # A policy skip: the backend was never tried, so try another one.
        reason = REASON_POLICY_SKIP

    capable, blocked = _eligible(context, required, registry, health_state_for)

    # 5. Exhaustion versus deferral.
    if capable:
        return decision(
            ACTION_TRY_BACKEND,
            next_backend=capable[0],
            reason=reason or REASON_TRANSPORT_FAILURE,
            required=required,
            considered=capable,
        )
    if blocked:
        # Something could help, but it is unhealthy right now: the candidate is
        # deferred, not finished.
        return decision(
            ACTION_DEFER,
            reason=REASON_ALL_BLOCKED,
            required=required,
            considered=blocked,
        )
    untried_any = [
        backend
        for backend in context.available_backends
        if backend not in set(context.attempted_backends)
        and backend != context.current_backend
    ]
    if untried_any:
        # Backends remain but none has the capability this outcome needs.
        return decision(
            ACTION_EXHAUST,
            reason=REASON_NO_CAPABLE,
            required=required,
            terminal=True,
            considered=tuple(untried_any),
        )
    return decision(ACTION_EXHAUST, reason=REASON_ALL_TRIED, terminal=True)


def assert_no_authority_fields(payload: Mapping[str, Any]) -> None:
    """Routing decisions may never carry local authority (§71B rule)."""

    forbidden = FORBIDDEN_AUTHORITY_FIELDS.intersection(payload)
    if forbidden:
        raise ValueError(
            "routing payload may not carry local authority fields: "
            + ", ".join(sorted(forbidden))
        )


# ---------------------------------------------------------------------------
# Pre-attempt scheduling
# ---------------------------------------------------------------------------

ACTION_SCHEDULE = "schedule"

SCHEDULING_ACTIONS: tuple[str, ...] = (
    ACTION_SCHEDULE,
    ACTION_DEFER,
    ACTION_BLOCK_RUN,
    ACTION_EXHAUST,
)


@dataclass(frozen=True)
class SchedulingContext:
    """Pre-attempt inputs: no backend has produced an outcome yet.

    This is deliberately a different shape from :class:`RoutingContext`: there is
    no ``retrieval_state`` to interpret and no ``current_backend`` outcome. The
    chain order expresses preference.
    """

    candidate_id: str
    available_backends: tuple[str, ...] = ()
    attempted_backends: tuple[str, ...] = ()
    host: str = ""
    run_blocked: bool = False
    required_capabilities: frozenset[str] = frozenset()
    availability: Mapping[str, BackendAvailability] | None = None
    remaining_seconds: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "available_backends": list(self.available_backends),
            "attempted_backends": list(self.attempted_backends),
            "host": self.host,
            "run_blocked": bool(self.run_blocked),
            "required_capabilities": sorted(self.required_capabilities),
            "remaining_seconds": self.remaining_seconds,
        }


@dataclass(frozen=True)
class SchedulingDecision:
    """What may be executed right now - never a read outcome.

    ``defer``, ``block_run`` and ``exhaust`` mean no attempt happened, so they
    must not create a ``RuntimeReadOutcome``; they are policy provenance only.
    """

    candidate_id: str
    action: str
    backend: str = ""
    reason: str = ""
    considered_backends: tuple[str, ...] = ()
    blocked_backends: tuple[str, ...] = ()
    verdicts: tuple[dict[str, Any], ...] = ()

    @property
    def executable(self) -> bool:
        return self.action == ACTION_SCHEDULE

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "action": self.action,
            "backend": self.backend,
            "reason": self.reason,
            "considered_backends": list(self.considered_backends),
            "blocked_backends": list(self.blocked_backends),
            "verdicts": [dict(item) for item in self.verdicts],
        }


REASON_SCHEDULED = "first_eligible_backend"
REASON_ALL_BLOCKED_SCHEDULING = "all_backends_unavailable"
REASON_NO_ELIGIBLE = "no_eligible_backend"


def schedulable_now(
    context: SchedulingContext,
    *,
    backends: Sequence[BackendCapability] | None = None,
    health_state_for: Callable[[str, str], str] | None = None,
) -> SchedulingDecision:
    """Pick the backend to execute now, or say why none can be.

    Uses the same :func:`backend_eligibility` verdict as :func:`route`, so a
    backend the router would consider is a backend the scheduler would consider.
    """

    if context.run_blocked:
        return SchedulingDecision(
            candidate_id=context.candidate_id,
            action=ACTION_BLOCK_RUN,
            reason=REASON_RUN_BLOCKED,
        )

    verdicts = tuple(
        backend_eligibility(
            EligibilityInputs(
                backend=backend,
                required_capabilities=context.required_capabilities,
                attempted_backends=context.attempted_backends,
                host=context.host,
                availability=context.availability,
            ),
            backends=backends,
            health_state_for=health_state_for,
        )
        for backend in context.available_backends
    )
    considered = tuple(item.backend for item in verdicts if item.eligible)
    blocked = tuple(
        item.backend
        for item in verdicts
        if item.reason in (REASON_UNHEALTHY, REASON_PROVIDER_UNAVAILABLE)
    )
    if considered:
        return SchedulingDecision(
            candidate_id=context.candidate_id,
            action=ACTION_SCHEDULE,
            backend=considered[0],
            reason=REASON_SCHEDULED,
            considered_backends=considered,
            blocked_backends=blocked,
            verdicts=tuple(item.to_dict() for item in verdicts),
        )
    if blocked:
        # Something could serve this candidate later, but not now.
        return SchedulingDecision(
            candidate_id=context.candidate_id,
            action=ACTION_DEFER,
            reason=REASON_ALL_BLOCKED_SCHEDULING,
            blocked_backends=blocked,
            verdicts=tuple(item.to_dict() for item in verdicts),
        )
    return SchedulingDecision(
        candidate_id=context.candidate_id,
        action=ACTION_EXHAUST,
        reason=REASON_NO_ELIGIBLE,
        verdicts=tuple(item.to_dict() for item in verdicts),
    )


__all__ = [
    "ACTION_BLOCK_RUN",
    "ACTION_DEFER",
    "ACTION_EXHAUST",
    "ACTION_RESOLVE",
    "ACTION_SCHEDULE",
    "ACTION_TRY_BACKEND",
    "ADEQUACY_CAPABILITY_REQUIREMENTS",
    "BACKEND_CAPABILITIES",
    "CAP_ANTI_BOT_RECOVERY",
    "CAP_CONTENT_EXTRACTION",
    "CAP_JS_RENDER",
    "CAP_PDF",
    "CAP_PLAIN_HTTP",
    "CAP_SESSION",
    "DEFAULT_BACKENDS",
    "REASON_ALL_BLOCKED_SCHEDULING",
    "REASON_NO_ELIGIBLE",
    "REASON_SCHEDULED",
    "ROUTING_ACTIONS",
    "SCHEDULING_ACTIONS",
    "STATE_CAPABILITY_REQUIREMENTS",
    "TERMINAL_RESOURCE_STATES",
    "TRANSPORT_STATES",
    "BackendAvailability",
    "BackendCapability",
    "BackendEligibility",
    "EligibilityInputs",
    "RoutingContext",
    "RoutingDecision",
    "SchedulingContext",
    "SchedulingDecision",
    "assert_no_authority_fields",
    "backend_eligibility",
    "capability_registry",
    "route",
    "schedulable_now",
]
