"""§71B retrieval backend contract: types, provenance ledger and budgets.

Contract only - no backend is wired into the runtime yet. The module exists so
external capabilities (rendered fetchers, search challengers, source-family
routers) can be evaluated in shadow mode without ever touching the evidence
chain.

Frozen boundaries
-----------------

1. A **discovery backend** may only produce :class:`DiscoveryCandidate` rows.
2. A **read backend** may only produce a :class:`RawReadArtifact`.
3. **Evidence authority stays local**: candidates and raw reads still have to
   pass the existing candidate assessment, extraction and support formation.
4. **Gate authority stays local**: an external ``confidence``, ``evidence`` or
   ``quality`` field can never be mapped into our Gate, support links or claim
   confidence. Anything a backend returns beyond the declared fields is kept in
   ``external_metadata`` and is inert.

Lifecycle discipline (the §71A-1 lesson, generalised)
-----------------------------------------------------

Every external invocation follows::

    resolve live metrics -> create invocation (stable id) -> external call
    -> resolve live metrics again -> terminal upsert

Backends must never hold a long-lived context or metrics reference: the runtime
rebinds both, so a captured mapping silently becomes a different universe. The
ledger therefore takes a *provider callable* and re-resolves at every boundary,
and every created invocation must reach a terminal state before its function
returns.

Budgets
-------

Three separate ledgers, one shared clock:

* ``model_attempt`` - model calls (unchanged; external backends never spend it);
* ``retrieval_attempt`` - search/fetch attempts, accounted per backend;
* ``wall_clock`` - the one budget every second is charged to, because four
  seconds in a browser fetch cost the 48s research window exactly as much as
  four seconds in a model call.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, MutableMapping, Protocol, Sequence

# ---------------------------------------------------------------------------
# Boundaries
# ---------------------------------------------------------------------------

DISCOVERY_OPERATION = "search"
READ_OPERATION = "fetch"
RETRIEVAL_OPERATIONS = (DISCOVERY_OPERATION, READ_OPERATION)

# Fields a backend may declare. Everything else is inert external metadata.
DISCOVERY_CANDIDATE_FIELDS = (
    "url",
    "title",
    "snippet",
    "provider",
    "source_family",
    "discovered_at",
    "backend",
)
RAW_READ_ARTIFACT_FIELDS = (
    "url",
    "content",
    "content_type",
    "retrieval_mode",
    "backend",
    "latency_ms",
    "bytes",
    "rendered",
    "cache_hit",
    # §94 P2-A0: canonical retrieval outcome (failure_taxonomy.RETRIEVAL_STATES)
    # and the policy half of why the attempt did or did not run. Optional so
    # existing backends and consumers keep working unchanged.
    "retrieval_state",
    "retrieval_policy",
)

# Names that must never appear as first-class contract fields: they belong to
# local authority (assessment / extraction / support / Gate), not to a backend.
FORBIDDEN_AUTHORITY_FIELDS = frozenset(
    {
        "evidence",
        "evidence_id",
        "support",
        "support_type",
        "relation",
        "claim_confidence",
        "confidence",
        "gate",
        "gate_status",
        "eligibility",
        "answer_relevant",
        "relevance",
        "quality_score",
    }
)

BUDGET_KINDS = ("model_attempt", "retrieval_attempt", "wall_clock")

TERMINAL_RETRIEVAL_STATES = frozenset(
    {
        "ok",
        "empty",
        "timeout",
        "http_error",
        "transport_error",
        "unsupported",
        "blocked",
        "aborted",
        "skipped_no_budget",
        "invalid_response",
    }
)
RUNNING_RETRIEVAL_STATE = "running"


class RetrievalContractError(ValueError):
    """Raised when a backend payload violates the frozen contract."""


# ---------------------------------------------------------------------------
# Requests / results
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DiscoveryRequest:
    claim_id: str
    wave_index: int
    query: str
    max_results: int = 10
    timeout_seconds: float | None = None
    source_family: str = ""


@dataclass(frozen=True)
class DiscoveryCandidate:
    url: str
    title: str = ""
    snippet: str = ""
    provider: str = ""
    source_family: str = ""
    discovered_at: str = ""
    backend: str = ""
    external_metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_candidate_row(self) -> dict[str, Any]:
        """Neutral row for the existing candidate pipeline (no authority)."""

        return {
            "url": self.url,
            "title": self.title,
            "snippet": self.snippet,
            "provider": self.provider,
            "source_family": self.source_family,
            "discovered_at": self.discovered_at,
            "backend": self.backend,
        }


@dataclass(frozen=True)
class ReadRequest:
    url: str
    max_chars: int = 6000
    timeout_seconds: float | None = None
    retrieval_mode: str = "http"


@dataclass(frozen=True)
class RawReadArtifact:
    url: str
    content: str = ""
    content_type: str = ""
    retrieval_mode: str = "http"
    backend: str = ""
    latency_ms: float = 0.0
    bytes: int = 0
    # None means "no reliable backend signal" - never guessed from latency.
    rendered: bool | None = None
    cache_hit: bool | None = None
    # §94 P2-A0: canonical outcome of this retrieval. Named ``retrieval_state``
    # rather than ``failure_state`` because it also describes success. Empty
    # means "not classified yet" - a backend that declares nothing is treated as
    # unclassified, never as success.
    retrieval_state: str = ""
    # ``{"attempted", "skip_reason", "breaker_state", "backend"}`` from
    # failure_taxonomy.RetrievalOutcome.to_policy_dict(). Empty for an ordinary
    # attempted read.
    retrieval_policy: Mapping[str, Any] = field(default_factory=dict)
    external_metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def usable(self) -> bool:
        return bool(self.content.strip())

    @property
    def attempted(self) -> bool:
        """False only when a policy skip is recorded (the URL was never read)."""

        policy = self.retrieval_policy
        if isinstance(policy, Mapping) and "attempted" in policy:
            return bool(policy.get("attempted"))
        return True


class DiscoveryBackend(Protocol):
    name: str

    def search(self, request: DiscoveryRequest) -> Sequence[DiscoveryCandidate]:
        ...


class ReadBackend(Protocol):
    name: str

    def fetch(self, request: ReadRequest) -> RawReadArtifact:
        ...


def validate_read_artifact(artifact: RawReadArtifact) -> None:
    """Enforce the §94 A0 outcome contract on one read artifact.

    A backend may declare ``retrieval_state`` freely, but whatever it declares
    must be a canonical state, must not smuggle local authority, and a policy
    skip must not claim anything about the URL. Unclassified (empty) is allowed:
    it means "nobody said", which is never treated as success.
    """

    from src.web.research.failure_taxonomy import (
        RETRIEVAL_STATES,
        RetrievalOutcome,
        assert_no_authority_fields,
        assert_no_url_truth_from_skip,
        assert_retrieval_outcome,
    )

    state = str(artifact.retrieval_state or "")
    if state and state not in RETRIEVAL_STATES:
        raise RetrievalContractError(f"unknown retrieval_state: {state!r}")
    policy = artifact.retrieval_policy
    if policy:
        assert_no_authority_fields(policy)
        assert_retrieval_outcome(
            RetrievalOutcome(
                state=state or "backend_failure",
                attempted=bool(policy.get("attempted")),
                skip_reason=str(policy.get("skip_reason") or ""),
                breaker_state=str(policy.get("breaker_state") or ""),
                backend=str(policy.get("backend") or artifact.backend),
            )
        )
        assert_no_url_truth_from_skip(
            RetrievalOutcome(
                state=state or "backend_failure",
                attempted=bool(policy.get("attempted")),
            )
        )


# ---------------------------------------------------------------------------
# Provenance ledger
# ---------------------------------------------------------------------------


def retrieval_invocation_id(
    *, claim_id: str, wave_index: int, backend: str, operation: str, sequence: int
) -> str:
    """Stable id: ``claim_id:wave_id:backend:operation:seq``."""

    if operation not in RETRIEVAL_OPERATIONS:
        raise RetrievalContractError(f"unknown retrieval operation: {operation!r}")
    return f"{claim_id}:{int(wave_index)}:{backend}:{operation}:{int(sequence)}"


def _live_metrics(
    metrics_provider: Callable[[], MutableMapping[str, Any] | None],
) -> MutableMapping[str, Any] | None:
    """Re-resolve the live metrics mapping; never cache the provider result."""

    try:
        metrics = metrics_provider()
    except Exception:
        return None
    return metrics if isinstance(metrics, MutableMapping) else None


def create_retrieval_invocation(
    metrics_provider: Callable[[], MutableMapping[str, Any] | None],
    *,
    claim_id: str,
    wave_index: int,
    backend: str,
    operation: str,
    sequence: int | None = None,
) -> dict[str, Any]:
    """Register a retrieval invocation in the *live* metrics mapping."""

    metrics = _live_metrics(metrics_provider)
    if metrics is None:
        raise RetrievalContractError("no writable metrics mapping available")
    invocations = metrics.get("retrieval_invocations")
    if not isinstance(invocations, list):
        invocations = []
    if sequence is None:
        sequence = (
            sum(
                1
                for item in invocations
                if isinstance(item, Mapping)
                and item.get("claim_id") == claim_id
                and int(item.get("wave_index") or 0) == int(wave_index)
                and item.get("backend") == backend
                and item.get("operation") == operation
            )
            + 1
        )
    entry: dict[str, Any] = {
        "invocation_id": retrieval_invocation_id(
            claim_id=claim_id,
            wave_index=wave_index,
            backend=backend,
            operation=operation,
            sequence=sequence,
        ),
        "claim_id": claim_id,
        "wave_index": int(wave_index),
        "backend": backend,
        "operation": operation,
        "state": RUNNING_RETRIEVAL_STATE,
        "result_count": 0,
        "bytes": 0,
        "cache_hit": False,
        "escalation_reason": "",
    }
    invocations.append(entry)
    metrics["retrieval_invocations"] = invocations[-60:]
    return entry


def finalize_retrieval_invocation(
    metrics_provider: Callable[[], MutableMapping[str, Any] | None],
    entry: Mapping[str, Any] | None,
    *,
    state: str,
    result_count: int = 0,
    bytes: int = 0,
    cache_hit: bool = False,
    escalation_reason: str = "",
    latency_ms: float | None = None,
) -> None:
    """Terminal upsert by invocation id into the live mapping.

    A backend that returns after the runtime replaced its context still lands
    here: the entry is found by id in the live mapping, or recovered there
    (marked ``recovered``) instead of appended twice.
    """

    if entry is None:
        return
    if state not in TERMINAL_RETRIEVAL_STATES:
        raise RetrievalContractError(
            f"state must be terminal, got {state!r}; "
            f"terminal states are {sorted(TERMINAL_RETRIEVAL_STATES)}"
        )
    metrics = _live_metrics(metrics_provider)
    if isinstance(entry, MutableMapping):
        entry["state"] = state
    if metrics is None:
        return
    invocations = metrics.get("retrieval_invocations")
    if not isinstance(invocations, list):
        invocations = []
    target = next(
        (
            item
            for item in invocations
            if isinstance(item, dict)
            and item.get("invocation_id") == entry.get("invocation_id")
        ),
        None,
    )
    if target is None:
        target = dict(entry)
        target["recovered"] = True
        invocations.append(target)
    target["state"] = state
    target["result_count"] = int(result_count)
    target["bytes"] = int(bytes)
    target["cache_hit"] = bool(cache_hit)
    target["escalation_reason"] = str(escalation_reason)[:120]
    if latency_ms is not None:
        target["latency_ms"] = round(float(latency_ms), 1)
    metrics["retrieval_invocations"] = invocations[-60:]


def assert_retrieval_invocations_terminal(metrics: Mapping[str, Any]) -> None:
    """Invariant helper: no invocation may be left running."""

    running = [
        item.get("invocation_id")
        for item in metrics.get("retrieval_invocations") or []
        if isinstance(item, Mapping)
        and item.get("state") == RUNNING_RETRIEVAL_STATE
    ]
    if running:
        raise RetrievalContractError(f"non-terminal retrieval invocations: {running}")


# ---------------------------------------------------------------------------
# Budget accounting (types only; no policy)
# ---------------------------------------------------------------------------


def retrieval_attempt_row(
    *,
    backend: str,
    operation: str,
    claim_id: str,
    wave_index: int,
    latency_ms: float,
    result_count: int = 0,
    bytes: int = 0,
    cache_hit: bool = False,
    escalation_reason: str = "",
) -> dict[str, Any]:
    """One retrieval attempt for the ``retrieval_attempt`` ledger.

    Deliberately separate from ``model_attempt``: a search or fetch never spends
    model budget, but its latency is charged to the shared wall clock by the
    caller (``wall_clock`` is the budget every second belongs to).
    """

    if operation not in RETRIEVAL_OPERATIONS:
        raise RetrievalContractError(f"unknown retrieval operation: {operation!r}")
    return {
        "budget": "retrieval_attempt",
        "backend": backend,
        "operation": operation,
        "claim_id": claim_id,
        "wave_index": int(wave_index),
        "latency_ms": round(float(latency_ms), 1),
        "result_count": int(result_count),
        "bytes": int(bytes),
        "cache_hit": bool(cache_hit),
        "escalation_reason": str(escalation_reason)[:120],
    }


def validate_backend_payload(
    payload: Mapping[str, Any], *, allowed_fields: Sequence[str]
) -> None:
    """Reject payloads that smuggle local authority into the contract."""

    if not isinstance(payload, Mapping):
        raise RetrievalContractError("backend payload must be a mapping")
    forbidden = FORBIDDEN_AUTHORITY_FIELDS.intersection(payload)
    if forbidden:
        raise RetrievalContractError(
            "backend payload may not carry local authority fields: "
            + ", ".join(sorted(forbidden))
        )
    extra = set(payload) - set(allowed_fields) - {"external_metadata"}
    if extra:
        raise RetrievalContractError(
            "backend payload has undeclared fields (move them to "
            "external_metadata): " + ", ".join(sorted(extra))
        )


__all__ = [
    "BUDGET_KINDS",
    "DISCOVERY_CANDIDATE_FIELDS",
    "DISCOVERY_OPERATION",
    "FORBIDDEN_AUTHORITY_FIELDS",
    "RAW_READ_ARTIFACT_FIELDS",
    "READ_OPERATION",
    "RETRIEVAL_OPERATIONS",
    "RUNNING_RETRIEVAL_STATE",
    "TERMINAL_RETRIEVAL_STATES",
    "DiscoveryBackend",
    "DiscoveryCandidate",
    "DiscoveryRequest",
    "RawReadArtifact",
    "ReadBackend",
    "ReadRequest",
    "RetrievalContractError",
    "assert_retrieval_invocations_terminal",
    "create_retrieval_invocation",
    "finalize_retrieval_invocation",
    "retrieval_attempt_row",
    "retrieval_invocation_id",
    "validate_backend_payload",
    "validate_read_artifact",
]
