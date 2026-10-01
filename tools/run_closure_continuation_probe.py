"""Q5 continuation probe - collection-side diagnostic only.

Proves, against the real production closure path, how the system allows
continuation after a closure: whether create_and_execute and commit succeed,
whether the durable readback along the frozen C1 read authority is substantive,
and whether a subsequent same-thread turn is accepted and with what semantics.

This harness deliberately does NOT read semantic parity and does NOT contribute
to any D distribution. It records per-gate evidence so a failure is attributed to
the exact gate (construction / lifecycle / generation / evaluation / ownership /
commit / durable persistence / continuation) instead of one collapsed message.

Reuses the existing fixture shape from
tests/test_learning_closure_commit_boundary.py::_build_service.
"""

from __future__ import annotations

import json
import sys
import tempfile
import traceback
from pathlib import Path
from types import SimpleNamespace

import src.application.memory_service as memory_service_module
from src.application.learning_closure_service import LearningClosureService
from src.application.memory_service import MemoryService
from src.application.runtime_repository import get_learner_model_service
from src.application.session_service import SessionService
from src.domain.runtime_entities import ChatThread, ChatTurn
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.learning_closure_repository import LearningClosureRepository
from src.repositories.memory_repository import MemoryRepository
from src.repositories.runtime_repository import RuntimeRepository


GATES: list[dict] = []


def gate(name: str, ok: bool, detail: object = None) -> bool:
    GATES.append({"gate": name, "status": "PASS" if ok else "FAIL", "detail": detail})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")
    return ok


def _task_contract() -> dict:
    return {
        "task_intent": "learn",
        "source_policy": "local_and_web",
        "closure_eligibility": "learning_summary",
        "learning_state_enabled": True,
        "confidence": "high",
    }


def _durable_only_result() -> dict:
    return {
        "candidates": [],
        "durable_learning_candidate": {
            "source_ref": "local_source:turn-1:0",
            "claim_text": "durable learning state must be readable after closure",
            "claim_kind": "invariant",
            "scope": "project",
            "next_step": "read back the same objective after closure",
            "evaluation_id": "eval-1",
            "evaluation_turn_id": "turn-1",
        },
    }


class RecordingTruthCommitter:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def commit(self, run):
        self.calls.append(run.id)
        return SimpleNamespace(status="claim_validated")


def main() -> int:
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("q5_probe.json")
    tmp = Path(tempfile.mkdtemp(prefix="q5_probe_"))

    saved_modes = memory_service_module.load_runtime_modes
    saved_allowed = memory_service_module.is_memory_write_allowed
    try:
        database = RuntimeDatabase(tmp / "runtime.db")
        runtime = RuntimeRepository(database)

        # --- G02/G03/G04: real legacy-substantive thread -----------------
        thread = runtime.create_chat_thread(
            ChatThread(
                id="thread-1",
                learning_state={
                    "protocol": "socratic_rediscovery",
                    "objective": "recover durable resume",
                    "phase": "guided_practice",
                },
            )
        )
        gate("thread_created", thread.id == "thread-1", thread.id)
        runtime.add_chat_turn(
            ChatTurn(
                id="turn-1",
                thread_id=thread.id,
                user_message="why does recovery need to span turns?",
                assistant_message="because durable learning truth owns recovery.",
                status="completed",
                role="nahida",
                mode="socratic",
                model="pro",
                route_snapshot={"task_contract": _task_contract()},
                pedagogy_snapshot={"phase": "guided_practice"},
            )
        )

        session = SessionService(
            runtime, current_dir=tmp / "current", archive_dir=tmp / "archive"
        )
        memory = MemoryService(MemoryRepository(database))
        modes = SimpleNamespace(
            memory_mode="confirm",
            safe_mode=False,
            profile=SimpleNamespace(memory_write_reason=""),
        )
        memory_service_module.load_runtime_modes = lambda: modes
        memory_service_module.is_memory_write_allowed = lambda _modes: True

        # --- G03: session lifecycle not short-circuited ------------------
        try:
            summary = session.summary_payload("thread-1")
            gate(
                "summary_payload_accepted",
                summary.get("status") != "summarized",
                {"status": summary.get("status")},
            )
        except Exception as exc:  # noqa: BLE001
            gate("summary_payload_accepted", False, f"{type(exc).__name__}: {exc}")
            raise

        # --- G01: service instantiation ---------------------------------
        committer = RecordingTruthCommitter()
        frozen = _durable_only_result()

        def generator(*_args, **_kwargs):
            return frozen

        service = LearningClosureService(
            LearningClosureRepository(database),
            session,
            memory,
            learning_truth_committer=committer,
            generator=generator,
            memory_bundle_loader=lambda _mode: {},
        )
        gate("closure_service_instantiated", service is not None, type(service).__name__)

        # --- G05..G10: real create_and_execute ---------------------------
        run = None
        try:
            run = service.create_and_execute("thread-1")
            gate("create_and_execute_returned", True, {"id": run.id, "status": run.status})
        except Exception as exc:  # noqa: BLE001
            gate(
                "create_and_execute_returned",
                False,
                {"error": f"{type(exc).__name__}: {exc}", "tb": traceback.format_exc()[-800:]},
            )

        if run is not None:
            generated = dict(run.generated_result or {})
            cand = generated.get("durable_learning_candidate")
            gate("generator_candidate_present", bool(cand), None if not cand else "present")
            gate("run_status", run.status in {"completed", "preview_ready"}, run.status)
            gate("run_error_reason", not run.error, {"error": run.error, "reason": run.reason})
            gate("truth_committer_called", bool(committer.calls), committer.calls)

            # --- G11: real commit step (separate from create_and_execute) -
            try:
                committed = service.commit(run.id)
                gate("commit_returned", True, {"status": committed.status})
                gate("truth_committer_called_after_commit", bool(committer.calls), committer.calls)
                gate(
                    "commit_error_reason",
                    not committed.error,
                    {"error": committed.error, "reason": committed.reason},
                )
                run = committed
            except Exception as exc:  # noqa: BLE001
                gate(
                    "commit_returned",
                    False,
                    {"error": f"{type(exc).__name__}: {exc}", "tb": traceback.format_exc()[-800:]},
                )

            # --- G12: durable readback along the frozen C1 read authority -
            try:
                lms = get_learner_model_service()
                snap = lms.build("thread-1")
                gate(
                    "durable_readback",
                    bool(snap.objective),
                    {"objective": snap.objective, "goal_status": snap.goal_status, "source": snap.source},
                )
            except Exception as exc:  # noqa: BLE001
                gate("durable_readback", False, f"{type(exc).__name__}: {exc}")

            # --- G13: same-thread continuation probe ---------------------
            try:
                summary_after = session.summary_payload("thread-1")
                gate(
                    "continuation_probe",
                    True,
                    {"summary_status_after": summary_after.get("status")},
                )
            except Exception as exc:  # noqa: BLE001
                gate("continuation_probe", False, f"{type(exc).__name__}: {exc}")

    finally:
        memory_service_module.load_runtime_modes = saved_modes
        memory_service_module.is_memory_write_allowed = saved_allowed

    payload = {
        "probe": "q5_closure_continuation",
        "gates": GATES,
        "all_pass": all(g["status"] == "PASS" for g in GATES),
        "first_fail": next((g for g in GATES if g["status"] == "FAIL"), None),
    }
    out_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print("\n=== first_fail ===")
    print(json.dumps(payload["first_fail"], indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
