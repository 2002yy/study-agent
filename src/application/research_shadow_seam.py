"""M4-A/M4-B: read-only B-Search shadow, parameterised by research phase.

One contract, three phases (``standard`` / ``lookup`` / ``deep``):

- per-phase flag defaults **off**, so wiring and measuring stay two different things;
- decision-input hashes are computed **before** submission, so the observer cannot
  participate in what it observes;
- the observation is a **dead end**: only telemetry consumes it, and no branch may
  change the phase's result, bindings, artifact, evidence gate, memory or learner
  state from it;
- submission is **non-blocking** and bounded (shared 2-worker pool, admission
  semaphore, reject-on-saturation), so a shadow cannot slow or interrupt research;
- records are **non-authoritative**: ``authoritative=False`` and
  ``evidence_completion="UNVERIFIED"`` are pinned for any runner, and
  ``grants_evidence_authority`` stays False.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from typing import Any, Callable, Mapping

from src.application.shadow_isolation import (
    BestEffortTelemetry,
    ShadowOutcome,
    submit_shadow_bounded,
)

PHASES = ("standard", "lookup", "deep")

#: One flag per phase: enabling Deep observation must not silently enable Lookup.
PHASE_FLAGS = {
    "standard": "BSEARCH_STANDARD_SHADOW",
    "lookup": "BSEARCH_LOOKUP_SHADOW",
    "deep": "BSEARCH_DEEP_SHADOW",
}

SEAM_VERSION = "research-bsearch-shadow-seam-v1"

#: Per-phase telemetry schema. The Standard record keeps the M4-A shape exactly
#: (version ``standard-bsearch-shadow-seam-v1``, no ``phase`` key) so the merged M4-A
#: contract is not silently changed; Lookup/Deep use the phase-aware format.
PHASE_SCHEMA: dict[str, tuple[str, bool]] = {
    "standard": ("standard-bsearch-shadow-seam-v1", False),
    "lookup": (SEAM_VERSION, True),
    "deep": (SEAM_VERSION, True),
}

#: Research budget tiers: (rounds, searches, page requests, seconds). The tier is the
#: single configuration entry point (env ``BSEARCH_SHADOW_TIER``) - no call site hardcodes
#: a number. ``standard`` is the default; a run may escalate once to ``deep`` while keeping
#: all state (no restart, no re-payment) when goals remain unresolved and the state still
#: holds an actionable candidate.
BUDGET_TIERS: dict[str, tuple[int, int, int, float]] = {
    "quick": (4, 2, 2, 20.0),
    "standard": (8, 4, 5, 40.0),
    "deep": (12, 6, 8, 75.0),
    "extended": (20, 8, 14, 180.0),
}
DEFAULT_TIER = "standard"
#: Escalation is a CHAIN, applied in order, once per step, inside the same run.
ESCALATION_CHAIN: tuple[str, ...] = ("deep", "extended")


def tier_budget(tier: str | None = None) -> tuple[int, int, int, float]:
    """(rounds, searches, page requests, seconds) for a tier name or the env default."""
    name = (tier or os.getenv("BSEARCH_SHADOW_TIER") or DEFAULT_TIER).strip().lower()
    return BUDGET_TIERS.get(name, BUDGET_TIERS[DEFAULT_TIER])


def escalation_chain(tier: str | None = None) -> tuple[str, ...]:
    """Tiers a run at ``tier`` may escalate through, in order.

    The declared maximum is the last tier in the chain, so the shadow's recorded bound
    matches what the run can actually consume (the earlier wiring let the default runner
    escalate to a deeper tier while the record still claimed the base tier's seconds).
    """
    name = (tier or os.getenv("BSEARCH_SHADOW_TIER") or DEFAULT_TIER).strip().lower()
    if name not in BUDGET_TIERS:
        name = DEFAULT_TIER
    # Only the default tier escalates. `quick` promises a low-cost answer, and a caller on
    # `deep`/`extended` already asked for the bigger budget, so neither may grow silently.
    # A caller that really wants more passes an explicit escalation list.
    if name != DEFAULT_TIER:
        return ()
    return ESCALATION_CHAIN


BSEARCH_SHADOW_MAX_ROUNDS, BSEARCH_SHADOW_MAX_SEARCHES, BSEARCH_SHADOW_MAX_READS, \
    BSEARCH_SHADOW_BUDGET_SECONDS = tier_budget()

#: The only evidence verdict this seam may emit.
SHADOW_EVIDENCE_COMPLETION = "UNVERIFIED"

#: A shadow record never carries evidence authority.
EVIDENCE_AUTHORITY = False


def shadow_enabled(phase: str) -> bool:
    """Default off; unset or unknown keeps the production behaviour unchanged."""
    flag = PHASE_FLAGS.get(phase)
    if flag is None:
        return False
    raw = (os.getenv(flag) or "").strip().lower()
    return raw in {"1", "true", "on", "yes"}


def canonical_hash(value: object) -> str:
    return sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str,
                   separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def grants_evidence_authority(payload: Mapping[str, Any]) -> bool:
    """Whether a record may inform an answer or the Evidence Gate.

    Always False for shadow records: they are born with ``authoritative=False`` and
    ``evidence_completion="UNVERIFIED"``, so this stays False even when the inner
    observation claims ``finished`` or ``supported``. A record could only pass with an
    explicit authority grant plus a named independent audit reference, which this seam
    never produces.
    """
    if payload.get("authoritative") is not True:
        return False
    if payload.get("evidence_completion") != "SUPPORTED":
        return False
    return bool(payload.get("audit_ref"))


@dataclass(frozen=True)
class ShadowInputHashes:
    """The inputs the observer must not be able to influence."""

    query_hash: str
    handoff_hash: str

    def to_dict(self) -> dict[str, str]:
        return {"query_hash": self.query_hash, "handoff_hash": self.handoff_hash}


def build_input_hashes(*, query: str, handoff: Mapping[str, Any] | None) -> ShadowInputHashes:
    """Compute the hashes. Must be called **before** submitting the shadow work."""
    return ShadowInputHashes(
        query_hash=canonical_hash(str(query or "")),
        handoff_hash=canonical_hash(dict(handoff or {})),
    )


def summarize_trace(trace: Mapping[str, Any], *, budget_seconds: float) -> dict[str, Any]:
    """Turn a B-Search trace into a non-authoritative, telemetry-only record."""
    bodies = [b for b in trace.get("bodies", []) if b.get("ok") and b.get("chars", 0) > 0]
    audit = trace.get("coverage_audit") or {}
    return {
        "authoritative": False,
        "evidence_completion": SHADOW_EVIDENCE_COMPLETION,
        "stop_reason": trace.get("stop_reason"),
        "rounds": trace.get("rounds"),
        "searches": trace.get("searches"),
        "reads": trace.get("reads"),
        "elapsed_seconds": trace.get("elapsed_seconds"),
        "budget_seconds": budget_seconds,
        "bodies": [{"url": b.get("url"), "chars": b.get("chars")} for b in bodies],
        "sub_goal_status": {
            k: (v or {}).get("status") for k, v in (audit.get("sub_goals") or {}).items()
        },
    }


def _default_runner(query: str, budget_seconds: float) -> dict[str, Any]:
    """Real B-Search run, internally bounded. Imported lazily so flag OFF is free."""
    from src.web.research_tool_agent import AgentBudget, run_tool_agent
    from src.web.semantic_recovery import configured_completion
    from src.web.tool_gateway import GeneralWebGateway

    rounds, searches, reads, seconds = tier_budget()
    budget = AgentBudget(
        max_rounds=rounds,
        max_searches=searches,
        max_reads=reads,
        hard_seconds=budget_seconds or seconds,
    )
    escalations = tuple(
        AgentBudget(max_rounds=tier[0], max_searches=tier[1], max_reads=tier[2],
                    hard_seconds=tier[3])
        for tier in (tier_budget(name) for name in escalation_chain())
    )
    trace = run_tool_agent(
        gateway=GeneralWebGateway(),
        completion=configured_completion,
        question=query,
        budget=budget,
        escalation_budgets=escalations,
    )
    record = summarize_trace(trace, budget_seconds=budget_seconds)
    # Honest runtime accounting: the record names the whole escalation chain instead of
    # claiming only the base tier's seconds.
    record["escalation_seconds"] = [item.hard_seconds for item in escalations]
    record["escalations"] = list(trace.get("escalations") or [])
    return record


@dataclass(frozen=True)
class ShadowResult:
    """What the seam produced. Never an exception, never a business input.

    ``submitted`` means the work was *admitted to the bounded worker* — it does not
    mean a record was persisted. The sink is best-effort, so persistence must be
    observed at the sink, never inferred from this flag.
    """

    phase: str
    enabled: bool
    submitted: bool
    decision_inputs: ShadowInputHashes

    @property
    def telemetry_only(self) -> bool:
        """The seam's output is consumed by telemetry and nothing else."""
        return True


def observe_shadow(
    *,
    phase: str,
    query: str,
    handoff: Mapping[str, Any] | None = None,
    telemetry: BestEffortTelemetry | None = None,
    runner: Callable[[str, float], dict[str, Any]] | None = None,
) -> ShadowResult:
    """Submit the bounded B-Search shadow read for one phase. Never raises."""
    inputs = build_input_hashes(query=query, handoff=handoff)
    if not shadow_enabled(phase):
        return ShadowResult(phase, False, False, inputs)
    if telemetry is None:
        # No observable sink: refuse to spend model/network budget on a run whose
        # result would be discarded. Enabled, but deliberately not submitted.
        return ShadowResult(phase, True, False, inputs)

    run = runner or _default_runner

    def work() -> dict[str, Any]:
        record = dict(run(str(query or ""), BSEARCH_SHADOW_BUDGET_SECONDS) or {})
        # Sanitize unconditionally: no runner may hand the shadow authority.
        record["authoritative"] = False
        record["evidence_completion"] = SHADOW_EVIDENCE_COMPLETION
        version, include_phase = PHASE_SCHEMA.get(phase, (SEAM_VERSION, True))
        payload: dict[str, Any] = {
            "seam_version": version,
            "authoritative": False,
            "decision_inputs": inputs.to_dict(),
            "observation": record,
        }
        if include_phase:
            payload["phase"] = phase
        return payload

    def on_result(outcome: ShadowOutcome) -> None:
        if telemetry is not None and outcome.ok:
            telemetry.record(outcome.value)

    submitted = submit_shadow_bounded(work, on_result=on_result)
    return ShadowResult(phase, True, submitted, inputs)
