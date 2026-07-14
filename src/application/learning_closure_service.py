"""Application owner for durable, resumable learning closure."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
import hashlib
import json
from typing import Any

from src.after_session import after_session_to_memory_updates
from src.application.closure_input_builder import build_structured_closure_input
from src.application.memory_service import MemoryService
from src.application.session_service import SessionService
from src.domain.learning_closure import LearningClosureRun
from src.domain.runtime_entities import new_id
from src.memory import read_memory_bundle
from src.repositories.learning_closure_repository import LearningClosureRepository
from src.repositories.pedagogy_eval_repository import PedagogyEvalRepository
from src.structured_closure import (
    generate_structured_closure_candidates,
    structured_candidates_to_memory_updates,
)
from src.task_contract import task_contract_from_snapshot

_ALLOWED_CLOSURES = {"learning_summary", "project_summary"}
_LEGACY_LEARNING_PROTOCOLS = {
    "socratic_rediscovery",
    "feynman_diagnosis",
    "project_execution",
}


class LearningClosureNotEligible(ValueError):
    pass


class LearningClosureCancelled(RuntimeError):
    pass


Generator = Callable[..., dict[str, Any]]
MemoryBundleLoader = Callable[[str], dict[str, str]]


def _canonical_hash(value: dict[str, Any]) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class LearningClosureService:
    """Own one immutable closure workflow per committed thread source."""

    def __init__(
        self,
        repository: LearningClosureRepository,
        session_service: SessionService,
        memory_service: MemoryService,
        *,
        evaluation_repository: PedagogyEvalRepository | None = None,
        generator: Generator = generate_structured_closure_candidates,
        memory_bundle_loader: MemoryBundleLoader = read_memory_bundle,
    ):
        self.repository = repository
        self.session_service = session_service
        self.memory_service = memory_service
        self.evaluation_repository = evaluation_repository
        self.generator = generator
        self.memory_bundle_loader = memory_bundle_loader

    def create_and_execute(self, thread_id: str) -> LearningClosureRun:
        snapshot, eligibility, source_hash = self._collect_source(thread_id)
        existing = self.repository.find_by_source_hash(source_hash)
        if existing is not None:
            if existing.status in {
                "collecting",
                "generating",
                "preview_ready",
                "committing",
                "completed",
            }:
                return existing
            return self.execute(existing.id)

        run = self.repository.create(
            LearningClosureRun(
                thread_id=thread_id,
                source_thread_version=int(snapshot["source_thread_version"]),
                last_completed_turn_id=str(snapshot["last_completed_turn_id"]),
                source_hash=source_hash,
                closure_eligibility=eligibility,
                committed_snapshot=snapshot,
            )
        )
        if run.status != "created":
            return run
        return self.execute(run.id)

    def execute(self, run_id: str) -> LearningClosureRun:
        existing = self.get(run_id)
        if existing.status in {"preview_ready", "completed"}:
            return existing
        if existing.status in {"collecting", "generating", "committing"}:
            return existing
        operation_id = new_id("closure_generate")
        resume_status = "generating" if existing.generated_result else "collecting"
        run = self.repository.begin_operation(
            run_id,
            operation_id=operation_id,
            status=resume_status,
        )
        try:
            self._ensure_active(run.id, operation_id)
            if run.status == "collecting":
                run = self.repository.transition_to_generating(
                    run.id,
                    operation_id=operation_id,
                )

            generated = dict(run.generated_result)
            if not generated:
                snapshot = run.committed_snapshot
                last_turn = dict(snapshot.get("last_turn") or {})
                generated = self.generator(
                    dict(snapshot.get("structured_input") or {}),
                    self.memory_bundle_loader("light"),
                    str(last_turn.get("role") or "auto"),
                    str(last_turn.get("mode") or "auto"),
                    model_profile="pro",
                )
                run = self.repository.checkpoint_generated(
                    run.id,
                    operation_id=operation_id,
                    generated_result=generated,
                )

            self._ensure_active(run.id, operation_id)
            updates = self._memory_updates(generated)
            if not updates:
                raise ValueError("无可靠且有来源的记忆候选")
            memory_run = self.memory_service.create(
                updates,
                run_id=f"memory_{run.id}",
            )
            if memory_run.status not in {"previewed", "succeeded"}:
                raise ValueError(
                    "Linked MemoryRun is not retryable: "
                    f"{memory_run.id} ({memory_run.status})"
                )
            self._ensure_active(run.id, operation_id)
            preview = self.repository.set_preview_ready(
                run.id,
                operation_id=operation_id,
                memory_run_id=memory_run.id,
            )
            if memory_run.status == "succeeded":
                return self.commit(preview.id)
            return preview
        except LearningClosureCancelled:
            return self.repository.finish_cancel(
                run.id,
                operation_id=operation_id,
            )
        except Exception as exc:
            latest = self.get(run.id)
            if latest.active_operation_id == operation_id and latest.status in {
                "collecting",
                "generating",
            }:
                return self.repository.fail(
                    run.id,
                    operation_id=operation_id,
                    error=str(exc),
                    reason="closure_generation_failed",
                )
            return latest

    def retry(self, run_id: str) -> LearningClosureRun:
        run = self.get(run_id)
        if run.status in {"preview_ready", "completed"}:
            return run
        return self.execute(run_id)

    def cancel(self, run_id: str) -> LearningClosureRun:
        return self.repository.request_cancel(run_id)

    def commit(self, run_id: str) -> LearningClosureRun:
        existing = self.get(run_id)
        if existing.status == "completed":
            return existing
        operation_id = new_id("closure_commit")
        run = self.repository.begin_commit(run_id, operation_id=operation_id)
        if run.status == "completed":
            return run
        assert run.memory_run_id is not None
        try:
            memory_run = self.memory_service.commit(run.memory_run_id)
            completed = memory_run.status == "succeeded"
            error = "" if completed else self._memory_failure_text(memory_run)
            reason = "" if completed else f"memory_{memory_run.status}"
            return self.repository.complete_commit(
                run.id,
                operation_id=operation_id,
                completed=completed,
                error=error,
                reason=reason,
            )
        except Exception as exc:
            return self.repository.complete_commit(
                run.id,
                operation_id=operation_id,
                completed=False,
                error=str(exc),
                reason="memory_commit_failed",
            )

    def get(self, run_id: str) -> LearningClosureRun:
        run = self.repository.get(run_id)
        if run is None:
            raise ValueError(f"LearningClosureRun not found: {run_id}")
        return run

    def list(self, *, limit: int = 20) -> list[LearningClosureRun]:
        return self.repository.list(limit=limit)

    def linked_memory_run(self, run: LearningClosureRun):
        return self.memory_service.get(run.memory_run_id) if run.memory_run_id else None

    def response_payload(self, run: LearningClosureRun) -> dict[str, Any]:
        payload = asdict(run)
        memory_run = self.linked_memory_run(run)
        payload["memory_run"] = asdict(memory_run) if memory_run is not None else None
        return payload

    def _collect_source(
        self, thread_id: str
    ) -> tuple[dict[str, Any], str, str]:
        thread = self.session_service.repository.get_chat_thread(thread_id)
        if thread is None:
            raise ValueError("Session not found")
        all_turns = self.session_service.repository.list_chat_turns(thread_id)
        completed_turns = [turn for turn in all_turns if turn.status == "completed"]
        if not completed_turns:
            raise LearningClosureNotEligible("Session has no completed turns")
        last_turn = completed_turns[-1]
        eligibility, task_contract = self._closure_contract(
            last_turn.route_snapshot,
            thread.learning_state,
        )
        messages: list[dict[str, str]] = []
        for turn in completed_turns:
            if turn.user_message:
                messages.append({"role": "user", "content": turn.user_message})
            if turn.assistant_message:
                messages.append(
                    {"role": "assistant", "content": turn.assistant_message}
                )
        structured_input = build_structured_closure_input(
            thread_id=thread.id,
            closure_eligibility=eligibility,
            task_contract=task_contract,
            learning_state=dict(thread.learning_state),
            all_turns=all_turns,
            completed_turns=completed_turns,
            evaluation_repository=self.evaluation_repository,
        )
        source_identity: dict[str, Any] = {
            "thread_id": thread.id,
            "source_thread_version": thread.version,
            "last_completed_turn_id": last_turn.id,
            "completed_turn_ids": [turn.id for turn in completed_turns],
            "learning_state": dict(thread.learning_state),
            "task_contract": task_contract,
            "last_turn": {
                "role": last_turn.role,
                "mode": last_turn.mode,
                "model": last_turn.model,
                "pedagogy_snapshot": dict(last_turn.pedagogy_snapshot),
            },
            "messages": messages,
        }
        snapshot = {
            **source_identity,
            "structured_input": structured_input,
        }
        return snapshot, eligibility, _canonical_hash(source_identity)

    @staticmethod
    def _closure_contract(
        route_snapshot: dict[str, Any],
        learning_state: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        raw_contract = route_snapshot.get("task_contract")
        contract = task_contract_from_snapshot(raw_contract)
        if contract is not None:
            if contract.closure_eligibility not in _ALLOWED_CLOSURES:
                raise LearningClosureNotEligible(
                    "TaskContract does not allow learning closure: "
                    f"{contract.closure_eligibility}"
                )
            return contract.closure_eligibility, contract.to_dict()

        objective = str(learning_state.get("objective") or "").strip()
        protocol = str(learning_state.get("protocol") or "").strip()
        if objective or protocol in _LEGACY_LEARNING_PROTOCOLS:
            eligibility = (
                "project_summary"
                if protocol == "project_execution"
                else "learning_summary"
            )
            return eligibility, {
                "closure_eligibility": eligibility,
                "legacy_inferred": True,
            }
        raise LearningClosureNotEligible(
            "Legacy session has no committed learning state eligible for closure"
        )

    def _ensure_active(self, run_id: str, operation_id: str) -> None:
        if self.repository.cancel_requested(run_id, operation_id=operation_id):
            raise LearningClosureCancelled("Learning closure cancelled by user")

    @staticmethod
    def _memory_updates(generated: dict[str, Any]) -> list[dict[str, Any]]:
        if isinstance(generated.get("candidates"), list):
            return structured_candidates_to_memory_updates(generated)
        return after_session_to_memory_updates(
            {key: str(value) for key, value in generated.items()}
        )

    @staticmethod
    def _memory_failure_text(memory_run) -> str:
        errors = memory_run.result.get("errors", [])
        if errors:
            return "; ".join(
                f"{item.get('target', 'unknown')}: {item.get('error', '')}"
                for item in errors
            )
        return memory_run.reason or f"MemoryRun ended as {memory_run.status}"
