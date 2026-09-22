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
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Split the untried chain into (capable and healthy, capable but unhealthy)."""

    tried = set(context.attempted_backends)
    # The current backend just produced this outcome - whether it was attempted
    # or policy-skipped, it is not the *next* backend.
    if context.current_backend:
        tried.add(context.current_backend)
    capable: list[str] = []
    blocked: list[str] = []
    for backend in context.available_backends:
        if backend in tried:
            continue
        declaration = registry.get(backend)
        if declaration is None or not declaration.supports(required):
            continue
        state = ""
        if health_state_for is not None and context.host:
            state = str(health_state_for(backend, context.host) or "")
        if state in ("open", "cooldown"):
            blocked.append(backend)
        else:
            capable.append(backend)
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


__all__ = [
    "ACTION_BLOCK_RUN",
    "ACTION_DEFER",
    "ACTION_EXHAUST",
    "ACTION_RESOLVE",
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
    "ROUTING_ACTIONS",
    "STATE_CAPABILITY_REQUIREMENTS",
    "TERMINAL_RESOURCE_STATES",
    "TRANSPORT_STATES",
    "BackendCapability",
    "RoutingContext",
    "RoutingDecision",
    "assert_no_authority_fields",
    "capability_registry",
    "route",
]
