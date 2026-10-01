"""§164-C1b-1: the single narrow seam that runs the shadow read inside a turn.

Contract (docs/PROJECT_STATUS.md §164.15):

- the flag defaults to **off**, so wiring the code and enabling measurement in
  production stay two different things;
- the four decision-input hashes are computed **before** the shadow call and are
  passed in, so the observer cannot participate in the planning inputs they
  represent;
- the returned outcome is a **dead end**: only telemetry may consume it, and no
  branch may change plan, state, retrieval or closure from it;
- publish happens after the turn's start state is persisted and is genuinely
  non-blocking.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from typing import Any, Callable, Mapping

from src.application.learner_state_parity_observer import (
    observe_learner_state_parity,
)
from src.application.shadow_isolation import (
    DEFAULT_SHADOW_BUDGET_SECONDS,
    BestEffortTelemetry,
    ShadowOutcome,
    run_shadow_bounded,
)

SHADOW_FLAG = "LEARNER_STATE_SHADOW_READ"
SEAM_VERSION = "learner-state-shadow-seam-v1"


def shadow_read_enabled() -> bool:
    """Default off; unset or unknown keeps the production behaviour unchanged."""
    raw = (os.getenv(SHADOW_FLAG) or "").strip().lower()
    return raw in {"1", "true", "on", "yes"}


def canonical_hash(value: object) -> str:
    return sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str,
                   separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _as_payload(value: object) -> object:
    """Use a value's own to_dict when it has one; otherwise the value itself."""
    converter = getattr(value, "to_dict", None)
    return converter() if callable(converter) else value


@dataclass(frozen=True)
class DecisionInputHashes:
    """The planning inputs the observer must not be able to influence."""

    route_hash: str
    pedagogy_plan_hash: str
    retrieval_plan_hash: str
    prompt_context_hash: str

    def to_dict(self) -> dict[str, str]:
        return {
            "route_hash": self.route_hash,
            "pedagogy_plan_hash": self.pedagogy_plan_hash,
            "retrieval_plan_hash": self.retrieval_plan_hash,
            "prompt_context_hash": self.prompt_context_hash,
        }


def build_decision_input_hashes(
    *,
    route: Mapping[str, Any],
    pedagogy_plan: object,
    retrieval_plan: object,
    messages: object,
) -> DecisionInputHashes:
    """Compute the four hashes. Must be called **before** the shadow call."""
    return DecisionInputHashes(
        route_hash=canonical_hash(dict(route)),
        pedagogy_plan_hash=canonical_hash(_as_payload(pedagogy_plan)),
        retrieval_plan_hash=canonical_hash(_as_payload(retrieval_plan)),
        prompt_context_hash=canonical_hash(messages),
    )


@dataclass(frozen=True)
class ShadowSeamResult:
    """What the seam produced. Never an exception, never a business input."""

    enabled: bool
    outcome: ShadowOutcome | None
    decision_inputs: DecisionInputHashes

    @property
    def telemetry_only(self) -> bool:
        """The seam's output is consumed by telemetry and nothing else."""
        return True


def observe_shadow_for_turn(
    *,
    thread_id: str,
    turn_id: str,
    learning_state_before: object,
    snapshot_reader: Callable[[], object] | None,
    decision_inputs: DecisionInputHashes,
    legacy_misconceptions: tuple[str, ...] = (),
    legacy_next_step_hint: str = "",
    budget_seconds: float = DEFAULT_SHADOW_BUDGET_SECONDS,
) -> ShadowSeamResult:
    """Run the bounded shadow read. Returns a dead-end result; never raises."""
    if snapshot_reader is None:
        return ShadowSeamResult(False, None, decision_inputs)

    def work() -> object:
        snapshot = snapshot_reader()
        return observe_learner_state_parity(
            thread_id=thread_id,
            turn_id=turn_id,
            learning_state=learning_state_before,
            snapshot=snapshot,
            legacy_misconceptions=legacy_misconceptions,
            legacy_next_step_hint=legacy_next_step_hint,
            provenance={
                "seam_version": SEAM_VERSION,
                "decision_inputs": decision_inputs.to_dict(),
            },
        )

    outcome = run_shadow_bounded(work, budget_seconds=budget_seconds)
    return ShadowSeamResult(True, outcome, decision_inputs)


def publish_shadow_observation(
    result: ShadowSeamResult,
    *,
    telemetry: BestEffortTelemetry | None,
    turn_start_persistence_confirmed: bool,
) -> None:
    """Best-effort, non-blocking publish. Never awaited, never raises.

    ``turn_start_persistence_confirmed`` describes the persisted start state of
    this turn, not the whole turn lifecycle, so an artifact cannot overstate a
    partial success.
    """
    if telemetry is None or result.outcome is None or not result.outcome.ok:
        return
    observation = _as_payload(result.outcome.value)
    payload = {
        "seam_version": SEAM_VERSION,
        "turn_start_persistence_confirmed": turn_start_persistence_confirmed,
        "decision_inputs": result.decision_inputs.to_dict(),
        "observation": observation,
    }
    telemetry.record(payload)
