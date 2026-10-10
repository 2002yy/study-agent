"""M4-A: read-only B-Search shadow for the Standard research path.

Contract (mirrors the §164-C1b learner-state seam):

- the flag defaults **off**, so wiring the code and measuring in production stay
  two different things;
- the decision-input hashes are computed **before** submission, so the observer
  cannot participate in the inputs it observes;
- the observation is a **dead end**: only telemetry may consume it; no branch may
  change the Standard result, bindings, artifact, evidence gate, memory or learner
  state from it;
- submission is **non-blocking**, so the shadow cannot slow or interrupt the main
  research chain;
- the record is **non-authoritative**: ``evidence_completion`` is never SUPPORTED
  here, because that verdict requires an independent full-text audit this seam
  cannot perform. It is reported as UNVERIFIED and must stay that way.
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

SHADOW_FLAG = "BSEARCH_STANDARD_SHADOW"
SEAM_VERSION = "standard-bsearch-shadow-seam-v1"

# Bounded, but large enough to be meaningful. This is the *inner* bound the
# observer enforces on itself (see the limitation note in ``submit_shadow_bounded``).
BSEARCH_SHADOW_BUDGET_SECONDS = 20.0
BSEARCH_SHADOW_MAX_ROUNDS = 6
BSEARCH_SHADOW_MAX_SEARCHES = 4
BSEARCH_SHADOW_MAX_READS = 3

#: The only evidence verdict this seam is allowed to emit. Anything else would
#: turn an unattested shadow run into evidence.
SHADOW_EVIDENCE_COMPLETION = "UNVERIFIED"

#: A shadow record never carries evidence authority. `grants_evidence_authority` is
#: the single choke point every future consumer must pass before a B-Search record
#: may inform an answer, a citation or the Evidence Gate.
EVIDENCE_AUTHORITY = False


def grants_evidence_authority(payload: Mapping[str, Any]) -> bool:
    """Whether a record may inform an answer or the Evidence Gate.

    Always False for shadow records: they are born with ``authoritative=False`` and
    ``evidence_completion="UNVERIFIED"``, so this stays False even when the inner
    observation claims ``finished`` or ``supported``. A record could only pass with
    an explicit authority grant plus a named independent audit reference, which
    this seam never produces.
    """
    if payload.get("authoritative") is not True:
        return False
    if payload.get("evidence_completion") != "SUPPORTED":
        return False
    return bool(payload.get("audit_ref"))


def standard_shadow_enabled() -> bool:
    """Default off; unset or unknown keeps the production behaviour unchanged."""
    raw = (os.getenv(SHADOW_FLAG) or "").strip().lower()
    return raw in {"1", "true", "on", "yes"}


def canonical_hash(value: object) -> str:
    return sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str,
                   separators=(",", ":")).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class StandardInputHashes:
    """The inputs the observer must not be able to influence."""

    query_hash: str
    handoff_hash: str

    def to_dict(self) -> dict[str, str]:
        return {"query_hash": self.query_hash, "handoff_hash": self.handoff_hash}


def build_standard_input_hashes(
    *, query: str, handoff: Mapping[str, Any] | None
) -> StandardInputHashes:
    """Compute the hashes. Must be called **before** submitting the shadow work."""
    return StandardInputHashes(
        query_hash=canonical_hash(str(query or "")),
        handoff_hash=canonical_hash(dict(handoff or {})),
    )


def summarize_trace(trace: Mapping[str, Any], *, budget_seconds: float) -> dict[str, Any]:
    """Turn a B-Search trace into a non-authoritative, telemetry-only record.

    Only observation fields are kept. ``evidence_completion`` is pinned to
    UNVERIFIED regardless of what the agent reported about itself, and
    ``authoritative`` is pinned to False: a shadow run can never grant evidence.
    """
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

    budget = AgentBudget(
        max_rounds=BSEARCH_SHADOW_MAX_ROUNDS,
        max_searches=BSEARCH_SHADOW_MAX_SEARCHES,
        max_reads=BSEARCH_SHADOW_MAX_READS,
        hard_seconds=budget_seconds,
    )
    trace = run_tool_agent(
        gateway=GeneralWebGateway(),
        completion=configured_completion,
        question=query,
        budget=budget,
    )
    return summarize_trace(trace, budget_seconds=budget_seconds)


@dataclass(frozen=True)
class StandardShadowResult:
    """What the seam produced. Never an exception, never a business input."""

    enabled: bool
    submitted: bool
    decision_inputs: StandardInputHashes

    @property
    def telemetry_only(self) -> bool:
        """The seam's output is consumed by telemetry and nothing else."""
        return True


def observe_shadow_for_standard(
    *,
    query: str,
    handoff: Mapping[str, Any] | None = None,
    telemetry: BestEffortTelemetry | None = None,
    runner: Callable[[str, float], dict[str, Any]] | None = None,
) -> StandardShadowResult:
    """Submit the bounded B-Search shadow read. Returns immediately; never raises."""
    inputs = build_standard_input_hashes(query=query, handoff=handoff)
    if not standard_shadow_enabled():
        return StandardShadowResult(False, False, inputs)

    run = runner or _default_runner

    def work() -> dict[str, Any]:
        record = dict(run(str(query or ""), BSEARCH_SHADOW_BUDGET_SECONDS) or {})
        # Sanitize unconditionally: no runner may hand the shadow authority.
        record["authoritative"] = False
        record["evidence_completion"] = SHADOW_EVIDENCE_COMPLETION
        return {
            "seam_version": SEAM_VERSION,
            "authoritative": False,
            "decision_inputs": inputs.to_dict(),
            "observation": record,
        }

    def on_result(outcome: ShadowOutcome) -> None:
        if telemetry is not None and outcome.ok:
            telemetry.record(outcome.value)

    submitted = submit_shadow_bounded(work, on_result=on_result)
    return StandardShadowResult(True, submitted, inputs)
