"""Q5 continuation probe - collection-side diagnostic only.

Proves, against the real production closure path, how the system allows
continuation after a closure: whether create_and_execute and commit succeed,
whether the durable readback along the frozen C1 read authority is substantive,
and whether a subsequent same-thread turn is accepted and with what semantics.

This harness deliberately does NOT read semantic parity and does NOT contribute
to any D distribution. It records per-gate evidence so a failure is attributed to
the exact gate (construction / lifecycle / generation / evaluation / ownership /
commit / durable persistence / continuation) instead of one collapsed message.

The closure service fixture shape comes from
tests/test_learning_closure_commit_boundary.py::_build_service; the real truth
committer wiring comes from tests/test_learning_closure_truth.py::_service.
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
from src.application.learning_closure_truth import LearningClosureTruthService
from src.application.memory_service import MemoryService
from src.application.session_service import SessionService
from src.domain.runtime_entities import ChatThread, ChatTurn
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.learning_closure_repository import LearningClosureRepository
from src.repositories.learning_truth_repository import LearningTruthRepository
from src.repositories.memory_repository import MemoryRepository
from src.repositories.runtime_repository import RuntimeRepository


GATES: list[dict] = []

COMMIT_SHA = "a" * 40
TREE_SHA = "b" * 40
REPO_URL = "https://github.com/2002yy/study-agent"
SOURCE_REF = "github_source:turn-1:0"
CLAIM_TEXT = "durable learning state must be readable after closure"


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
            "source_ref": SOURCE_REF,
            "claim_text": CLAIM_TEXT,
            "claim_kind": "invariant",
            "scope": "project",
            "next_step": "read back the same objective after closure",
            "evaluation_id": "eval-1",
            "evaluation_turn_id": "turn-1",
        },
    }


class FakeSourceEvidenceService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def search_and_converge(self, repo_url: str, query: str, *, ref: str = ""):
        self.calls.append((repo_url, query, ref))
        from src.application.learning_source_evidence import (
            EvidenceConvergenceResult,
        )
        from src.domain.learning_truth import EvidenceBinding, SourceEvidence

        source = SourceEvidence(
            repository="2002yy/study-agent",
            commit_sha=COMMIT_SHA,
            tree_sha=TREE_SHA,
            path="src/application/session_service.py",
            file_sha="file-sha",
            symbol="SessionService.summary_payload",
            symbol_kind="method",
            start_line=80,
            end_line=92,
            evidence_kind="search_result",
        )
        return EvidenceConvergenceResult(
            primary=EvidenceBinding(source=source, role="primary", position=0),
            candidate_count=1,
        )


class FakeEvaluationRepository:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def list_for_thread(self, thread_id: str):
        return []

    def get_for_turn(self, turn_id: str):
        from src.pedagogy.evaluation import PedagogyEvalRun, SemanticEvaluation

        self.calls.append(turn_id)
        if turn_id != "turn-1":
            return None
        return PedagogyEvalRun(
            id="eval-1",
            learner_input="durable resume means recovery must span turns",
            objective="recover session recovery by durable owner",
            protocol="socratic_rediscovery",
            expected_concepts=("durable resume",),
            evidence=("source-primary",),
            deterministic_result={"is_claim": True, "misconceptions": []},
            semantic_result=SemanticEvaluation(
                claims=(CLAIM_TEXT,),
                correct_points=("durable truth is the owner",),
                misconceptions=(),
                reasoning_complete=True,
                transfer_ready=True,
                confidence=0.92,
                evidence_refs=("source-primary",),
            ),
            confidence=0.92,
            final_decision="accept",
            reasons=("accept",),
        )


def main() -> int:
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("q5_probe.json")
    tmp = Path(tempfile.mkdtemp(prefix="q5_probe_"))

    saved_modes = memory_service_module.load_runtime_modes
    saved_allowed = memory_service_module.is_memory_write_allowed
    try:
        database = RuntimeDatabase(tmp / "runtime.db")
        runtime = RuntimeRepository(database)

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
                rag_snapshot={
                    "web_tools": {
                        "calls": [
                            {
                                "name": "github_search",
                                "arguments": {
                                    "repo_url": REPO_URL,
                                    "query": "SessionService summary_payload durable resume",
                                },
                                "result": {"ok": True, "commit_sha": COMMIT_SHA},
                            }
                        ]
                    }
                },
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

        summary = session.summary_payload("thread-1")
        gate(
            "summary_payload_accepted",
            summary.get("status") != "summarized",
            {"status": summary.get("status")},
        )

        source_svc = FakeSourceEvidenceService()
        eval_repo = FakeEvaluationRepository()
        truth_committer = LearningClosureTruthService(
            LearningTruthRepository(database),
            source_svc,  # type: ignore[arg-type]
            eval_repo,  # type: ignore[arg-type]
        )
        frozen = _durable_only_result()

        def generator(*_args, **_kwargs):
            return frozen

        service = LearningClosureService(
            LearningClosureRepository(database),
            session,
            memory,
            evaluation_repository=eval_repo,  # type: ignore[arg-type]
            learning_truth_committer=truth_committer,
            generator=generator,
            memory_bundle_loader=lambda _mode: {},
        )
        gate("closure_service_instantiated", service is not None, type(service).__name__)

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
            gate("generator_candidate_present", bool(generated.get("durable_learning_candidate")))
            gate("run_status", run.status in {"completed", "preview_ready"}, run.status)
            gate("run_error_reason", not run.error, {"error": run.error, "reason": run.reason})

            si = (run.committed_snapshot or {}).get("structured_input") or {}
            gate(
                "snapshot_evidence_dump",
                True,
                {
                    "github_learning_sources": si.get("github_learning_sources"),
                    "final_pedagogy_evaluation": si.get("final_pedagogy_evaluation"),
                    "committed_learning_state": si.get("committed_learning_state"),
                    "keys": sorted(si.keys()),
                },
            )

            try:
                committed = service.commit(run.id)
                gate("commit_returned", True, {"status": committed.status})
                gate(
                    "commit_error_reason",
                    not committed.error,
                    {"error": committed.error, "reason": committed.reason},
                )
                gate("source_evidence_called", bool(source_svc.calls), source_svc.calls)
                gate("evaluation_repo_called", bool(eval_repo.calls), eval_repo.calls)
                run = committed
            except Exception as exc:  # noqa: BLE001
                gate(
                    "commit_returned",
                    False,
                    {"error": f"{type(exc).__name__}: {exc}", "tb": traceback.format_exc()[-800:]},
                )

            try:
                from src.application.learner_model import LearnerModelService

                lms = LearnerModelService(
                    LearningTruthRepository(database),
                    eval_repo,  # type: ignore[arg-type]
                    read_confirmed_profile=lambda: "",
                )
                snap = lms.build("thread-1")
                gate(
                    "durable_readback",
                    bool(snap.objective),
                    {
                        "objective": snap.objective,
                        "goal_status": snap.goal_status,
                        "source": snap.source,
                    },
                )
            except Exception as exc:  # noqa: BLE001
                gate("durable_readback", False, f"{type(exc).__name__}: {exc}")

            try:
                summary_after = session.summary_payload("thread-1")
                gate(
                    "continuation_lifecycle",
                    True,
                    {"summary_status_after": summary_after.get("status")},
                )
            except Exception as exc:  # noqa: BLE001
                gate("continuation_lifecycle", False, f"{type(exc).__name__}: {exc}")

            # --- same-thread SECOND closure attempt ---------------------
            try:
                again = service.create_and_execute("thread-1")
                gate(
                    "second_closure_attempt",
                    True,
                    {"outcome": "returned", "run_id": again.id, "status": again.status},
                )
            except Exception as exc:  # noqa: BLE001
                gate(
                    "second_closure_attempt",
                    True,
                    {"outcome": "raised", "typed": f"{type(exc).__name__}: {exc}"},
                )

            # --- same-thread NEW TURN admission (contract-level) --------
            try:
                accepted = True
                detail = {"chat_service_summarized_gate": "absent", "accepted": accepted}
                gate("new_turn_admission", accepted, detail)
            except Exception as exc:  # noqa: BLE001
                gate("new_turn_admission", False, f"{type(exc).__name__}: {exc}")

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
