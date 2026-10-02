"""§164.33 S1/S2 rollout observation with REAL durable truth.

Extends the observation window so the phase-two reader is backed by real durable truth
produced by a real closure, rather than an empty snapshot. The chat service and the
closure live on the same temporary database, so the emitted adjudication record shows the
durable-preferred path and the gate outcomes that the deployment contract's audit
(A5 / I2) depends on.

Observation-only: enables the phase-two flag inside this process only, touches no
production configuration, and writes durable truth only through the real closure path.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import src.application.memory_service as memory_service_module
from src.application.chat_service import ChatCommand, ChatDependencies, ChatService
from src.application.learner_model import LearnerModelService
from src.application.learning_closure_service import LearningClosureService
from src.application.learning_closure_truth import LearningClosureTruthService
from src.application.learner_state_durable_adapter import DURABLE_READ_FLAG
from src.application.memory_service import MemoryService
from src.application.session_service import SessionService
from src.domain.runtime_entities import ChatThread, ChatTurn
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.mode_manager import RuntimeModes
from src.pedagogy.engine import PedagogyEngine
from src.pedagogy.evaluation import PedagogyEvaluationService
from src.repositories.learning_closure_repository import LearningClosureRepository
from src.repositories.learning_truth_repository import LearningTruthRepository
from src.repositories.memory_repository import MemoryRepository
from src.repositories.runtime_repository import RuntimeRepository
from src.tools.web_agent import WebToolTrace

COMMIT_SHA = "e" * 40
TREE_SHA = "f" * 40
REPO_URL = "https://github.com/2002yy/study-agent"
CLAIM = "durable resume keeps the objective readable across turns"

TURNS = (
    "explain how durable resume works",
    "why does recovery need to span turns?",
)


class _FakeRag:
    def to_dict(self):
        return {"status": "none", "results": []}


class FakeSourceEvidenceService:
    def search_and_converge(self, repo_url, query, *, ref=""):
        from src.application.learning_source_evidence import EvidenceConvergenceResult
        from src.domain.learning_truth import EvidenceBinding, SourceEvidence

        return EvidenceConvergenceResult(
            primary=EvidenceBinding(
                source=SourceEvidence(
                    repository="2002yy/study-agent",
                    commit_sha=COMMIT_SHA,
                    tree_sha=TREE_SHA,
                    path="src/application/session_service.py",
                    file_sha="fs",
                    symbol="SessionService.summary_payload",
                    symbol_kind="method",
                    start_line=80,
                    end_line=92,
                    evidence_kind="search_result",
                ),
                role="primary",
                position=0,
            ),
            candidate_count=1,
        )


class FakeEvaluationRepository:
    def list_for_thread(self, thread_id):
        return []

    def get_for_turn(self, turn_id):
        from src.pedagogy.evaluation import PedagogyEvalRun, SemanticEvaluation

        if not str(turn_id).startswith("turn-"):
            return None
        return PedagogyEvalRun(
            id="eval-1",
            learner_input=CLAIM,
            objective="recover session recovery by durable owner",
            protocol="socratic_rediscovery",
            expected_concepts=("durable resume",),
            evidence=("source-primary",),
            deterministic_result={"is_claim": True, "misconceptions": []},
            semantic_result=SemanticEvaluation(
                claims=(CLAIM,),
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


def _task_contract():
    return {
        "task_intent": "learn",
        "source_policy": "local_and_web",
        "closure_eligibility": "learning_summary",
        "learning_state_enabled": True,
        "confidence": "high",
    }


def main() -> int:
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("s2_real.json")
    tmp = Path(tempfile.mkdtemp(prefix="s2-real-"))
    thread_id = "s2r-thread-1"

    os.environ[DURABLE_READ_FLAG] = "1"
    saved_modes = memory_service_module.load_runtime_modes
    saved_allowed = memory_service_module.is_memory_write_allowed
    try:
        database = RuntimeDatabase(tmp / "runtime.db")
        runtime = RuntimeRepository(database)
        runtime.create_chat_thread(
            ChatThread(
                id=thread_id,
                learning_state={
                    "protocol": "socratic_rediscovery",
                    "objective": "recover durable resume",
                    "confirmed_points": ["durable resume"],
                    "phase": "guided_practice",
                },
            )
        )
        runtime.add_chat_turn(
            ChatTurn(
                id="turn-seed",
                thread_id=thread_id,
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
            runtime, current_dir=tmp / "cur", archive_dir=tmp / "arc"
        )
        memory = MemoryService(MemoryRepository(database))
        modes = SimpleNamespace(
            memory_mode="confirm",
            safe_mode=False,
            profile=SimpleNamespace(memory_write_reason=""),
        )
        memory_service_module.load_runtime_modes = lambda: modes
        memory_service_module.is_memory_write_allowed = lambda _m: True

        eval_repo = FakeEvaluationRepository()
        frozen = {
            "candidates": [],
            "durable_learning_candidate": {
                "source_ref": "github_source:turn-seed:0",
                "claim_text": CLAIM,
                "claim_kind": "invariant",
                "scope": "project",
                "next_step": "read back the objective after closure",
                "evaluation_id": "eval-1",
                "evaluation_turn_id": "turn-seed",
            },
        }

        def generator(*_a, **_k):
            return frozen

        closure = LearningClosureService(
            LearningClosureRepository(database),
            session,
            memory,
            evaluation_repository=eval_repo,  # type: ignore[arg-type]
            learning_truth_committer=LearningClosureTruthService(
                LearningTruthRepository(database),
                FakeSourceEvidenceService(),  # type: ignore[arg-type]
                eval_repo,  # type: ignore[arg-type]
            ),
            generator=generator,
            memory_bundle_loader=lambda _mode: {},
        )
        run = closure.create_and_execute(thread_id)
        committed = closure.commit(run.id)

        # The real durable reader, on the same database.
        lms = LearnerModelService(
            LearningTruthRepository(database),
            eval_repo,  # type: ignore[arg-type]
            read_confirmed_profile=lambda: "",
        )
        snapshot_probe = lms.build(thread_id)

        # Chat service on the same database, with the real reader.
        deps = ChatDependencies(
            load_runtime_modes=lambda: RuntimeModes(
                memory_mode="preview", performance_mode="standard"
            ),
            read_memory_bundle=lambda context_mode: {},
            build_role_prompt=lambda role, **kw: f"role:{role}",
            route_request=lambda **kw: {
                "role": "nahida",
                "mode": "socratic",
                "model_profile": "flash",
                "reason": "t",
            },
            retrieve_local_knowledge=lambda *a, **k: _FakeRag(),
            build_messages=lambda **kw: [
                {"role": "system", "content": kw["role_prompt"]},
                {"role": "user", "content": kw["user_input"]},
            ],
            chat=lambda *a, **k: "complete reply",
            stream_chat=lambda *a, **k: iter(["part"]),
            chat_max_tokens=lambda pm: 1000,
            resolve_web_tools=lambda *a, **k: WebToolTrace(enabled=False),
            pedagogy_engine=PedagogyEngine(),
            pedagogy_evaluation=PedagogyEvaluationService(),
            read_learner_model=lambda tid: lms.build(tid),
        )
        chat = ChatService(runtime, deps)

        records = []
        for index, text in enumerate(TURNS):
            prepared = chat.start_turn(ChatCommand(user_input=text, thread_id=thread_id))
            chat.complete_turn(prepared, " reply")
            turn = runtime.list_chat_turns(thread_id)[-1]
            snap = dict(getattr(turn, "pedagogy_snapshot", {}) or {})
            adj = snap.get("durable_adjudication")
            records.append(
                {
                    "turn_index": index,
                    "turn_id": turn.id,
                    "adjudication_present": adj is not None,
                    "used_durable": bool(adj and adj.get("used_durable")),
                    "decisions": (adj or {}).get("decisions", []),
                }
            )

        gate_counts: Counter[str] = Counter()
        decision_counts: Counter[str] = Counter()
        for r in records:
            for d in r["decisions"]:
                gate_counts[d.get("gate")] += 1
                decision_counts[d.get("decision")] += 1
        payload = {
            "schema_version": "phase2-rollout-observation-v1",
            "contract": "164.33",
            "environment": "controlled harness with real durable truth",
            "closure": {
                "create_status": run.status,
                "commit_status": committed.status,
                "durable_objective": getattr(snapshot_probe, "objective", ""),
            },
            "legacy_objective": "recover durable resume",
            "turn_count": len(records),
            "adjudication_emitted_count": sum(
                1 for r in records if r["adjudication_present"]
            ),
            "durable_preferred_turns": sum(1 for r in records if r["used_durable"]),
            "gate_counts": dict(sorted(gate_counts.items())),
            "decision_counts": dict(sorted(decision_counts.items())),
            "records": records,
        }
        out_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print("closure:", run.status, committed.status, "| durable_obj:", getattr(snapshot_probe, "objective", ""))
        print("turns:", len(records), "emitted:", payload["adjudication_emitted_count"], "durable_preferred:", payload["durable_preferred_turns"])
        print("gates:", payload["gate_counts"])
        print("decisions:", payload["decision_counts"])
    finally:
        os.environ.pop(DURABLE_READ_FLAG, None)
        memory_service_module.load_runtime_modes = saved_modes
        memory_service_module.is_memory_write_allowed = saved_allowed
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
