"""GroupThread application service backed by SQLite runtime state."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator

from src.domain.runtime_entities import GroupMessage, GroupThread, new_id
from src.infrastructure.markdown.group_archive import (
    GroupMarkdownExporter,
    LegacyGroupImporter,
)
from src.repositories.group_repository import GroupRepository
from src.tools.local_knowledge import retrieve_local_knowledge
from src.wechat_format import _message_blocks
from src.wechat_generator import (
    generate_interactive_wechat_reply,
    generate_interactive_wechat_reply_stream,
    generate_wechat_opening,
    normalize_interactive_wechat_reply,
)


@dataclass(frozen=True)
class GroupDependencies:
    retrieve_local_knowledge: Callable[..., Any] = retrieve_local_knowledge
    generate_opening: Callable[..., str] = generate_wechat_opening
    generate_reply: Callable[..., str] = generate_interactive_wechat_reply
    generate_reply_stream: Callable[..., Any] = generate_interactive_wechat_reply_stream
    normalize_reply: Callable[[str], str] = normalize_interactive_wechat_reply


@dataclass(frozen=True)
class PreparedGroupMessage:
    thread: GroupThread
    message: GroupMessage
    operation_id: str
    user_text: str
    model_profile: str
    relationship_mode: str
    performance_mode: str
    history_text: str
    rag: dict[str, Any] = field(default_factory=dict)
    rag_context: str = ""


class GroupChatService:
    def __init__(
        self,
        repository: GroupRepository,
        *,
        group_file: Path,
        unread_file: Path,
        state_file: Path,
        archive_dir: Path,
        dependencies: GroupDependencies | None = None,
    ):
        self.repository = repository
        self.importer = LegacyGroupImporter(group_file, unread_file, state_file)
        self.exporter = GroupMarkdownExporter(archive_dir)
        self.dependencies = dependencies or GroupDependencies()
        self._legacy_imported = False

    def list_threads(self, *, limit: int = 20) -> list[GroupThread]:
        self._import_legacy_once()
        return self.repository.list_threads(limit=limit)

    def get_thread(self, thread_id: str) -> dict[str, Any] | None:
        self._import_legacy_once()
        thread = self.repository.get_thread(thread_id)
        if thread is None:
            return None
        return {"thread": thread, "messages": self.repository.list_messages(thread_id)}

    def get_state(self, thread_id: str | None = None) -> dict[str, Any]:
        thread = self._resolve_thread(thread_id, create=True)
        messages = self.repository.list_messages(thread.id)
        visible = [message for message in messages if message.status == "committed"]
        content = _format_messages(visible)
        unread_candidates = [
            message
            for message in visible
            if message.speaker != "用户"
        ]
        unread_messages = (
            unread_candidates[-thread.unread_count :] if thread.unread_count else []
        )
        return {
            "group_thread_id": thread.id,
            "state": {
                **thread.settings_snapshot,
                "mode": thread.settings_snapshot.get("mode", "interactive_group"),
            },
            "content": content,
            "unread": _format_messages(unread_messages),
            "has_unread": thread.unread_count > 0,
            "started": bool(visible),
            "message_count": sum(_display_count(message) for message in visible),
            "unread_count": thread.unread_count,
            "summary": content[-500:] if content else "暂无群聊记录",
        }

    def create_thread(
        self,
        *,
        title: str = "",
        settings_snapshot: dict[str, Any] | None = None,
    ) -> GroupThread:
        self._import_legacy_once()
        return self.repository.create_thread(
            GroupThread(title=title, settings_snapshot=settings_snapshot or {})
        )

    def create_opening(
        self,
        *,
        thread_id: str | None,
        role_hint: str,
        relationship_mode: str,
        performance_mode: str,
        selected_model: str,
    ) -> GroupThread:
        thread = self._resolve_thread(thread_id, create=True)
        if any(
            message.status != "failed"
            for message in self.repository.list_messages(thread.id)
        ):
            raise ValueError("Group thread already has messages")
        operation_id = new_id("group_op")
        self.repository.acquire_operation(
            thread.id,
            operation_id,
            settings_snapshot={
                **thread.settings_snapshot,
                "relationship_mode": relationship_mode,
                "performance_mode": performance_mode,
                "selected_model": selected_model,
                "mode": "interactive_group",
            },
        )
        pending = GroupMessage(
            thread_id=thread.id,
            speaker="群聊",
            status="streaming",
            message_type="opening",
            operation_id=operation_id,
        )
        self.repository.start_exchange(None, pending)
        try:
            reply = self.dependencies.generate_opening(
                role_hint=role_hint,
                relationship_mode=relationship_mode,
                performance_mode=performance_mode,
                selected_model=selected_model,
            )
            self._settle(pending, operation_id, reply, "committed")
        except Exception as exc:
            self._settle(pending, operation_id, "", "failed", error=str(exc))
            raise
        return self.repository.get_thread(thread.id) or thread

    def prepare_message(
        self,
        user_text: str,
        *,
        thread_id: str | None,
        model_profile: str,
        relationship_mode: str,
        performance_mode: str,
        rag_enabled: bool,
        rag_top_k: int,
        rag_retrieval_mode: str,
        rag_min_score: float,
    ) -> PreparedGroupMessage:
        thread = self._resolve_thread(thread_id, create=True)
        operation_id = new_id("group_op")
        self.repository.acquire_operation(
            thread.id,
            operation_id,
            settings_snapshot={
                **thread.settings_snapshot,
                "relationship_mode": relationship_mode,
                "performance_mode": performance_mode,
                "model_profile": model_profile,
                "mode": "interactive_group",
            },
        )
        try:
            history = _format_messages(self.repository.list_messages(thread.id))
            rag_result = self.dependencies.retrieve_local_knowledge(
                user_text,
                enabled=rag_enabled,
                top_k=rag_top_k,
                retrieval_mode=rag_retrieval_mode,
                min_score=rag_min_score,
            )
            user_message = GroupMessage(
                thread_id=thread.id,
                speaker="用户",
                content=user_text,
                status="committed",
                operation_id=operation_id,
            )
            pending = GroupMessage(
                thread_id=thread.id,
                speaker="群聊",
                status="streaming",
                operation_id=operation_id,
            )
            self.repository.start_exchange(user_message, pending)
        except Exception:
            self.repository.release_operation(thread.id, operation_id)
            raise
        return PreparedGroupMessage(
            thread=self.repository.get_thread(thread.id) or thread,
            message=pending,
            operation_id=operation_id,
            user_text=user_text,
            model_profile=model_profile,
            relationship_mode=relationship_mode,
            performance_mode=performance_mode,
            history_text=history,
            rag=rag_result.to_dict(),
            rag_context=str(getattr(rag_result, "context", "")),
        )

    def generate(self, prepared: PreparedGroupMessage) -> GroupMessage:
        try:
            reply = self.dependencies.generate_reply(
                prepared.user_text,
                model_profile=prepared.model_profile,
                relationship_mode=prepared.relationship_mode,
                rag_context=prepared.rag_context,
                performance_mode=prepared.performance_mode,
                history_text=prepared.history_text,
                first_reaction_done=bool(prepared.history_text),
            )
            return self.complete(prepared, reply)
        except Exception as exc:
            self.fail(prepared, str(exc))
            raise

    def stream(self, prepared: PreparedGroupMessage, *, should_cancel=None) -> Iterator[str]:
        stream, _ = self.dependencies.generate_reply_stream(
            prepared.user_text,
            model_profile=prepared.model_profile,
            relationship_mode=prepared.relationship_mode,
            rag_context=prepared.rag_context,
            performance_mode=prepared.performance_mode,
            should_cancel=should_cancel,
            history_text=prepared.history_text,
            first_reaction_done=bool(prepared.history_text),
        )
        return stream

    def complete(self, prepared: PreparedGroupMessage, reply: str) -> GroupMessage:
        return self._settle(
            prepared.message,
            prepared.operation_id,
            self.dependencies.normalize_reply(reply.strip()),
            "committed",
        )

    def interrupt(self, prepared: PreparedGroupMessage, partial: str) -> GroupMessage:
        return self._settle(
            prepared.message,
            prepared.operation_id,
            partial.strip(),
            "interrupted",
            error="generation interrupted",
        )

    def fail(self, prepared: PreparedGroupMessage, error: str) -> GroupMessage:
        return self._settle(
            prepared.message,
            prepared.operation_id,
            "",
            "failed",
            error=error,
        )

    def mark_read(self, thread_id: str | None) -> GroupThread:
        thread = self._resolve_thread(thread_id, create=False)
        return self.repository.mark_read(thread.id)

    def search(self, thread_id: str | None, keyword: str, limit: int) -> list[dict[str, str]]:
        thread = self._resolve_thread(thread_id, create=False)
        needle = keyword.casefold()
        results: list[dict[str, str]] = []
        for message in self.repository.list_messages(thread.id):
            if message.status != "committed":
                continue
            blocks = _message_blocks(message.content) or [(message.speaker, message.content)]
            for speaker, text in blocks:
                if needle in text.casefold():
                    results.append({"speaker": speaker, "text": text[:150]})
                    if len(results) >= limit:
                        return results
        return results

    def reset(self, thread_id: str | None) -> GroupThread:
        current = self._resolve_thread(thread_id, create=False)
        self.archive_thread(current.id)
        return self.create_thread(title="Study Group")

    def append_external_message(
        self,
        *,
        thread_id: str | None,
        speaker: str,
        content: str,
        message_type: str,
        unread: bool,
    ) -> GroupThread:
        thread = self._resolve_thread(thread_id, create=True)
        operation_id = new_id("group_op")
        self.repository.acquire_operation(thread.id, operation_id)
        pending = GroupMessage(
            thread_id=thread.id,
            speaker=speaker,
            status="streaming",
            message_type=message_type,
            operation_id=operation_id,
        )
        self.repository.start_exchange(None, pending)
        self.repository.settle_message(
            pending.id,
            operation_id=operation_id,
            content=content.strip(),
            status="committed",
            unread_delta=_display_count(pending, content=content) if unread else 0,
        )
        return self.repository.get_thread(thread.id) or thread

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
            exported = self.exporter.export_archive(
                locked, self.repository.list_messages(thread_id), path=path
            )
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

    def _settle(
        self,
        message: GroupMessage,
        operation_id: str,
        content: str,
        status: str,
        *,
        error: str = "",
    ) -> GroupMessage:
        unread_delta = _display_count(message, content=content) if status == "committed" else 0
        return self.repository.settle_message(
            message.id,
            operation_id=operation_id,
            content=content,
            status=status,
            error=error,
            unread_delta=unread_delta,
        )

    def _resolve_thread(self, thread_id: str | None, *, create: bool) -> GroupThread:
        self._import_legacy_once()
        if thread_id:
            thread = self.repository.get_thread(thread_id)
            if thread is None or thread.status != "active":
                raise ValueError(f"Group thread not found or inactive: {thread_id}")
            return thread
        active = next(
            (thread for thread in self.repository.list_threads() if thread.status == "active"),
            None,
        )
        if active is not None:
            return active
        if not create:
            raise ValueError("No active Group thread")
        return self.create_thread(title="Study Group")

    def _import_legacy_once(self) -> None:
        if self._legacy_imported:
            return
        self.importer.import_once(self.repository)
        self._legacy_imported = True


def _format_messages(messages: list[GroupMessage]) -> str:
    blocks: list[str] = []
    for message in messages:
        if message.status not in {"committed", "interrupted"} or not message.content.strip():
            continue
        if message.speaker == "群聊" and _message_blocks(message.content):
            blocks.append(message.content.strip())
        else:
            blocks.append(f"【{message.speaker}】\n{message.content.strip()}")
    return "\n\n".join(blocks)


def _display_count(message: GroupMessage, *, content: str | None = None) -> int:
    text = message.content if content is None else content
    return len(_message_blocks(text)) or (1 if text.strip() else 0)
