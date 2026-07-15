"""Server-owned MemoryRun preview and commit workflow."""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from typing import Any

from src.application.helpers import (
    memory_target_path,
    memory_update_preview_text,
)
from src.domain.runtime_entities import MemoryRun, new_id, utc_now
from src.mode_manager import is_memory_write_allowed, load_runtime_modes
from src.repositories.memory_repository import MemoryRepository

_ALLOWED_CONFIDENCE = {"low", "medium", "high"}


def normalize_updates(updates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    focus_replaces = 0
    for raw in updates:
        target = str(raw.get("target", "")).strip()
        content = str(raw.get("content", "")).strip()
        if not content:
            raise ValueError("Memory update content is required")
        memory_target_path(target)
        append = bool(raw.get("append", True))
        source_refs = _string_list(raw.get("source_refs"))
        evaluation_refs = _string_list(raw.get("evaluation_refs"))
        learner_pending = bool(raw.get("learner_pending", False))
        if target == "learner_profile" and source_refs:
            learner_pending = True
        if target != "current_focus" and not append:
            raise ValueError(
                "append=false is only supported for target current_focus"
            )
        if target == "current_focus" and not append:
            focus_replaces += 1
        item: dict[str, Any] = {
            "target": target,
            "content": content,
            "append": append,
            "learner_pending": learner_pending,
        }
        confidence = str(raw.get("confidence", "")).strip().lower()
        if confidence:
            item["confidence"] = (
                confidence if confidence in _ALLOWED_CONFIDENCE else "low"
            )
        if source_refs:
            item["source_refs"] = source_refs
        if evaluation_refs:
            item["evaluation_refs"] = evaluation_refs
        provenance_schema = str(
            raw.get("provenance_schema_version", "")
        ).strip()
        if provenance_schema:
            item["provenance_schema_version"] = provenance_schema
        normalized.append(item)
    if not normalized:
        raise ValueError("At least one memory update is required")
    if focus_replaces > 1:
        raise ValueError("最多允许一次 current_focus replace 操作")
    return normalized


def updates_hash(updates: list[dict[str, Any]]) -> str:
    payload = json.dumps(
        updates, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class MemoryService:
    def __init__(self, repository: MemoryRepository):
        self.repository = repository

    def create(
        self,
        updates: list[dict[str, Any]],
        *,
        runtime_modes=None,
        run_id: str | None = None,
    ) -> MemoryRun:
        frozen = normalize_updates(updates)
        frozen_hash = updates_hash(frozen)
        if run_id:
            existing = self.repository.get(run_id)
            if existing is not None:
                if existing.updates_hash != frozen_hash:
                    raise ValueError(f"MemoryRun idempotency conflict: {run_id}")
                return existing
        modes = runtime_modes or load_runtime_modes()
        writable = is_memory_write_allowed(modes)
        preview_items = []
        for update in frozen:
            action = self._action(update)
            preview_item: dict[str, Any] = {
                "target": update["target"],
                "path": str(memory_target_path(update["target"])),
                "action": action,
                "allowed": writable,
                "preview": memory_update_preview_text(
                    SimpleNamespace(**update), action
                ),
            }
            for key in (
                "confidence",
                "source_refs",
                "evaluation_refs",
                "provenance_schema_version",
            ):
                if key in update:
                    preview_item[key] = update[key]
            preview_items.append(preview_item)
        now = utc_now()
        return self.repository.create(
            MemoryRun(
                id=run_id or new_id("memory"),
                updates=frozen,
                updates_hash=frozen_hash,
                preview={
                    "writable": writable,
                    "memory_mode": modes.memory_mode,
                    "safe_mode": modes.safe_mode,
                    "updates": preview_items,
                },
                previewed_at=now,
                created_at=now,
                updated_at=now,
            )
        )

    def commit(self, run_id: str, *, runtime_modes=None) -> MemoryRun:
        existing = self.repository.get(run_id)
        if existing is None:
            raise ValueError(f"MemoryRun not found: {run_id}")
        if existing.status in {"succeeded", "partial", "failed", "blocked"}:
            return existing
        operation_id = new_id("memory_commit")
        run = self.repository.acquire_commit(run_id, operation_id)
        if updates_hash(normalize_updates(run.updates)) != run.updates_hash:
            return self.repository.complete_commit(
                run.id,
                operation_id,
                status="blocked",
                result={},
                reason="updates_hash_mismatch",
            )
        modes = runtime_modes or load_runtime_modes()
        if not is_memory_write_allowed(modes):
            return self.repository.complete_commit(
                run.id,
                operation_id,
                status="blocked",
                result={},
                reason=modes.profile.memory_write_reason,
            )

        import src.memory_writer as writer

        results: list[dict[str, str]] = []
        errors: list[dict[str, str]] = []
        for update in run.updates:
            action = self._action(update)
            try:
                if action == "replace":
                    path = writer.write_current_focus(update["content"])
                else:
                    path = writer.append_memory(
                        update["target"],
                        update["content"],
                        learner_pending=update["learner_pending"],
                    )
                results.append(
                    {
                        "target": update["target"],
                        "action": action,
                        "path": str(path),
                    }
                )
            except Exception as exc:
                errors.append(
                    {
                        "target": update["target"],
                        "action": action,
                        "error": str(exc),
                    }
                )
        status = "succeeded" if not errors else "partial" if results else "failed"
        return self.repository.complete_commit(
            run.id,
            operation_id,
            status=status,
            result={"results": results, "errors": errors},
            reason="memory_write_failed" if errors and not results else "",
        )

    def get(self, run_id: str) -> MemoryRun:
        run = self.repository.get(run_id)
        if run is None:
            raise ValueError(f"MemoryRun not found: {run_id}")
        return run

    def list(self, *, limit: int = 20) -> list[MemoryRun]:
        return self.repository.list(limit=limit)

    @staticmethod
    def _action(update: dict[str, Any]) -> str:
        return (
            "replace"
            if update["target"] == "current_focus" and not update["append"]
            else "append"
        )


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return sorted({str(item).strip() for item in value if str(item).strip()})
