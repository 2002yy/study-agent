"""Legacy session import and Markdown export for SQLite chat threads."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.domain.runtime_entities import ChatThread, ChatTurn
from src.repositories.runtime_repository import RuntimeRepository
from src.safe_writer import safe_write_text

SESSION_TURN_MARKER = "```json session_turn"


class SessionMarkdownExporter:
    def __init__(self, current_dir: Path, archive_dir: Path):
        self.current_dir = current_dir
        self.archive_dir = archive_dir

    def export_current(
        self,
        thread: ChatThread,
        turns: list[ChatTurn],
    ) -> Path:
        path = self.current_dir / f"{thread.id}.md"
        safe_write_text(path, _render_thread(thread, turns, archived=False))
        return path

    def export_archive(
        self,
        thread: ChatThread,
        turns: list[ChatTurn],
    ) -> Path:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        path = self.archive_dir / f"{timestamp}_session_{thread.id}_archived.md"
        safe_write_text(path, _render_thread(thread, turns, archived=True))
        current = self.current_dir / f"{thread.id}.md"
        current.unlink(missing_ok=True)
        return path


class LegacySessionImporter:
    def __init__(self, current_dir: Path, archive_dir: Path):
        self.current_dir = current_dir
        self.archive_dir = archive_dir

    def import_all(self, repository: RuntimeRepository) -> int:
        imported = 0
        candidates: list[tuple[str, Path]] = []
        if self.archive_dir.is_dir():
            candidates.extend(("archived", path) for path in self.archive_dir.glob("*.md"))
        if self.current_dir.is_dir():
            candidates.extend(("current", path) for path in self.current_dir.glob("*.md"))
        for kind, path in sorted(
            candidates,
            key=lambda item: (
                0 if item[0] == "archived" else 1,
                item[1].stat().st_mtime_ns,
            ),
        ):
            imported += int(self.import_file(repository, path, kind=kind))
        return imported

    def import_session(self, repository: RuntimeRepository, session_id: str) -> bool:
        if repository.get_chat_thread(session_id) is not None:
            return False
        if self.archive_dir.is_dir():
            for path in sorted(
                self.archive_dir.glob("*.md"),
                key=lambda item: item.stat().st_mtime_ns,
                reverse=True,
            ):
                raw = path.read_text(encoding="utf-8")
                if _session_id(path, raw, "archived") == session_id:
                    return self.import_file(repository, path, kind="archived")
        current = self.current_dir / f"{session_id}.md"
        if current.is_file():
            return self.import_file(repository, current, kind="current")
        return False

    def import_file(
        self,
        repository: RuntimeRepository,
        path: Path,
        *,
        kind: str,
    ) -> bool:
        raw = path.read_text(encoding="utf-8")
        session_id = _session_id(path, raw, kind)
        if not session_id or repository.get_chat_thread(session_id) is not None:
            return False
        snapshots = _parse_snapshots(raw)
        if not snapshots:
            snapshots = _fallback_snapshots(raw, kind)
        file_time = datetime.fromtimestamp(
            path.stat().st_mtime,
            timezone.utc,
        ).isoformat()
        settings = snapshots[-1].get("settings", {}) if snapshots else {}
        repository.create_chat_thread(
            ChatThread(
                id=session_id,
                status="active",
                settings_snapshot=settings if isinstance(settings, dict) else {},
                created_at=file_time,
                updated_at=file_time,
            )
        )
        for index, snapshot in enumerate(snapshots):
            repository.add_chat_turn(
                _turn_from_snapshot(session_id, snapshot, path, index, file_time)
            )
        if kind == "archived":
            repository.archive_chat_thread(session_id, export_path=str(path))
        return True


def _render_thread(
    thread: ChatThread,
    turns: list[ChatTurn],
    *,
    archived: bool,
) -> str:
    lines = [f"# Session {thread.id}", "", f"- session_id: {thread.id}"]
    lines.append(f"- status: {'archived' if archived else thread.status}")
    lines.append("")
    for turn in turns:
        lines.extend(
            [
                f"## {turn.created_at}",
                f"- turn_id: {turn.id}",
                f"- status: {turn.status}",
                f"- role: {turn.role}",
                f"- mode: {turn.mode}",
                f"- model: {turn.model}",
                "",
                f"**User**\n{turn.user_message}\n",
                f"**Agent**\n{turn.assistant_message}\n",
                SESSION_TURN_MARKER,
                json.dumps(_turn_snapshot(thread, turn), ensure_ascii=False),
                "```",
                "---",
                "",
            ]
        )
    return "\n".join(lines)


def _turn_snapshot(thread: ChatThread, turn: ChatTurn) -> dict[str, Any]:
    return {
        "turn_id": turn.id,
        "status": turn.status,
        "parent_turn_id": turn.parent_turn_id,
        "operation_id": turn.operation_id,
        "time": turn.created_at,
        "messages": [
            {"role": "user", "content": turn.user_message, "avatarRole": "user"},
            {
                "role": "assistant",
                "content": turn.assistant_message,
                "avatarRole": turn.role or "auto",
            },
        ],
        "settings": thread.settings_snapshot,
        "route": turn.route_snapshot,
        "rag": turn.rag_snapshot,
        "conversation_instruction": turn.conversation_instruction,
    }


def _parse_snapshots(raw: str) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    for block in raw.split(SESSION_TURN_MARKER)[1:]:
        json_part = block.split("```", 1)[0].strip()
        try:
            parsed = json.loads(json_part)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(parsed, dict):
            snapshots.append(parsed)
    return snapshots


def _fallback_snapshots(raw: str, kind: str) -> list[dict[str, Any]]:
    if kind == "current":
        users = [line.removeprefix("User: ") for line in raw.splitlines() if line.startswith("User: ")]
        agents = [line.removeprefix("Agent: ") for line in raw.splitlines() if line.startswith("Agent: ")]
        return [
            {"messages": [{"role": "user", "content": user}, {"role": "assistant", "content": agent}]}
            for user, agent in zip(users, agents)
        ]
    snapshots: list[dict[str, Any]] = []
    for block in raw.split("---"):
        if "**User**" not in block or "**Agent**" not in block:
            continue
        user = block.split("**User**", 1)[1].split("**Agent**", 1)[0].strip()
        agent = block.split("**Agent**", 1)[1].split(SESSION_TURN_MARKER, 1)[0].strip()
        snapshots.append(
            {"messages": [{"role": "user", "content": user}, {"role": "assistant", "content": agent}]}
        )
    return snapshots


def _turn_from_snapshot(
    thread_id: str,
    snapshot: dict[str, Any],
    path: Path,
    index: int,
    fallback_time: str,
) -> ChatTurn:
    messages = snapshot.get("messages") if isinstance(snapshot.get("messages"), list) else []
    user = next((item for item in messages if isinstance(item, dict) and item.get("role") == "user"), {})
    assistant = next(
        (item for item in messages if isinstance(item, dict) and item.get("role") == "assistant"),
        {},
    )
    route = snapshot.get("route") if isinstance(snapshot.get("route"), dict) else {}
    rag = snapshot.get("rag") if isinstance(snapshot.get("rag"), dict) else {}
    turn_id = str(snapshot.get("turn_id") or _legacy_turn_id(path, index))
    return ChatTurn(
        id=turn_id,
        thread_id=thread_id,
        user_message=str(user.get("content", "")),
        assistant_message=str(assistant.get("content", "")),
        status=str(snapshot.get("status") or "completed"),
        role=str(assistant.get("avatarRole") or route.get("role") or "auto"),
        mode=str(route.get("mode") or "auto"),
        model=str(route.get("model_profile") or "auto"),
        route_snapshot=route,
        rag_snapshot=rag,
        parent_turn_id=snapshot.get("parent_turn_id"),
        operation_id=snapshot.get("operation_id"),
        conversation_instruction=str(snapshot.get("conversation_instruction") or ""),
        created_at=str(snapshot.get("time") or fallback_time),
        updated_at=str(snapshot.get("time") or fallback_time),
    )


def _session_id(path: Path, raw: str, kind: str) -> str:
    metadata = re.search(r"(?m)^- session_id:\s*(\S+)\s*$", raw)
    if metadata:
        return metadata.group(1)
    if kind == "current":
        return path.stem
    match = re.search(r"_session_([^_]+)_", path.name)
    return match.group(1) if match else path.stem


def _legacy_turn_id(path: Path, index: int) -> str:
    digest = hashlib.sha256(f"{path.resolve()}:{index}".encode("utf-8")).hexdigest()
    return f"turn_legacy_{digest[:24]}"
