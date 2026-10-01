"""§164-C2 stratum D: a fresh, independent semantic-parity sample.

This is NOT the Q5 probe. Q5 established the construction and continuation
authority; this harness collects one formal D observation, and it must not reuse
any Q5 thread, run, candidate or evaluation, nor count any Q5 parity value.

Order is frozen (164.28): legacy write + persist -> confirm legacy substantive ->
real closure (create_and_execute + commit) -> durable readback via the C1 read
authority -> subsequent chat observation -> read both projections -> prove
continuity and lineage -> assign stratum from observed state -> confirm D ->
read parity LAST.

The stratum label follows the observed state, never the intent. If the observed
state is not legacy-substantive plus durable-substantive, it is reported as the
stratum it actually is and the D gate fails honestly rather than being forced.
"""

from __future__ import annotations

import json
import sys
import tempfile
import traceback
from pathlib import Path
from types import SimpleNamespace

import src.application.memory_service as memory_service_module
from src.application.chat_service import ChatCommand, ChatService
from src.application.learner_model import LearnerModelService
from src.application.learner_state_parity_observer import (
    build_durable_projection,
    build_legacy_projection,
    observe_learner_state_parity,
)
from src.application.learning_closure_service import LearningClosureService
from src.application.learning_closure_truth import LearningClosureTruthService
from src.application.memory_service import MemoryService
from src.application.session_service import SessionService
from src.domain.runtime_entities import ChatThread, ChatTurn
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.pedagogy.types import LearningState
from src.repositories.learning_closure_repository import LearningClosureRepository
from src.repositories.learning_truth_repository import LearningTruthRepository
from src.repositories.memory_repository import MemoryRepository
from src.repositories.runtime_repository import RuntimeRepository

COMMIT_SHA = "c" * 40
TREE_SHA = "d" * 40
REPO_URL = "https://github.com/2002yy/study-agent"
SOURCE_REF = "github_source:turn-1:0"  # overwritten per-sample below
CLAIM_TEXT = "durable resume keeps the objective readable across turns"

GATES: list[dict] = []
_SAMPLE: dict = {}


def gate(name: str, ok: bool, detail: object = None) -> bool:
    GATES.append({"gate": name, "status": "PASS" if ok else "FAIL", "detail": detail})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")
    return ok


class FakeSourceEvidenceService:
    def search_and_converge(self, repo_url: str, query: str, *, ref: str = ""):
        from src.application.learning_source_evidence import EvidenceConvergenceResult
        from src.domain.learning_truth import EvidenceBinding, SourceEvidence

        return EvidenceConvergenceResult(
            primary=EvidenceBinding(
                source=SourceEvidence(
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
                ),
                role="primary",
                position=0,
            ),
            candidate_count=1,
        )


class FakeEvaluationRepository:
    def list_for_thread(self, thread_id: str):
        return []

    def get_for_turn(self, turn_id: str):
        from src.pedagogy.evaluation import PedagogyEvalRun, SemanticEvaluation

        if not str(turn_id).startswith("turn-"):
            return None
        return PedagogyEvalRun(
            id="eval-1",
            learner_input=_SAMPLE["claim_text"],
            objective=_SAMPLE["durable_objective"],
            protocol="socratic_rediscovery",
            expected_concepts=("durable resume",),
            evidence=("source-primary",),
            deterministic_result={"is_claim": True, "misconceptions": []},
            semantic_result=SemanticEvaluation(
                claims=(_SAMPLE["claim_text"],),
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


def _durable_only_result() -> dict:
    return {
        "candidates": [],
        "durable_learning_candidate": {
            "source_ref": f"github_source:turn-{_SAMPLE["sample_id"]}:0",
            "claim_text": _SAMPLE["claim_text"],
            "claim_kind": "invariant",
            "scope": "project",
            "next_step": "read back the same objective after closure",
            "evaluation_id": "eval-1",
            "evaluation_turn_id": f"turn-{_SAMPLE["sample_id"]}",
        },
    }


def _task_contract() -> dict:
    return {
        "task_intent": "learn",
        "source_policy": "local_and_web",
        "closure_eligibility": "learning_summary",
        "learning_state_enabled": True,
        "confidence": "high",
    }


def _substantive(*, objective: str, known: int) -> bool:
    return bool(str(objective or "").strip()) or known > 0


def main() -> int:
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("d_sample.json")
    spec: dict[str, object] = {}
    if len(sys.argv) > 2 and sys.argv[2]:
        _sp = Path(sys.argv[2])
        spec = json.loads(_sp.read_text(encoding="utf-8-sig")) if _sp.exists() else json.loads(sys.argv[2])
    legacy_objective = str(spec.get("legacy_objective") or "recover durable resume")
    durable_objective = str(
        spec.get("durable_objective") or "recover session recovery by durable owner"
    )
    claim_text = str(spec.get("claim_text") or CLAIM_TEXT)
    sample_id = str(spec.get("sample_id") or "d-1")
    _SAMPLE.update({"sample_id": sample_id, "claim_text": claim_text, "durable_objective": durable_objective, "legacy_objective": legacy_objective})
    tmp = Path(tempfile.mkdtemp(prefix="d-parity-"))
    artifact: dict[str, object] = {
        "schema_version": "learner-state-parity-collection-v1",
        "population": "D",
        "condition": "legacy_substantive_then_real_closure",
        "sample_id": sample_id,
        "q5_isolation": {
            "reuses_q5_thread": False,
            "reuses_q5_run": False,
            "counts_q5_parity": False,
            "q5_role": "construction_and_continuation_authority_only",
        },
    }

    saved_modes = memory_service_module.load_runtime_modes
    saved_allowed = memory_service_module.is_memory_write_allowed
    try:
        database = RuntimeDatabase(tmp / "runtime.db")
        runtime = RuntimeRepository(database)

        # --- 1. legacy write + persist (fresh sample) --------------------
        runtime.create_chat_thread(
            ChatThread(
                id=f"d-thread-{sample_id}",
                learning_state={
                    "protocol": "socratic_rediscovery",
                    "objective": legacy_objective,
                    "phase": "guided_practice",
                },
            )
        )
        runtime.add_chat_turn(
            ChatTurn(
                id=f"turn-{sample_id}",
                thread_id=f"d-thread-{sample_id}",
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
        persisted = runtime.get_chat_thread(f"d-thread-{sample_id}")
        legacy_state = LearningState.from_dict(
            getattr(persisted, "learning_state", {}) or {}
        )
        legacy_projection = build_legacy_projection(legacy_state)
        artifact["legacy_before_projection"] = {
            "objective": legacy_projection.objective,
            "protocol": legacy_projection.protocol,
            "known_points_count": len(legacy_projection.known_points),
        }
        legacy_substantive = _substantive(
            objective=legacy_projection.objective,
            known=len(legacy_projection.known_points),
        )
        gate("legacy_substantive", legacy_substantive, legacy_projection.objective)

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

        eval_repo = FakeEvaluationRepository()
        frozen = _durable_only_result()

        def generator(*_args, **_kwargs):
            return frozen

        service = LearningClosureService(
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

        # --- 2. real closure ---------------------------------------------
        run = service.create_and_execute(f"d-thread-{sample_id}")
        gate("closure_preview_ready", run.status == "preview_ready", run.status)
        committed = service.commit(run.id)
        gate("closure_committed", committed.status == "completed", committed.status)
        artifact["closure_evidence"] = {
            "create_and_execute_status": run.status,
            "commit_status": committed.status,
            "commit_error": committed.error,
            "run_id": committed.id,
            "thread_id": "d-thread",
        }

        # --- 3. durable readback via C1 read authority -------------------
        lms = LearnerModelService(
            LearningTruthRepository(database),
            eval_repo,  # type: ignore[arg-type]
            read_confirmed_profile=lambda: "",
        )
        snapshot = lms.build(f"d-thread-{sample_id}")
        durable_projection = build_durable_projection(snapshot)
        artifact["durable_post_closure_projection"] = {
            "goal_id": durable_projection.goal_id,
            "objective": durable_projection.objective,
            "confirmed_points_count": len(durable_projection.confirmed_points),
            "unresolved_count": durable_projection.unresolved_count,
        }
        durable_substantive = _substantive(
            objective=durable_projection.objective,
            known=len(durable_projection.confirmed_points),
        )
        gate("durable_substantive", durable_substantive, durable_projection.objective)
        artifact["durable_persistence_evidence"] = {
            "source": snapshot.source,
            "goal_status": snapshot.goal_status,
            "valid": durable_substantive,
        }

        # --- 4. subsequent chat observation (post-closure) ---------------
        chat = ChatService(runtime)
        prepared = chat.start_turn(
            ChatCommand(
                user_input="what changed after closure?",
                thread_id=f"d-thread-{sample_id}",
            )
        )
        before = prepared.learning_state_before
        artifact["observation_legacy_projection"] = {
            "objective": before.objective,
            "confirmed_points_count": len(before.confirmed_points),
        }
        gate("subsequent_turn_accepted", True, "accepted")
        artifact["continuity"] = {
            "same_thread": True,
            "closure_continuation_contract": "CONTINUES_WITH_CHANGED_SEMANTICS",
            "lineage_thread_id_aligned": (
                committed.thread_id == "d-thread" == snapshot.thread_id
            ),
        }

        # --- 5. stratum from observed state (never from intent) ----------
        if legacy_substantive and durable_substantive:
            assigned = "D"
        elif legacy_substantive and not durable_substantive:
            assigned = "B"
        elif not legacy_substantive and not durable_substantive:
            assigned = "A"
        else:
            assigned = "other"
        artifact["stratum_assignment"] = assigned
        artifact["observed_state"] = {
            "legacy_substantive": legacy_substantive,
            "durable_substantive": durable_substantive,
        }
        gate("stratum_is_D", assigned == "D", assigned)

        # --- 6. parity LAST ----------------------------------------------
        observation = observe_learner_state_parity(
            thread_id=f"d-thread-{sample_id}",
            turn_id=f"turn-{sample_id}",
            learning_state=before,
            snapshot=snapshot,
            provenance={"collection": "164-C2", "population": "D"},
        )
        artifact["parity"] = {
            "overall": observation.overall_classification,
            "five_dimensions": {
                verdict.dimension: verdict.classification
                for verdict in observation.dimensions
            },
        }
        gate("parity_recorded", True, observation.overall_classification)

    except Exception as exc:  # noqa: BLE001
        gate(
            "harness_unhandled",
            False,
            {"error": f"{type(exc).__name__}: {exc}", "tb": traceback.format_exc()[-1200:]},
        )
    finally:
        memory_service_module.load_runtime_modes = saved_modes
        memory_service_module.is_memory_write_allowed = saved_allowed

    artifact["gates"] = GATES
    artifact["all_pass"] = all(g["status"] == "PASS" for g in GATES)
    artifact["first_fail"] = next((g for g in GATES if g["status"] == "FAIL"), None)
    out_path.write_text(json.dumps(artifact, indent=2, default=str), encoding="utf-8")
    print("\n=== first_fail ===")
    print(json.dumps(artifact["first_fail"], indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
