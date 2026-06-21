"""GroupThread Batch 1 application service backed by SQLite."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.domain.runtime_entities import GroupThread, new_id
from src.infrastructure.markdown.group_archive import (
    GroupMarkdownExporter,
    LegacyGroupImporter,
)
from src.repositories.group_repository import GroupRepository


class GroupChatService:
    def __init__(
        self,
        repository: GroupRepository,
        *,
        group_file: Path,
        unread_file: Path,
        state_file: Path,
        archive_dir: Path,
    ):
        self.repository = repository
        self.importer = LegacyGroupImporter(group_file, unread_file, state_file)
        self.exporter = GroupMarkdownExporter(archive_dir)
        self._legacy_imported = False

    def list_threads(self, *, limit: int = 20) -> list[GroupThread]:
        self._import_legacy_once()
        return self.repository.list_threads(limit=limit)

    def get_thread(self, thread_id: str) -> dict[str, Any] | None:
        self._import_legacy_once()
        thread = self.repository.get_thread(thread_id)
        if thread is None:
            return None
        return {
            "thread": thread,
            "messages": self.repository.list_messages(thread_id),
        }

    def create_thread(
        self,
        *,
        title: str = "",
        settings_snapshot: dict[str, Any] | None = None,
    ) -> GroupThread:
        self._import_legacy_once()
        return self.repository.create_thread(
            GroupThread(
                title=title,
                settings_snapshot=settings_snapshot or {},
            )
        )

    def archive_thread(self, thread_id: str) -> GroupThread:
        self._import_legacy_once()
        current = self.repository.get_thread(thread_id)
        if current is None:
            raise ValueError(f"Group thread not found: {thread_id}")
        if current.status == "archived":
            return current
        operation_id = new_id("group_archive")
        locked = self.repository.begin_archive(thread_id, operation_id)
        path = self.exporter.archive_path(locked)
        try:
            messages = self.repository.list_messages(thread_id)
            exported = self.exporter.export_archive(locked, messages, path=path)
            return self.repository.finish_archive(thread_id, operation_id, exported)
        except Exception:
            path.unlink(missing_ok=True)
            current = self.repository.get_thread(thread_id)
            if (
                current is not None
                and current.status == "archiving"
                and current.archive_operation_id == operation_id
            ):
                self.repository.cancel_archive(thread_id, operation_id)
            raise

    def _import_legacy_once(self) -> None:
        if self._legacy_imported:
            return
        self.importer.import_once(self.repository)
        self._legacy_imported = True
