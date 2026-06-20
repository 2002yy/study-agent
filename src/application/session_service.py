"""Session application service backed by SQLite ChatThread/ChatTurn."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from src.domain.runtime_entities import ChatThread, new_id
from src.infrastructure.markdown.session_archive import (
    LegacySessionImporter,
    SessionMarkdownExporter,
)
from src.repositories.runtime_repository import RuntimeRepository


class SessionService:
    def __init__(
        self,
        repository: RuntimeRepository,
        *,
        current_dir: Path,
        archive_dir: Path,
    ):
        self.repository = repository
        self.importer = LegacySessionImporter(current_dir, archive_dir)
        self.exporter = SessionMarkdownExporter(current_dir, archive_dir)
        self._legacy_imported = False

    def list_sessions(self, *, limit: int = 20) -> list[dict[str, Any]]:
        self._import_legacy_once()
        return [self._thread_row(thread) for thread in self.repository.list_chat_threads(limit=limit)]

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
        for turn in turns:
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
        path = self._thread_path(thread)
        raw = path.read_text(encoding="utf-8")[:4000] if path and path.is_file() else ""
        return {
            "session_id": thread.id,
            "kind": "archived" if thread.status == "archived" else "active",
            "path": str(path) if path else "",
            "messages": messages,
            "settings": thread.settings_snapshot,
            "route": latest.route_snapshot if latest else {},
            "rag": latest.rag_snapshot if latest else {},
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
                }
                for turn in turns
            ],
            "raw": raw,
        }

    def create_session(self, settings: dict[str, Any]) -> ChatThread:
        return self.repository.create_chat_thread(ChatThread(settings_snapshot=settings))

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

    def _import_legacy_once(self) -> None:
        if self._legacy_imported:
            return
        self.importer.import_all(self.repository)
        self._legacy_imported = True

    def _thread_row(self, thread: ChatThread) -> dict[str, Any]:
        path = self._thread_path(thread)
        stat = path.stat() if path and path.is_file() else None
        return {
            "session_id": thread.id,
            "kind": "archived" if thread.status == "archived" else "current",
            "name": path.name if path else f"{thread.id}.md",
            "path": str(path) if path else "",
            "size_bytes": stat.st_size if stat else 0,
            "mtime_ns": stat.st_mtime_ns if stat else _iso_to_ns(thread.updated_at),
            "status": thread.status,
            "version": thread.version,
        }

    def _thread_path(self, thread: ChatThread) -> Path | None:
        if thread.export_path:
            return Path(thread.export_path)
        current = self.exporter.current_dir / f"{thread.id}.md"
        return current if current.is_file() else None


def _iso_to_ns(value: str) -> int:
    try:
        return int(datetime.fromisoformat(value).timestamp() * 1_000_000_000)
    except (TypeError, ValueError):
        return 0
