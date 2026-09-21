"""§94 P2-A0 retrieval outcome contract: one language for "what happened".

Every retrieval backend speaks its own dialect: an HTTP client raises
``URLError``, a rendered fetcher reports ``fetch_method``, a local reader reports
a content *shape*, and a policy layer decides not to try at all. Downstream
policy (circuit breaker, progressive reader, browser escalation) must never
branch on those dialects, or every new backend grows another ``if provider ==``.

This module is the single translation point::

    backend raw outcome
          -> failure_taxonomy.classify()
          -> canonical retrieval state
          -> runtime policy

Frozen boundaries
-----------------

1. **Canonical state is about one retrieval**, never about the URL's worth. A
   state may only claim what this attempt actually observed.
2. **Unknown failures fail closed** to ``backend_failure``. An unrecognised
   error can never become ``success``, and can never become a content judgement.
3. **A skipped attempt is not an observation.** When ``attempted`` is false the
   state may only be a policy state (``backend_failure`` + ``skip_reason`` or
   ``budget_exhausted``); the URL was never read, so no ``not_found`` /
   ``invalid_content`` / ``http_denied`` style claim may be produced. This is
   the ``host health != URL truth`` invariant.
4. **No authority.** Nothing here may write evidence, support, relevance or Gate
   fields; the §71B ``FORBIDDEN_AUTHORITY_FIELDS`` rule still holds.
5. **No policy.** This module defines the vocabulary and the state model only.
   It never opens a circuit, shortens a timeout or reorders a read; A1 owns
   behaviour, and A1's first version is per-run ``(backend, host)`` memory only.

Two vocabularies, one bridge
----------------------------

§71B already has *invocation lifecycle* states (``ok`` / ``timeout`` /
``http_error`` / ``unsupported`` / ``skipped_no_budget`` ...) that describe the
ledger entry. Those are not replaced here: :func:`from_invocation_state` bridges
them into the canonical vocabulary so the two cannot drift apart.

Where a raw signal genuinely cannot resolve the cause, the bridge stays
fail-closed and keeps the raw value in ``raw_state``::

    http_error (no status code)   -> backend_failure   (raw_state=http_error)
    unsupported + detail=circuit_open -> backend_failure + skip_reason=circuit_open
    unsupported + detail=preflight:*  -> backend_failure + skip_reason=preflight
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from src.web.research.read_adequacy import ADEQUATE_SHAPE, FAILED_SHAPE
from src.web.research.retrieval_backends import (
    FORBIDDEN_AUTHORITY_FIELDS,
    RetrievalContractError,
)

# ---------------------------------------------------------------------------
# Canonical vocabulary
# ---------------------------------------------------------------------------

SUCCESS_STATE = "success"
UNKNOWN_STATE = "backend_failure"

#: The canonical retrieval states. Deliberately a closed set: a new backend must
#: project onto one of these rather than adding a state of its own.
RETRIEVAL_STATES: tuple[str, ...] = (
    "success",
    "not_found",
    "http_denied",
    "rate_limited",
    "connect_failure",
    "dns_failure",
    "tls_failure",
    "timeout",
    "reset",
    "invalid_content",
    "shell_page",
    "js_required",
    "login_required",
    "anti_bot",
    "backend_failure",
    "budget_exhausted",
)

#: States that make a claim about the *resource*. A skipped attempt may never
#: produce one of these, because nothing was observed.
CONTENT_JUDGEMENT_STATES = frozenset(
    {
        "not_found",
        "http_denied",
        "rate_limited",
        "invalid_content",
        "shell_page",
        "js_required",
        "login_required",
        "anti_bot",
    }
)

#: States a *skipped* attempt may carry: a policy outcome, not an observation.
POLICY_SKIP_STATES = frozenset({"backend_failure", "budget_exhausted"})

#: States that mean "this attempt did not deliver usable content".
FAILURE_STATES = frozenset(set(RETRIEVAL_STATES) - {SUCCESS_STATE})

# ---------------------------------------------------------------------------
# Policy provenance (why an attempt did or did not run)
# ---------------------------------------------------------------------------

SKIP_REASON_CIRCUIT_OPEN = "circuit_open"
SKIP_REASON_INSUFFICIENT_WINDOW = "insufficient_remaining_window"
SKIP_REASON_PREFLIGHT = "preflight"
SKIP_REASON_DISABLED = "disabled"

SKIP_REASONS: frozenset[str] = frozenset(
    {
        SKIP_REASON_CIRCUIT_OPEN,
        SKIP_REASON_INSUFFICIENT_WINDOW,
        SKIP_REASON_PREFLIGHT,
        SKIP_REASON_DISABLED,
    }
)

BREAKER_STATES: tuple[str, ...] = ("closed", "open", "half_open", "cooldown")
BREAKER_STATE_NONE = ""

_STATUS_IN_TEXT = re.compile(r"\b([1-5]\d{2})\b")


@dataclass(frozen=True)
class RetrievalOutcome:
    """Canonical outcome of one retrieval, plus why it was or was not tried."""

    state: str
    attempted: bool
    skip_reason: str = ""
    breaker_state: str = BREAKER_STATE_NONE
    backend: str = ""
    raw_state: str = ""
    detail: str = ""

    @property
    def is_success(self) -> bool:
        return self.state == SUCCESS_STATE

    @property
    def is_policy_skip(self) -> bool:
        return not self.attempted

    def to_dict(self) -> dict[str, Any]:
        return {
            "retrieval_state": self.state,
            "attempted": self.attempted,
            "skip_reason": self.skip_reason,
            "breaker_state": self.breaker_state,
            "backend": self.backend,
            "raw_state": self.raw_state,
            "detail": self.detail[:200],
        }

    def to_policy_dict(self) -> dict[str, Any]:
        """The policy half only - what ``RawReadArtifact`` carries."""

        return {
            "attempted": self.attempted,
            "skip_reason": self.skip_reason,
            "breaker_state": self.breaker_state,
            "backend": self.backend,
        }


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

# Ordered raw markers -> canonical state. Order matters: the more specific
# transport signatures are checked before the generic ones.
RAW_MARKER_STATES: tuple[tuple[str, str], ...] = (
    ("getaddrinfo", "dns_failure"),
    ("name or service not known", "dns_failure"),
    ("nodename nor servname", "dns_failure"),
    ("temporary failure in name resolution", "dns_failure"),
    ("certificate", "tls_failure"),
    ("ssl", "tls_failure"),
    ("tls handshake", "tls_failure"),
    ("10054", "reset"),
    ("connection reset", "reset"),
    ("connectionreset", "reset"),
    ("reset by peer", "reset"),
    ("connection aborted", "reset"),
    ("remotedisconnected", "reset"),
    ("server disconnected", "reset"),
    ("timed out", "timeout"),
    ("timeout", "timeout"),
    ("connection refused", "connect_failure"),
    ("network is unreachable", "connect_failure"),
    ("temporarily unavailable", "connect_failure"),
    ("urlerror", "connect_failure"),
    ("captcha", "anti_bot"),
    ("are you a robot", "anti_bot"),
    ("unusual traffic", "anti_bot"),
    ("checking your browser", "anti_bot"),
    ("just a moment", "anti_bot"),
    ("enable javascript", "shell_page"),
    ("javascript is required", "shell_page"),
    ("please turn on javascript", "shell_page"),
    ("noscript", "shell_page"),
    ("unauthorized", "http_denied"),
    # Login walls: deliberately multi-word. A bare "login"/"sign in" would fire
    # on unrelated detail text, and this classifier is fail-closed on purpose.
    ("login required", "login_required"),
    ("login_required", "login_required"),
    ("please log in", "login_required"),
    ("sign in to continue", "login_required"),
    ("authentication required", "login_required"),
)

#: Budget refusals (B2 rejection reasons and the §50 window guard). Checked
#: before the transport markers because a budget refusal is a statement about
#: the research window, not about the network.
BUDGET_MARKERS: tuple[str, ...] = (
    "run_envelope_exhausted",
    "hard_headroom_insufficient",
    "insufficient_remaining_window",
    "insufficient_window",
    "skipped_due_to_budget",
    "no_budget",
)

#: Read-adequacy shape -> canonical state. The §71C-3a shapes are content
#: shapes, so they map to content states; ``read_failed`` is only reached when
#: no raw transport marker matched.
ADEQUACY_SHAPE_STATES: Mapping[str, str] = {
    ADEQUATE_SHAPE: SUCCESS_STATE,
    FAILED_SHAPE: UNKNOWN_STATE,
    "js_shell": "shell_page",
    "anti_bot_or_error": "anti_bot",
    "short_doc": "invalid_content",
}

#: §71B invocation lifecycle state -> canonical state (bridge, not a second
#: vocabulary). ``http_error`` is intentionally fail-closed unless the detail
#: carries a status code, and ``unsupported`` resolves through its detail.
INVOCATION_STATE_STATES: Mapping[str, str] = {
    "ok": SUCCESS_STATE,
    "empty": "invalid_content",
    "timeout": "timeout",
    "http_error": UNKNOWN_STATE,
    "transport_error": "connect_failure",
    "unsupported": UNKNOWN_STATE,
    "blocked": "http_denied",
    "aborted": "budget_exhausted",
    "skipped_no_budget": "budget_exhausted",
    "invalid_response": "invalid_content",
}


def state_for_status(status: int | None) -> str:
    """Canonical state for an HTTP status code (``None`` -> unknown)."""

    if not isinstance(status, int) or status <= 0:
        return ""
    if status in (404, 410):
        return "not_found"
    if status in (401, 403, 451):
        return "http_denied"
    if status == 429:
        return "rate_limited"
    if 500 <= status <= 599:
        return UNKNOWN_STATE
    if 400 <= status <= 499:
        return "invalid_content"
    if 300 <= status <= 399:
        return UNKNOWN_STATE
    return ""


def state_for_text(text: str) -> str:
    """Canonical state for a raw **error** string ("" when unrecognised).

    Must only ever be given error/detail/exception text. Passing fetched page
    content here would turn a word on the page into a failure claim about the
    resource, which the contract forbids.
    """

    lowered = str(text or "").lower()
    if not lowered.strip():
        return ""
    for marker, state in RAW_MARKER_STATES:
        if marker in lowered:
            return state
    return ""


def _status_from_text(text: str) -> int | None:
    """Recover an HTTP status embedded in a raw error string, if any."""

    match = _STATUS_IN_TEXT.search(str(text or ""))
    if match is None:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _looks_like_http_error(text: str) -> bool:
    """Gate for trusting a bare status number found inside a detail string."""

    lowered = str(text or "").lower()
    return "http" in lowered or "status" in lowered


def state_for_budget_text(text: str) -> bool:
    """True when a raw detail names a budget refusal rather than a fetch failure."""

    lowered = str(text or "").lower()
    return any(marker in lowered for marker in BUDGET_MARKERS)


def classify(
    *,
    backend: str = "",
    raw_state: str = "",
    detail: str = "",
    http_status: int | None = None,
    adequacy_shape: str = "",
    exception_type: str = "",
    skip_reason: str = "",
    breaker_state: str = BREAKER_STATE_NONE,
    attempted: bool = True,
) -> RetrievalOutcome:
    """Map a backend's raw outcome onto one canonical state.

    Precedence: an explicit policy skip first, then an explicit HTTP status,
    then raw transport/anti-bot markers, then the content shape, then the
    backend-specific state name. Anything unrecognised fails closed to
    ``backend_failure`` - never to ``success``.
    """

    raw = str(raw_state or "")
    text = " ".join(part for part in (detail, exception_type, raw) if part)

    if not attempted:
        state = (
            "budget_exhausted"
            if skip_reason == SKIP_REASON_INSUFFICIENT_WINDOW
            else UNKNOWN_STATE
        )
        outcome = RetrievalOutcome(
            state=state,
            attempted=False,
            skip_reason=skip_reason or SKIP_REASON_DISABLED,
            breaker_state=breaker_state,
            backend=backend,
            raw_state=raw,
            detail=detail,
        )
        assert_retrieval_outcome(outcome)
        return outcome

    state = ""
    if http_status is not None:
        state = state_for_status(http_status)
    if not state and state_for_budget_text(text):
        state = "budget_exhausted"
    if not state:
        # An HTTP-ish error string may carry the status the backend dropped
        # (e.g. "HTTPError: 403 Forbidden"). Only trust the number when the text
        # actually looks like an HTTP error, so an unrelated 3-digit number in a
        # detail string cannot become a content claim.
        if _looks_like_http_error(text):
            candidate = _status_from_text(detail) or _status_from_text(raw)
            if candidate is not None:
                state = state_for_status(candidate)
    if not state:
        state = state_for_text(text)
    if not state and adequacy_shape:
        state = ADEQUACY_SHAPE_STATES.get(str(adequacy_shape), "")
    if not state and raw:
        state = INVOCATION_STATE_STATES.get(raw, "")
    if not state:
        state = UNKNOWN_STATE

    outcome = RetrievalOutcome(
        state=state,
        attempted=True,
        skip_reason="",
        breaker_state=breaker_state,
        backend=backend,
        raw_state=raw,
        detail=detail,
    )
    assert_retrieval_outcome(outcome)
    return outcome


def from_read_adequacy(
    shape: str, *, backend: str = "", detail: str = ""
) -> RetrievalOutcome:
    """Canonical outcome for one §71C-3a read-adequacy shape."""

    return classify(backend=backend, adequacy_shape=shape, detail=detail)


def from_invocation_state(
    state: str, *, backend: str = "", detail: str = ""
) -> RetrievalOutcome:
    """Bridge one §71B invocation lifecycle state into the canonical vocabulary.

    ``unsupported`` resolves through its detail, because that is how the
    existing backends report a policy skip (``circuit_open``, ``preflight:*``).
    """

    raw = str(state or "")
    lowered = str(detail or "").lower()
    if raw == "unsupported" and "circuit_open" in lowered:
        return classify(
            backend=backend,
            raw_state=raw,
            detail=detail,
            skip_reason=SKIP_REASON_CIRCUIT_OPEN,
            breaker_state="open",
            attempted=False,
        )
    if raw == "unsupported" and "preflight" in lowered:
        return classify(
            backend=backend,
            raw_state=raw,
            detail=detail,
            skip_reason=SKIP_REASON_PREFLIGHT,
            attempted=False,
        )
    if raw == "skipped_no_budget":
        return classify(
            backend=backend,
            raw_state=raw,
            detail=detail,
            skip_reason=SKIP_REASON_INSUFFICIENT_WINDOW,
            attempted=False,
        )
    return classify(backend=backend, raw_state=raw, detail=detail)


def is_success(state: str) -> bool:
    return str(state or "") == SUCCESS_STATE


# ---------------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------------


def assert_retrieval_outcome(outcome: RetrievalOutcome) -> None:
    """Enforce the A0 contract on one outcome (raises on violation)."""

    if outcome.state not in RETRIEVAL_STATES:
        raise RetrievalContractError(f"unknown retrieval state: {outcome.state!r}")
    if outcome.breaker_state and outcome.breaker_state not in BREAKER_STATES:
        raise RetrievalContractError(
            f"unknown breaker state: {outcome.breaker_state!r}"
        )
    if outcome.attempted:
        if outcome.skip_reason:
            raise RetrievalContractError(
                "an attempted retrieval must not carry a skip reason"
            )
        return
    # Policy skip: it must say why, and it must not claim anything about the URL.
    if not outcome.skip_reason:
        raise RetrievalContractError("a skipped retrieval must record a skip reason")
    if outcome.skip_reason not in SKIP_REASONS:
        raise RetrievalContractError(f"unknown skip reason: {outcome.skip_reason!r}")
    assert_no_url_truth_from_skip(outcome)
    if outcome.skip_reason == SKIP_REASON_CIRCUIT_OPEN:
        if outcome.breaker_state in (BREAKER_STATE_NONE, "closed"):
            raise RetrievalContractError(
                "a circuit_open skip must carry an open/half_open/cooldown state"
            )
    if outcome.skip_reason == SKIP_REASON_INSUFFICIENT_WINDOW:
        if outcome.state != "budget_exhausted":
            raise RetrievalContractError(
                "an insufficient-window skip must be budget_exhausted"
            )


def assert_no_url_truth_from_skip(outcome: RetrievalOutcome) -> None:
    """``host health != URL truth``: a skip may never judge the resource."""

    if outcome.attempted:
        return
    if outcome.state in CONTENT_JUDGEMENT_STATES:
        raise RetrievalContractError(
            f"a skipped retrieval must not claim {outcome.state!r} about the URL"
        )
    if outcome.state not in POLICY_SKIP_STATES:
        raise RetrievalContractError(
            f"a skipped retrieval may only be {sorted(POLICY_SKIP_STATES)}"
        )


def assert_no_authority_fields(payload: Mapping[str, Any]) -> None:
    """Nothing in this contract may carry local authority (§71B rule)."""

    if not isinstance(payload, Mapping):
        raise RetrievalContractError("outcome payload must be a mapping")
    forbidden = FORBIDDEN_AUTHORITY_FIELDS.intersection(payload)
    if forbidden:
        raise RetrievalContractError(
            "retrieval outcome may not carry local authority fields: "
            + ", ".join(sorted(forbidden))
        )


# ---------------------------------------------------------------------------
# Backend health state model (contract only; A1 owns behaviour)
# ---------------------------------------------------------------------------


def health_key(backend: str, host: str) -> str:
    """Health is tracked per ``(backend, host)``, never per host alone.

    An unhealthy native HTTP path says nothing about the browser backend for the
    same host, so the two must not share a breaker.
    """

    return f"{str(backend or '').strip().lower()}::{str(host or '').strip().lower()}"


@dataclass(frozen=True)
class BackendHealthPolicy:
    """Parameterised thresholds for the A1 breaker. No magic numbers.

    A1's first version is **per-run in-memory** state keyed by
    :func:`health_key`; cross-run health caching is explicitly out of scope.
    """

    failure_threshold: int = 3
    open_seconds: float = 30.0
    half_open_probes: int = 1
    cooldown_seconds: float = 5.0

    def __post_init__(self) -> None:
        if int(self.failure_threshold) < 1:
            raise RetrievalContractError("failure_threshold must be >= 1")
        if float(self.open_seconds) <= 0:
            raise RetrievalContractError("open_seconds must be > 0")
        if int(self.half_open_probes) < 1:
            raise RetrievalContractError("half_open_probes must be >= 1")
        if float(self.cooldown_seconds) < 0:
            raise RetrievalContractError("cooldown_seconds must be >= 0")

    def to_dict(self) -> dict[str, Any]:
        return {
            "failure_threshold": int(self.failure_threshold),
            "open_seconds": float(self.open_seconds),
            "half_open_probes": int(self.half_open_probes),
            "cooldown_seconds": float(self.cooldown_seconds),
            "scope": "per_run",
            "key": "backend+host",
        }


def counts_towards_health(state: str, *, attempted: bool = True) -> bool:
    """Which canonical outcomes count as a *backend health* failure.

    Three exclusions, all deliberate:

    * a **content judgement** (``not_found``, ``http_denied``,
      ``invalid_content``) is an observation about the resource, not evidence
      that the backend is sick;
    * a **policy skip** never counts, whatever its state name - the attempt did
      not run, and letting a skip count would let one breaker feed another;
    * ``budget_exhausted`` describes the research window, not the backend.
    """

    if not attempted:
        return False
    return str(state or "") in {
        "connect_failure",
        "dns_failure",
        "tls_failure",
        "timeout",
        "reset",
        "backend_failure",
    }


__all__ = [
    "ADEQUACY_SHAPE_STATES",
    "BREAKER_STATE_NONE",
    "BREAKER_STATES",
    "BUDGET_MARKERS",
    "BackendHealthPolicy",
    "CONTENT_JUDGEMENT_STATES",
    "FAILURE_STATES",
    "INVOCATION_STATE_STATES",
    "POLICY_SKIP_STATES",
    "RAW_MARKER_STATES",
    "RETRIEVAL_STATES",
    "RetrievalOutcome",
    "SKIP_REASONS",
    "SKIP_REASON_CIRCUIT_OPEN",
    "SKIP_REASON_DISABLED",
    "SKIP_REASON_INSUFFICIENT_WINDOW",
    "SKIP_REASON_PREFLIGHT",
    "SUCCESS_STATE",
    "UNKNOWN_STATE",
    "assert_no_authority_fields",
    "assert_no_url_truth_from_skip",
    "assert_retrieval_outcome",
    "classify",
    "counts_towards_health",
    "from_invocation_state",
    "from_read_adequacy",
    "health_key",
    "is_success",
    "state_for_budget_text",
    "state_for_status",
    "state_for_text",
]
