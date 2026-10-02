"""§164.33 S1/S2 rollout observation with REAL durable truth (multi-sample).

Each sample runs the full chain on its own temporary database: a legacy-substantive
thread, a real closure that writes durable truth, then real chat turns with the
phase-two durable read ON. The emitted ``durable_adjudication`` record is read back
from each persisted turn and audited against the frozen contract.

Audits performed here:

* G1 / A5 - the objective gate. A ``diff`` sample has genuinely different legacy and
  durable objectives, where a durable-preferred objective with a differing value is
  expected and A5 must NOT fire. An ``equal`` sample has identical objectives, where
  the gate must report a match and must NOT report a conflict; a conflict there would
  be an A5 abort.
* I2 - the reader is wrapped with a counter, so the exactly-once invariant is measured
  on the real path rather than assumed.

Observation-only: the phase-two flag is enabled inside this process alone, no
production configuration changes, and durable truth is written only through the real
closure path.
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
from src.application.learner_state_durable_adapter import DURABLE_READ_FLAG
from src.application.learner_state_parity_observer import (
    observe_learner_state_parity,
)
from src.application.learning_closure_service import LearningClosureService
from src.application.learning_closure_truth import LearningClosureTruthService
from src.application.memory_service import MemoryService
from src.application.session_service import SessionService
from src.domain.runtime_entities import ChatThread, ChatTurn
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.mode_manager import RuntimeModes
from src.pedagogy.engine import PedagogyEngine
from src.pedagogy.evaluation import PedagogyEvaluationService
from src.pedagogy.types import LearningState
from src.repositories.learning_closure_repository import LearningClosureRepository
from src.repositories.learning_truth_repository import LearningTruthRepository
from src.repositories.memory_repository import MemoryRepository
from src.repositories.runtime_repository import RuntimeRepository
from src.tools.web_agent import WebToolTrace

COMMIT_SHA = "e" * 40
TREE_SHA = "f" * 40
REPO_URL = "https://github.com/2002yy/study-agent"
CLAIM = "durable resume keeps the objective readable across turns"

SAMPLES = (
    {
        "sid": "diff",
        "legacy": "recover durable resume",
        "durable": "recover session recovery by durable owner",
        "expect": "durable_preferred_with_diverging_objective",
    },
    {
        "sid": "equal",
        "legacy": "recover durable resume",
        "durable": "recover durable resume",
        "expect": "gate_match_no_conflict",
    },
)

TURNS = (
    "explain how durable resume works",
    "why does recovery need to span turns?",
)

# Per-sample values consumed by the module-level fakes.
_SAMPLE: dict = {}


class _FakeRag:
    def to_dict(self):
        return {"status": "none", "results": []}


class _CountingReader:
    """Wraps the durable reader to measure the exactly-once invariant (I2)."""

    def __init__(self, service) -> None:
        self._service = service
        self.calls = 0

    def __call__(self, thread_id: str):
        self.calls += 1
        return self._service.build(thread_id)


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
            objective=_SAMPLE.get("durable", "durable objective"),
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


def _run_sample(sample: dict, root: Path) -> dict:
    sid = sample["sid"]
    tmp = root / sid
    tmp.mkdir(parents=True, exist_ok=True)
    thread_id = f"s2r-{sid}"
    _SAMPLE.clear()
    _SAMPLE.update(sample)

    database = RuntimeDatabase(tmp / "runtime.db")
    runtime = RuntimeRepository(database)
    runtime.create_chat_thread(
        ChatThread(
            id=thread_id,
            learning_state={
                "protocol": "socratic_rediscovery",
                "objective": sample["legacy"],
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
    session = SessionService(runtime, current_dir=tmp / "cur", archive_dir=tmp / "arc")
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

    lms = LearnerModelService(
        LearningTruthRepository(database),
        eval_repo,  # type: ignore[arg-type]
        read_confirmed_profile=lambda: "",
    )
    probe = lms.build(thread_id)
    reader = _CountingReader(lms)

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
        read_learner_model=reader,
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

    # A5 via the parity instrument (the adjudication record has no conflict value).
    # The legacy side must be the persisted, un-adjudicated thread state: with Phase 2
    # on, prepared.learning_state_before is already the adjudicated value.
    legacy_side = LearningState.from_dict(
        runtime.get_chat_thread(thread_id).learning_state
    )
    parity_obs = observe_learner_state_parity(
        thread_id=thread_id,
        turn_id="turn-seed",
        learning_state=legacy_side,
        snapshot=lms.build(thread_id),
        provenance={"collection": "164.33", "audit": "A5"},
    )
    parity_g1 = next(
        (
            v.classification
            for v in parity_obs.dimensions
            if getattr(v, "dimension", "") == "goal_objective"
        ),
        None,
    )

    return {
        "parity_overall": parity_obs.overall_classification,
        "parity_goal_objective": parity_g1,
        "sample_id": sid,
        "expectation": sample["expect"],
        "legacy_objective": sample["legacy"],
        "durable_objective": getattr(probe, "objective", ""),
        "closure": {"create": run.status, "commit": committed.status},
        "turn_count": len(records),
        "adjudication_emitted": sum(1 for r in records if r["adjudication_present"]),
        "durable_preferred_turns": sum(1 for r in records if r["used_durable"]),
        "gate_counts": dict(sorted(gate_counts.items())),
        "decision_counts": dict(sorted(decision_counts.items())),
        "reader_calls": reader.calls,
        "records": records,
    }


def main() -> int:
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("s2_real.json")
    root = Path(tempfile.mkdtemp(prefix="s2-real-"))

    os.environ[DURABLE_READ_FLAG] = "1"
    saved_modes = memory_service_module.load_runtime_modes
    saved_allowed = memory_service_module.is_memory_write_allowed
    try:
        results = [_run_sample(s, root) for s in SAMPLES]
    finally:
        os.environ.pop(DURABLE_READ_FLAG, None)
        memory_service_module.load_runtime_modes = saved_modes
        memory_service_module.is_memory_write_allowed = saved_allowed

    # --- audits -------------------------------------------------------------
    i2 = all(r["reader_calls"] == r["turn_count"] for r in results)
    # A5: audited with the parity instrument, which is what actually emits CONFLICT.
    a5 = [
        {
            "sample": r["sample_id"],
            "objectives_equal": r["legacy_objective"] == r["durable_objective"],
            "goal_objective_parity": r["parity_goal_objective"],
            "overall_parity": r["parity_overall"],
        }
        for r in results
    ]
    a5_abort = any(
        item["objectives_equal"] and item["goal_objective_parity"] == "CONFLICT"
        for item in a5
    )

    payload = {
        "schema_version": "phase2-rollout-observation-v1",
        "contract": "164.33",
        "environment": "controlled harness with real durable truth (multi-sample)",
        "sample_count": len(results),
        "invariants": {
            "I2_reader_exactly_once": i2,
            "reader_calls_per_sample": {
                r["sample_id"]: r["reader_calls"] for r in results
            },
        },
        "aborts": {
            "A5_objective_conflict_on_equal": a5_abort,
            "G1_audit": a5,
        },
        "samples": results,
    }
    out_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    for r in results:
        print(
            f"{r['sample_id']}: durable_preferred={r['durable_preferred_turns']}/"
            f"{r['turn_count']} reader_calls={r['reader_calls']} "
            f"decisions={r['decision_counts']}"
        )
    print("I2 exactly-once:", i2)
    print("A5 abort:", a5_abort, "| G1:", a5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
