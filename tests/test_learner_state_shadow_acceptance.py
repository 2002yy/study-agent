"""§164-C1b-1 acceptance: real start_turn, observer broken eight ways.

Discipline (docs §164.15): each scenario is paired with **its own** off baseline
built from the same fixture, user turn, starting state and deterministic seams;
the snapshot covers only production-observable behaviour; the latency bound is
frozen here **before** any measurement; and the runtime evidence is an invocation
proof, not an artifact.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import threading
import time

import pytest

from src.application import shadow_isolation as iso
from src.application.chat_service import (
    ChatCommand,
    ChatDependencies,
    ChatService,
    _requires_mastery_evidence,
)
from src.application.learner_state_shadow_seam import (
    SHADOW_FLAG,
    canonical_hash,
)
from src.application.learner_state_parity_observer import LearnerStateParityCollector
from src.application.shadow_isolation import (
    DEFAULT_SHADOW_BUDGET_SECONDS,
    SHADOW_CAPACITY,
    BestEffortTelemetry,
)
from src.domain.learner_model import LearnerClaimState, LearnerModelSnapshot
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.mode_manager import RuntimeModes
from src.pedagogy.evaluation import PedagogyEvaluationService
from src.repositories.runtime_repository import RuntimeRepository
from src.tools.web_agent import WebToolTrace

# Frozen before measuring: the shadow budget plus scheduling tolerance. An
# overrun is a real failure, not a reason to move the gate.
LATENCY_DELTA_BOUND_SECONDS = 1.0


class _FakeRag:
    context = "local context"

    def to_dict(self) -> dict[str, object]:
        return {"status": "found", "context": self.context, "result_count": 1,
                "results": []}


def _service(tmp_path, *, reader, telemetry=None) -> tuple[ChatService, RuntimeRepository]:
    repository = RuntimeRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    dependencies = ChatDependencies(
        load_runtime_modes=lambda: RuntimeModes(
            memory_mode="preview", performance_mode="standard"
        ),
        read_memory_bundle=lambda context_mode: {},
        build_role_prompt=lambda role, **kwargs: f"role:{role}",
        route_request=lambda **kwargs: {
            "role": "nahida", "mode": "普通", "model_profile": "flash", "reason": "test",
        },
        retrieve_local_knowledge=lambda *args, **kwargs: _FakeRag(),
        build_messages=lambda **kwargs: [
            {"role": "system", "content": kwargs["role_prompt"]},
            {"role": "user", "content": kwargs["user_input"]},
        ],
        chat=lambda *args, **kwargs: "complete reply",
        stream_chat=lambda *args, **kwargs: iter(["part", " two"]),
        chat_max_tokens=lambda performance_mode: 1000,
        resolve_web_tools=lambda *args, **kwargs: WebToolTrace(enabled=False),
        pedagogy_engine=__import__(
            "src.pedagogy.engine", fromlist=["PedagogyEngine"]
        ).PedagogyEngine(),
        pedagogy_evaluation=PedagogyEvaluationService(),
        read_learner_model=reader,
    )
    return ChatService(repository, dependencies, shadow_telemetry=telemetry), repository


# Generated identities (ped_eval_<hex>, turn_<hex>, ...) are per-run random and are
# not production-observable semantics, so they are scrubbed before hashing. A
# determinism control asserts that two off runs agree after scrubbing.
_GENERATED_ID = re.compile(r"^[a-z][a-z_]*_[0-9a-f]{8,}$")

def _normalize(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _normalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, str) and _GENERATED_ID.match(value):
        return "<id>"
    return value


@dataclass(frozen=True)
class TurnBehaviorSnapshot:
    """Only production-observable behaviour; never shadow state."""

    route_hash: str
    pedagogy_plan_hash: str
    retrieval_plan_hash: str
    prompt_context_hash: str
    response: str
    persisted_learning_state_hash: str
    pedagogy_eval_hash: str
    closure_eligibility: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "route_hash": self.route_hash,
            "pedagogy_plan_hash": self.pedagogy_plan_hash,
            "retrieval_plan_hash": self.retrieval_plan_hash,
            "prompt_context_hash": self.prompt_context_hash,
            "response": self.response,
            "persisted_learning_state_hash": self.persisted_learning_state_hash,
            "pedagogy_eval_hash": self.pedagogy_eval_hash,
            "closure_eligibility": self.closure_eligibility,
        }


def _run_turn(tmp_path, *, flag: bool, reader, telemetry=None) -> TurnBehaviorSnapshot:
    import os

    if flag:
        os.environ[SHADOW_FLAG] = "1"
    else:
        os.environ.pop(SHADOW_FLAG, None)
    service, _ = _service(tmp_path, reader=reader, telemetry=telemetry)
    prepared = service.start_turn(
        ChatCommand(user_input="explain hashing", thread_id="thread-shadow")
    )
    return TurnBehaviorSnapshot(
        route_hash=canonical_hash(_normalize(prepared.route)),
        pedagogy_plan_hash=canonical_hash(_normalize(prepared.pedagogy_plan.to_dict())),
        retrieval_plan_hash=canonical_hash(_normalize(prepared.rag.get("query_plan"))),
        prompt_context_hash=canonical_hash(_normalize(prepared.messages)),
        response=prepared.turn.assistant_message,
        persisted_learning_state_hash=canonical_hash(
            _normalize(prepared.turn.pedagogy_snapshot.get("learning_state_after"))
        ),
        pedagogy_eval_hash=canonical_hash(_normalize(prepared.learner_evaluation.to_dict())),
        closure_eligibility=_requires_mastery_evidence(prepared.pedagogy_plan),
    )


def _snapshot() -> LearnerModelSnapshot:
    return LearnerModelSnapshot(
        thread_id="thread-shadow", goal_id="goal-1", objective="explain hashing",
        claim_states=(LearnerClaimState("c1", "r1", "fact", "confirmed", "pass"),),
    )


@pytest.fixture(autouse=True)
def _clean_flag(monkeypatch):
    monkeypatch.delenv(SHADOW_FLAG, raising=False)
    yield
    import os

    os.environ.pop(SHADOW_FLAG, None)


# ---------------------------------------------------------------- scenarios

def _paired(tmp_path, name: str, *, reader, telemetry=None):
    """Each scenario gets its own off baseline from the same fixture."""
    off = _run_turn(tmp_path / f"{name}-off", flag=False, reader=reader)
    on = _run_turn(tmp_path / f"{name}-on", flag=True, reader=reader, telemetry=telemetry)
    return off, on


def test_normal_shadow_is_behaviourally_identical(tmp_path) -> None:
    off, on = _paired(tmp_path, "normal", reader=_snapshot)
    assert off.to_dict() == on.to_dict()


def test_reader_error_is_behaviourally_identical(tmp_path) -> None:
    def explode(thread_id: str) -> object:
        raise RuntimeError("durable read exploded")

    off, on = _paired(tmp_path, "throw", reader=explode)
    assert off.to_dict() == on.to_dict()


def test_reader_stall_is_behaviourally_identical(tmp_path) -> None:
    release = threading.Event()

    def stall(thread_id: str) -> object:
        release.wait(timeout=5)
        return _snapshot()

    off, on = _paired(tmp_path, "stall", reader=stall)
    assert off.to_dict() == on.to_dict()
    release.set()


def test_capacity_exhaustion_is_behaviourally_identical(tmp_path) -> None:
    held = [iso._capacity.acquire(blocking=False) for _ in range(SHADOW_CAPACITY)]
    try:
        off, on = _paired(tmp_path, "capacity", reader=_snapshot)
        assert off.to_dict() == on.to_dict()
    finally:
        for _ in held:
            iso._capacity.release()


def test_parity_projection_error_is_behaviourally_identical(tmp_path) -> None:
    class ExplodingSnapshot:
        @property
        def claim_states(self):
            raise RuntimeError("projection exploded")

    off, on = _paired(tmp_path, "parity", reader=lambda thread_id: ExplodingSnapshot())
    assert off.to_dict() == on.to_dict()


def test_telemetry_failure_is_behaviourally_identical(tmp_path) -> None:
    class BrokenSink:
        def record(self, observation: object) -> None:
            raise RuntimeError("collector down")

    telemetry = BestEffortTelemetry(BrokenSink())
    off, on = _paired(tmp_path, "telemetry-throw", reader=_snapshot, telemetry=telemetry)
    assert off.to_dict() == on.to_dict()
    telemetry.close()


def test_slow_telemetry_is_behaviourally_identical(tmp_path) -> None:
    class SlowSink:
        def record(self, observation: object) -> None:
            time.sleep(0.4)

    telemetry = BestEffortTelemetry(SlowSink())
    off, on = _paired(tmp_path, "telemetry-slow", reader=_snapshot, telemetry=telemetry)
    assert off.to_dict() == on.to_dict()
    telemetry.close()


# ------------------------------------------------------ latency delta (frozen)

@pytest.mark.parametrize("mode", ["stall", "rejected", "error"])
def test_production_path_latency_delta_is_bounded(tmp_path, mode: str) -> None:
    release = threading.Event()

    def stall(thread_id: str) -> object:
        release.wait(timeout=5)
        return _snapshot()

    def explode(thread_id: str) -> object:
        raise RuntimeError("boom")

    reader = {"stall": stall, "rejected": _snapshot, "error": explode}[mode]
    held = [iso._capacity.acquire(blocking=False) for _ in range(SHADOW_CAPACITY)] \
        if mode == "rejected" else []

    try:
        started = time.monotonic()
        _run_turn(tmp_path / f"{mode}-off", flag=False, reader=reader)
        off_elapsed = time.monotonic() - started

        started = time.monotonic()
        _run_turn(tmp_path / f"{mode}-on", flag=True, reader=reader)
        on_elapsed = time.monotonic() - started
    finally:
        for _ in held:
            iso._capacity.release()
        release.set()

    assert on_elapsed - off_elapsed <= LATENCY_DELTA_BOUND_SECONDS, (
        mode, on_elapsed - off_elapsed
    )


# ------------------------------------------------------- invocation proof

def test_real_start_turn_invokes_the_reader_exactly_once(tmp_path) -> None:
    calls: list[str] = []

    def counting_reader(thread_id: str) -> object:
        calls.append(thread_id)
        return _snapshot()

    collector = LearnerStateParityCollector()
    telemetry = BestEffortTelemetry(collector)
    snapshot = _run_turn(tmp_path, flag=True, reader=counting_reader, telemetry=telemetry)

    assert calls == ["thread-shadow"], calls
    assert snapshot.response == ""
    assert telemetry.flush(timeout=1.0) is True
    recorded = collector.observations()
    assert len(recorded) == 1
    assert recorded[0]["turn_start_persistence_confirmed"] is True
    assert recorded[0]["decision_inputs"]["prompt_context_hash"] == snapshot.prompt_context_hash
    telemetry.close()


def test_flag_off_never_invokes_the_reader(tmp_path) -> None:
    calls: list[str] = []

    def counting_reader(thread_id: str) -> object:
        calls.append(thread_id)
        return _snapshot()

    _run_turn(tmp_path, flag=False, reader=counting_reader)
    assert calls == []


def test_no_reader_wired_never_invokes_anything(tmp_path) -> None:
    snapshot = _run_turn(tmp_path, flag=True, reader=None)
    assert snapshot.response == ""


def test_frozen_latency_bound_is_documented_before_measurement() -> None:
    assert isinstance(LATENCY_DELTA_BOUND_SECONDS, float)
    assert LATENCY_DELTA_BOUND_SECONDS >= DEFAULT_SHADOW_BUDGET_SECONDS


def test_off_baseline_is_deterministic(tmp_path) -> None:
    """Control: two off runs must agree, so an off/on difference is meaningful."""
    first = _run_turn(tmp_path / "det-1", flag=False, reader=_snapshot)
    second = _run_turn(tmp_path / "det-2", flag=False, reader=_snapshot)
    assert first.to_dict() == second.to_dict()
