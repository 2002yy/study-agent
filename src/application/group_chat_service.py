"""GroupThread application service backed by SQLite runtime state."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import asyncio
from threading import Event
from typing import Any, AsyncIterator, Callable, Iterator

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
        unread_messages = self.repository.list_unread_messages(thread.id)
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
            "message_count": len(visible),
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
                status="pending",
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

    def generate(self, prepared: PreparedGroupMessage) -> str:
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

    async def stream_async(
        self, prepared: PreparedGroupMessage, *, cancel_event: Event | None = None
    ) -> AsyncIterator[str]:
        """Bridge the synchronous provider iterator without blocking the event loop."""

        stopped = cancel_event or Event()
        iterator = iter(self.stream(prepared, should_cancel=stopped.is_set))
        try:
            while not stopped.is_set():
                token, done = await asyncio.to_thread(_next_token, iterator)
                if done:
                    return
                yield token
        finally:
            stopped.set()
            close = getattr(iterator, "close", None)
            if callable(close):
                try:
                    close()
                except (RuntimeError, ValueError):
                    pass

    def complete(self, prepared: PreparedGroupMessage, reply: str) -> str:
        normalized = self.dependencies.normalize_reply(reply.strip())
        self._settle(
            prepared.message,
            prepared.operation_id,
            normalized,
            "committed",
        )
        return normalized

    def interrupt(self, prepared: PreparedGroupMessage, partial: str) -> list[GroupMessage]:
        return self._settle(
            prepared.message,
            prepared.operation_id,
            partial.strip(),
            "interrupted",
            error="generation interrupted",
        )

    def fail(self, prepared: PreparedGroupMessage, error: str) -> list[GroupMessage]:
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
            if needle in message.content.casefold():
                results.append({"speaker": message.speaker, "text": message.content[:150]})
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
        messages = _reply_messages(
            thread.id,
            operation_id,
            content.strip(),
            message_type=message_type,
            fallback_speaker=speaker,
        )
        self.repository.settle_exchange(
            pending.id,
            operation_id=operation_id,
            messages=messages,
            status="committed",
            count_unread=unread,
        )
        return self.repository.get_thread(thread.id) or thread

    def append_news_bundle(
        self,
        *,
        thread_id: str | None,
        source_block: str,
        discussion: str,
        news_run_id: str,
    ) -> GroupThread:
        thread = self._resolve_thread(thread_id, create=True)
        operation_id = f"group_news_{news_run_id}"
        messages: list[GroupMessage] = []
        if source_block.strip():
            messages.append(
                GroupMessage(
                    thread_id=thread.id,
                    speaker="系统",
                    content=source_block.strip(),
                    message_type="news_source",
                    operation_id=operation_id,
                )
            )
        replies = _reply_messages(
            thread.id,
            operation_id,
            discussion.strip(),
            message_type="news_discussion",
            fallback_speaker="群聊",
        )
        messages.extend(replies)
        self.repository.append_news_bundle(
            thread.id,
            operation_id,
            messages,
            unread_count=len(replies),
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
        self.repository.reserve_archive_path(thread_id, operation_id, path)
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
    ) -> list[GroupMessage]:
        messages = (
            _reply_messages(
                message.thread_id,
                operation_id,
                content,
                message_type=message.message_type,
                fallback_speaker=message.speaker,
            )
            if status == "committed"
            else []
        )
        return self.repository.settle_exchange(
            message.id,
            operation_id=operation_id,
            messages=messages,
            content=content,
            status=status,
            error=error,
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


def _reply_messages(
    thread_id: str,
    operation_id: str,
    content: str,
    *,
    message_type: str,
    fallback_speaker: str,
) -> list[GroupMessage]:
    blocks = _message_blocks(content) or [(fallback_speaker, content)]
    return [
        GroupMessage(
            thread_id=thread_id,
            speaker=speaker,
            content=text.strip(),
            status="committed",
            message_type=message_type,
            operation_id=operation_id,
        )
        for speaker, text in blocks
        if text.strip()
    ]


def _next_token(iterator: Iterator[str]) -> tuple[str, bool]:
    try:
        return next(iterator), False
    except StopIteration:
        return "", True
