"""Legacy GroupThread import and Markdown archive export."""

from __future__ import annotations

import re
from pathlib import Path

from src.domain.runtime_entities import GroupMessage, GroupThread
from src.repositories.group_repository import GroupRepository
from src.safe_writer import safe_write_text
from src.wechat_format import _message_blocks

LEGACY_GROUP_THREAD_ID = "group_legacy_default"


class LegacyGroupImporter:
    def __init__(self, group_file: Path, unread_file: Path, state_file: Path):
        self.group_file = group_file
        self.unread_file = unread_file
        self.state_file = state_file

    def import_once(self, repository: GroupRepository) -> GroupThread | None:
        existing = repository.list_threads(limit=1)
        if existing:
            return existing[0]
        group_content = self._read(self.group_file)
        unread_content = self._read(self.unread_file)
        blocks = _message_blocks(group_content or unread_content)
        if not blocks:
            return None
        unread_count = len(_message_blocks(unread_content))
        thread = repository.create_thread(
            GroupThread(
                id=LEGACY_GROUP_THREAD_ID,
                title="Legacy WeChat Group",
                settings_snapshot=self._state_snapshot(),
                unread_count=unread_count,
            )
        )
        for speaker, content in blocks:
            repository.add_message(
                GroupMessage(
                    thread_id=thread.id,
                    speaker=speaker,
                    content=content,
                    status="committed",
                    message_type="legacy",
                )
            )
        return repository.get_thread(thread.id)

    def _state_snapshot(self) -> dict[str, object]:
        raw = self._read(self.state_file)
        if not raw:
            return {}
        snapshot: dict[str, object] = {}
        for key in (
            "user_has_joined_group",
            "first_join_reaction_done",
            "mode",
            "memory_capture_enabled",
            "memory_capture_mode",
        ):
            match = re.search(rf"^-\s*{re.escape(key)}:\s*(.+?)\s*$", raw, re.MULTILINE)
            if not match:
                continue
            value = match.group(1).strip()
            if value.lower() in {"true", "false"}:
                snapshot[key] = value.lower() == "true"
            else:
                snapshot[key] = value
        return snapshot

    @staticmethod
    def _read(path: Path) -> str:
        return path.read_text(encoding="utf-8").strip() if path.is_file() else ""


class GroupMarkdownExporter:
    def __init__(self, archive_dir: Path):
        self.archive_dir = archive_dir

    def archive_path(self, thread: GroupThread) -> Path:
        return self.archive_dir / f"{thread.id}.md"

    def export_archive(
        self,
        thread: GroupThread,
        messages: list[GroupMessage],
        *,
        path: Path | None = None,
    ) -> Path:
        destination = path or self.archive_path(thread)
        lines = [
            "# Group Thread Archive",
            "",
            f"- group_thread_id: {thread.id}",
            f"- title: {thread.title}",
            "",
        ]
        for message in messages:
            lines.extend(
                [
                    f"【{message.speaker}】",
                    message.content,
                    "",
                    f"<!-- group_message_id: {message.id}; status: {message.status} -->",
                    "",
                ]
            )
        safe_write_text(destination, "\n".join(lines).rstrip() + "\n")
        return destination
