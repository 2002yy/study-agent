"""Session application service backed by SQLite ChatThread/ChatTurn."""

from __future__ import annotations

from dataclasses import asdict
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from src.domain.runtime_entities import ChatThread, ChatTurn, new_id
from src.infrastructure.markdown.session_archive import (
    LegacySessionImporter,
    SessionMarkdownExporter,
)
from src.repositories.runtime_repository import RuntimeRepository
from src.repositories.session_navigation_repository import SessionNavigationRepository
from src.repositories.thread_summary_repository import ThreadSummaryRepository
from src.task_contract import task_contract_from_snapshot

_NAVIGATION_SCHEMA_VERSION = "session-navigation-v1"
_TITLE_LIMIT = 48
_PREVIEW_LIMIT = 180


class SessionService:
    def __init__(
        self,
        repository: RuntimeRepository,
        *,
        current_dir: Path,
        archive_dir: Path,
        summary_repository: ThreadSummaryRepository | None = None,
        navigation_repository: SessionNavigationRepository | None = None,
    ):
        self.repository = repository
        self.summary_repository = summary_repository or ThreadSummaryRepository(
            repository.database
        )
        self.navigation_repository = (
            navigation_repository
            or SessionNavigationRepository(repository.database)
        )
        self.importer = LegacySessionImporter(current_dir, archive_dir)
        self.exporter = SessionMarkdownExporter(current_dir, archive_dir)
        self._legacy_imported = False

    def list_sessions(self, *, limit: int = 20) -> list[dict[str, Any]]:
        self._import_legacy_once()
        return [
            self._thread_row(thread)
            for thread in self.repository.list_chat_threads(limit=limit)
        ]

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        self._import_legacy_once()
        thread = self.repository.get_chat_thread(session_id)
        if thread is None:
            self.importer.import_session(self.repository, session_id)
            thread = self.repository.get_chat_thread(session_id)
        if thread is None:
            return None
        turns = self.repository.list_chat_turns(session_id)
        messages: list[dict[str, str]] = []
        for turn in (turn for turn in turns if turn.status != "superseded"):
            messages.append(
                {
                    "role": "user",
                    "content": turn.user_message,
                    "avatarRole": "user",
                    "turnId": turn.id,
                    "turnStatus": turn.status,
                    "parentTurnId": turn.parent_turn_id,
                }
            )
            if turn.assistant_message:
                messages.append(
                    {
                        "role": "assistant",
                        "content": turn.assistant_message,
                        "avatarRole": turn.role or "auto",
                        "turnId": turn.id,
                        "turnStatus": turn.status,
                        "parentTurnId": turn.parent_turn_id,
                    }
                )
        latest = turns[-1] if turns else None
        latest_completed = next(
            (turn for turn in reversed(turns) if turn.status == "completed"),
            None,
        )
        path = self._thread_path(thread)
        raw = path.read_text(encoding="utf-8")[:4000] if path and path.is_file() else ""
        navigation = self._navigation_projection(thread, turns)
        return {
            "session_id": thread.id,
            "kind": "archived" if thread.status == "archived" else "active",
            "path": str(path) if path else "",
            "messages": messages,
            "settings": thread.settings_snapshot,
            "route": latest.route_snapshot if latest else {},
            "rag": latest.rag_snapshot if latest else {},
            "learning_state": thread.learning_state,
            "summary": navigation["summary"],
            "navigation": navigation,
            "pedagogy": latest_completed.pedagogy_snapshot if latest_completed else {},
            "latest_attempted_pedagogy": latest.pedagogy_snapshot if latest else {},
            "conversation_instruction": latest.conversation_instruction if latest else "",
            "turns": [
                {
                    "turn_id": turn.id,
                    "status": turn.status,
                    "parent_turn_id": turn.parent_turn_id,
                    "operation_id": turn.operation_id,
                    "user_message": turn.user_message,
                    "assistant_message": turn.assistant_message,
                    "role": turn.role,
                    "mode": turn.mode,
                    "model": turn.model,
                    "route_snapshot": turn.route_snapshot,
                    "rag_snapshot": turn.rag_snapshot,
                    "pedagogy_snapshot": turn.pedagogy_snapshot,
                }
                for turn in turns
            ],
            "raw": raw,
        }

    def create_session(self, settings: dict[str, Any]) -> ChatThread:
        return self.repository.create_chat_thread(ChatThread(settings_snapshot=settings))

    def rename_session(self, session_id: str, title: str) -> dict[str, Any]:
        self._import_legacy_once()
        self.navigation_repository.set_manual_title(session_id, title)
        thread = self.repository.get_chat_thread(session_id)
        if thread is None:
            raise ValueError(f"Chat thread not found: {session_id}")
        return self._thread_row(thread)

    def archive_session(self, session_id: str) -> ChatThread | None:
        self._import_legacy_once()
        thread = self.repository.get_chat_thread(session_id)
        if thread is None:
            return None
        if thread.status == "archived":
            return thread
        archive_operation_id = new_id("archive")
        locked = self.repository.begin_archive_chat_thread(
            session_id,
            operation_id=archive_operation_id,
        )
        if locked.status == "archived":
            return locked
        export_path: Path | None = None
        try:
            turns = self.repository.list_chat_turns(session_id)
            if not turns:
                self.repository.cancel_archive_chat_thread(
                    session_id,
                    operation_id=archive_operation_id,
                )
                return None
            if any(turn.status in {"pending", "streaming"} for turn in turns):
                raise ValueError("Chat thread has an active turn and cannot be archived")
            export_path = self.exporter.archive_path(locked)
            self.repository.reserve_archive_path(
                session_id,
                operation_id=archive_operation_id,
                export_path=str(export_path),
            )
            export_path = self.exporter.export_archive(locked, turns, path=export_path)
            archived = self.repository.finish_archive_chat_thread(
                session_id,
                operation_id=archive_operation_id,
                export_path=str(export_path),
            )
        except Exception:
            if export_path is not None:
                export_path.unlink(missing_ok=True)
            current = self.repository.get_chat_thread(session_id)
            if (
                current is not None
                and current.status == "archiving"
                and current.archive_operation_id == archive_operation_id
            ):
                self.repository.cancel_archive_chat_thread(
                    session_id,
                    operation_id=archive_operation_id,
                )
            raise
        try:
            (self.exporter.current_dir / f"{session_id}.md").unlink(missing_ok=True)
        except OSError as exc:
            logging.getLogger(__name__).warning(
                "Archived session %s but could not remove current mirror: %s",
                session_id,
                exc,
            )
        return archived

    def flush_session(self, session_id: str) -> Path | None:
        thread = self.repository.get_chat_thread(session_id)
        if thread is None or thread.status != "active":
            return None
        turns = self.repository.list_chat_turns(session_id)
        if not turns:
            return None
        return self.exporter.export_current(thread, turns)

    def summary_payload(self, session_id: str) -> dict[str, Any]:
        state = self.summary_repository.get_effective(session_id)
        payload = asdict(state)
        payload["can_summarize"] = state.can_summarize
        return payload

    def assert_summary_source_current(
        self,
        session_id: str,
        *,
        last_completed_turn_id: str,
    ) -> None:
        self.summary_repository.assert_source_current(
            session_id,
            last_completed_turn_id=last_completed_turn_id,
        )

    def mark_summary_completed(
        self,
        session_id: str,
        *,
        source_thread_version: int,
        last_completed_turn_id: str,
        closure_run_id: str,
    ) -> dict[str, Any]:
        state = self.summary_repository.mark_summarized(
            session_id,
            source_thread_version=source_thread_version,
            last_completed_turn_id=last_completed_turn_id,
            closure_run_id=closure_run_id,
        )
        payload = asdict(state)
        payload["can_summarize"] = state.can_summarize
        return payload

    def _import_legacy_once(self) -> None:
        if self._legacy_imported:
            return
        self.importer.import_all(self.repository)
        self._legacy_imported = True

    def _thread_row(self, thread: ChatThread) -> dict[str, Any]:
        path = self._thread_path(thread)
        stat = path.stat() if path and path.is_file() else None
        navigation = self._navigation_projection(
            thread,
            self.repository.list_chat_turns(thread.id),
        )
        return {
            "session_id": thread.id,
            "kind": "archived" if thread.status == "archived" else "current",
            "name": path.name if path else f"{thread.id}.md",
            "path": str(path) if path else "",
            "size_bytes": stat.st_size if stat else 0,
            "mtime_ns": _iso_to_ns(thread.updated_at),
            "status": thread.status,
            "version": thread.version,
            **navigation,
        }

    def _navigation_projection(
        self,
        thread: ChatThread,
        turns: list[ChatTurn],
    ) -> dict[str, Any]:
        completed_turns = [turn for turn in turns if turn.status == "completed"]
        latest_completed = completed_turns[-1] if completed_turns else None
        first_completed = completed_turns[0] if completed_turns else None
        contract = None
        if latest_completed is not None:
            contract = task_contract_from_snapshot(
                latest_completed.route_snapshot.get("task_contract")
            )
        task_intent = (
            contract.task_intent
            if contract is not None
            else _legacy_task_intent(thread.learning_state)
        )
        objective = _normalized_text(thread.learning_state.get("objective"))
        phase = _normalized_text(thread.learning_state.get("phase"))
        if not phase and latest_completed is not None:
            phase = _normalized_text(latest_completed.pedagogy_snapshot.get("phase"))
        unresolved_gap = _normalized_text(thread.learning_state.get("unresolved_gap"))
        auto_title = _auto_title(
            objective=objective,
            task_intent=task_intent,
            first_completed=first_completed,
            thread_id=thread.id,
        )
        title_meta = self.navigation_repository.get_title(thread.id)
        manual_title = title_meta.manual_title
        title = manual_title or auto_title
        preview = ""
        research_summary = ""
        if latest_completed is not None:
            preview = _truncate(
                latest_completed.assistant_message
                or latest_completed.user_message,
                _PREVIEW_LIMIT,
            )
            if task_intent == "research":
                research_summary = _truncate(
                    latest_completed.assistant_message,
                    _PREVIEW_LIMIT,
                )
        return {
            "navigation_schema_version": _NAVIGATION_SCHEMA_VERSION,
            "title": title,
            "title_source": "manual" if manual_title else "auto",
            "manual_title": manual_title,
            "auto_title": auto_title,
            "objective": objective,
            "research_summary": research_summary,
            "preview": preview,
            "task_intent": task_intent,
            "phase": phase,
            "unresolved_gap": unresolved_gap,
            "last_completed_turn_id": latest_completed.id if latest_completed else None,
            "has_completed_turns": bool(completed_turns),
            "summary": self.summary_payload(thread.id),
            "updated_at": thread.updated_at,
        }

    def _thread_path(self, thread: ChatThread) -> Path | None:
        if thread.export_path:
            return Path(thread.export_path)
        current = self.exporter.current_dir / f"{thread.id}.md"
        return current if current.is_file() else None


def _auto_title(
    *,
    objective: str,
    task_intent: str,
    first_completed: ChatTurn | None,
    thread_id: str,
) -> str:
    if objective:
        return _truncate(objective, _TITLE_LIMIT)
    if first_completed is not None and first_completed.user_message.strip():
        return _truncate(first_completed.user_message, _TITLE_LIMIT)
    labels = {
        "research": "研究会话",
        "project_execution": "项目推进",
        "learn": "学习会话",
        "explain_back": "理解检验",
        "conversation": "对话",
        "organize": "整理会话",
        "quick_answer": "快速问答",
    }
    return f"{labels.get(task_intent, '新会话')} · {thread_id[-6:]}"


def _legacy_task_intent(learning_state: dict[str, Any]) -> str:
    protocol = str(learning_state.get("protocol") or "")
    if protocol == "project_execution":
        return "project_execution"
    if protocol in {"socratic_rediscovery", "feynman_diagnosis"}:
        return "learn"
    return "quick_answer"


def _normalized_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return " ".join(value.strip().split())
    if isinstance(value, (list, tuple, set)):
        return "；".join(
            item
            for raw in value
            if (item := _normalized_text(raw))
        )
    if isinstance(value, dict):
        return "；".join(
            f"{key}: {text}"
            for key, raw in value.items()
            if (text := _normalized_text(raw))
        )
    return str(value)


def _truncate(text: str, limit: int) -> str:
    normalized = " ".join(str(text or "").strip().split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(1, limit - 1)].rstrip() + "…"


def _iso_to_ns(value: str) -> int:
    try:
        return int(datetime.fromisoformat(value).timestamp() * 1_000_000_000)
    except (TypeError, ValueError):
        return 0
