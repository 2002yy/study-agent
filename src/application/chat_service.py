"""Application service for the ChatThread and ChatTurn lifecycle."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, AsyncIterator, Callable, Iterator

from src.context_builder import build_messages
from src.domain.runtime_entities import ChatThread, ChatTurn, new_id, utc_now
from src.llm_client import async_stream_chat, chat, stream_chat
from src.memory import read_memory_bundle
from src.mode_manager import load_runtime_modes
from src.performance_budget import chat_max_tokens
from src.repositories.runtime_repository import RuntimeRepository
from src.role_manager import build_role_prompt
from src.router import route_request
from src.tools.local_knowledge import retrieve_local_knowledge

PERFORMANCE_MODES = {"fast", "standard", "deep"}


@dataclass(frozen=True)
class ChatCommand:
    user_input: str
    selected_role: str = "auto"
    selected_mode: str = "auto"
    selected_model: str = "auto"
    relationship_mode: str = "standard"
    scene: str = "single"
    conversation_instruction: str = ""
    performance_mode: str | None = None
    context_mode: str | None = None
    previous_mode: str | None = None
    chat_history: list[dict[str, Any]] = field(default_factory=list)
    keep_current_role: bool = False
    thread_id: str | None = None
    rag_enabled: bool = False
    rag_top_k: int = 3
    rag_search_top_k: int | None = None
    rag_chat_top_k: int | None = None
    rag_retrieval_mode: str = "hybrid"
    rag_min_score: float = 0.01
    web_context: str = ""
    continuation_of_turn_id: str | None = None
    retry_of_turn_id: str | None = None
    partial_reply: str = ""
    turn_id: str | None = None


@dataclass(frozen=True)
class ChatDependencies:
    load_runtime_modes: Callable[[], Any] = load_runtime_modes
    read_memory_bundle: Callable[[str], dict[str, str]] = read_memory_bundle
    build_role_prompt: Callable[..., str] = build_role_prompt
    route_request: Callable[..., dict[str, Any]] = route_request
    retrieve_local_knowledge: Callable[..., Any] = retrieve_local_knowledge
    build_messages: Callable[..., list[dict[str, Any]]] = build_messages
    chat: Callable[..., str] = chat
    stream_chat: Callable[..., Iterator[str]] = stream_chat
    async_stream_chat: Callable[..., AsyncIterator[str]] = async_stream_chat
    chat_max_tokens: Callable[[str], int] = chat_max_tokens


@dataclass(frozen=True)
class PreparedChatTurn:
    thread: ChatThread
    turn: ChatTurn
    messages: list[dict[str, Any]]
    route: dict[str, Any]
    rag: dict[str, Any]
    runtime_modes: Any
    memory_enabled: bool
    web_context_used: bool
    is_continuation: bool
    base_reply: str
    retry_parent_turn_id: str | None


class ChatService:
    def __init__(
        self,
        repository: RuntimeRepository,
        dependencies: ChatDependencies | None = None,
    ):
        self.repository = repository
        self.dependencies = dependencies or ChatDependencies()

    def start_turn(self, command: ChatCommand) -> PreparedChatTurn:
        command, existing, retry_parent = self._validate_turn_command(command)
        runtime_modes = self._runtime_modes(command.performance_mode)
        context_mode = command.context_mode or runtime_modes.context_mode
        settings = _session_settings(command, context_mode)
        turn_id = command.turn_id or command.continuation_of_turn_id or new_id("turn")
        is_continuation = bool(command.continuation_of_turn_id)
        thread_id = command.thread_id or (
            existing.thread_id if existing is not None and is_continuation else ChatThread().id
        )
        if existing is not None and not is_continuation:
            raise ValueError(f"Chat turn already exists: {turn_id}")
        thread = self.repository.ensure_chat_thread(thread_id)
        operation_id = new_id("op")
        thread = self.repository.acquire_chat_operation(
            thread.id,
            operation_id,
            settings_snapshot={
                **settings,
                "conversationInstruction": command.conversation_instruction,
            },
        )
        try:
            route = self.dependencies.route_request(
                user_input=command.user_input,
                selected_role=command.selected_role,
                selected_mode=command.selected_mode,
                selected_model=command.selected_model,
                runtime_modes=runtime_modes,
                previous_role=_previous_assistant_role(command.chat_history),
                previous_mode=command.previous_mode,
                keep_current_role=command.keep_current_role,
            )
            role_prompt = self.dependencies.build_role_prompt(
                route["role"],
                scene=command.scene,
                relationship_mode=command.relationship_mode,
            )
            memory_bundle = self.dependencies.read_memory_bundle(context_mode)
            rag_result = self.dependencies.retrieve_local_knowledge(
                command.user_input,
                enabled=command.rag_enabled,
                top_k=command.rag_chat_top_k or command.rag_top_k,
                retrieval_mode=command.rag_retrieval_mode,
                min_score=command.rag_min_score,
            )
            rag = rag_result.to_dict()
            continuation_instruction = _continuation_instruction(command)
            context_blocks: list[str] = []
            if str(getattr(rag_result, "context", "")).strip():
                context_blocks.append(f"【本地资料检索结果】\n{rag_result.context}")
            if command.web_context.strip():
                context_blocks.append(f"【联网检索结果】\n{command.web_context.strip()}")
            if continuation_instruction:
                context_blocks.append(continuation_instruction)
            messages = self.dependencies.build_messages(
                user_input=command.user_input,
                role_prompt=role_prompt,
                mode=route["mode"],
                memory_bundle=memory_bundle,
                chat_history=command.chat_history,
                relationship_mode=command.relationship_mode,
                runtime_modes=runtime_modes,
                context_mode=context_mode,
                rag_context="\n\n".join(context_blocks),
                scene=command.scene,
                conversation_instruction=command.conversation_instruction,
            )
            base_reply = ""
            if is_continuation:
                base_reply = _preferred_partial_reply(
                    existing.assistant_message if existing else "",
                    command.partial_reply,
                )
            now = utc_now()
            if existing is None:
                pending = ChatTurn(
                    id=turn_id,
                    thread_id=thread.id,
                    user_message=command.user_input,
                    assistant_message=base_reply,
                    status="pending",
                    role=route["role"],
                    mode=route["mode"],
                    model=route["model_profile"],
                    route_snapshot=route,
                    rag_snapshot=rag,
                    parent_turn_id=retry_parent.id if retry_parent else None,
                    operation_id=operation_id,
                    conversation_instruction=command.conversation_instruction,
                    created_at=now,
                    updated_at=now,
                )
                self.repository.add_chat_turn(pending)
            streaming = self.repository.update_chat_turn(
                turn_id,
                assistant_message=base_reply,
                status="streaming",
                role=route["role"],
                mode=route["mode"],
                model=route["model_profile"],
                route_snapshot=route,
                rag_snapshot=rag,
                operation_id=operation_id,
                expected_operation_id=(operation_id if existing is None else existing.operation_id),
                enforce_operation_owner=True,
                expected_status="pending" if existing is None else "interrupted",
            )
            if streaming is None:
                raise RuntimeError(f"Chat turn was not created: {turn_id}")
        except Exception:
            self.repository.release_chat_operation(thread.id, operation_id)
            raise
        return PreparedChatTurn(
            thread=self.repository.get_chat_thread(thread.id) or thread,
            turn=streaming,
            messages=messages,
            route=route,
            rag=rag,
            runtime_modes=runtime_modes,
            memory_enabled=bool(memory_bundle),
            web_context_used=bool(command.web_context.strip()),
            is_continuation=is_continuation,
            base_reply=base_reply,
            retry_parent_turn_id=retry_parent.id if retry_parent else None,
        )

    def generate(self, prepared: PreparedChatTurn) -> str:
        try:
            suffix = self.dependencies.chat(
                prepared.messages,
                model_profile=prepared.route["model_profile"],
                max_tokens=self.dependencies.chat_max_tokens(
                    prepared.runtime_modes.performance_mode
                ),
                task_name="single_chat",
            )
        except Exception:
            self.fail_turn(prepared)
            raise
        return self.complete_turn(prepared, suffix).assistant_message

    def stream(self, prepared: PreparedChatTurn, *, should_cancel=None) -> Iterator[str]:
        return self.dependencies.stream_chat(
            prepared.messages,
            model_profile=prepared.route["model_profile"],
            max_tokens=self.dependencies.chat_max_tokens(
                prepared.runtime_modes.performance_mode
            ),
            task_name="single_chat",
            should_cancel=should_cancel,
        )

    async def stream_async(self, prepared: PreparedChatTurn) -> AsyncIterator[str]:
        async for token in self.dependencies.async_stream_chat(
            prepared.messages,
            model_profile=prepared.route["model_profile"],
            max_tokens=self.dependencies.chat_max_tokens(
                prepared.runtime_modes.performance_mode
            ),
            task_name="single_chat",
        ):
            yield token

    def complete_turn(self, prepared: PreparedChatTurn, suffix: str) -> ChatTurn:
        reply = f"{prepared.base_reply}{suffix}" if prepared.is_continuation else suffix
        updated = self.repository.update_chat_turn(
            prepared.turn.id,
            assistant_message=reply,
            status="completed",
            role=prepared.route["role"],
            mode=prepared.route["mode"],
            model=prepared.route["model_profile"],
            route_snapshot={
                **prepared.route,
                "web_context_used": prepared.web_context_used,
                "is_continuation": prepared.is_continuation,
                "is_continuation_resolved": prepared.is_continuation,
            },
            rag_snapshot=prepared.rag,
            operation_id=prepared.turn.operation_id,
            expected_operation_id=prepared.turn.operation_id,
            enforce_operation_owner=True,
            expected_status="streaming",
            release_operation=True,
            supersede_parent_turn_id=prepared.retry_parent_turn_id,
        )
        if updated is None:
            raise RuntimeError(f"Chat turn disappeared: {prepared.turn.id}")
        return updated

    def interrupt_turn(self, prepared: PreparedChatTurn, suffix: str) -> ChatTurn:
        reply = f"{prepared.base_reply}{suffix}" if prepared.is_continuation else suffix
        updated = self.repository.update_chat_turn(
            prepared.turn.id,
            assistant_message=reply,
            status="interrupted",
            route_snapshot={**prepared.route, "interrupted": True},
            rag_snapshot=prepared.rag,
            operation_id=prepared.turn.operation_id,
            expected_operation_id=prepared.turn.operation_id,
            enforce_operation_owner=True,
            expected_status="streaming",
            release_operation=True,
        )
        if updated is None:
            raise RuntimeError(f"Chat turn disappeared: {prepared.turn.id}")
        return updated

    def fail_turn(self, prepared: PreparedChatTurn, suffix: str = "") -> ChatTurn:
        reply = f"{prepared.base_reply}{suffix}" if prepared.is_continuation else suffix
        updated = self.repository.update_chat_turn(
            prepared.turn.id,
            assistant_message=reply,
            status="failed",
            route_snapshot={**prepared.route, "failed": True},
            rag_snapshot=prepared.rag,
            operation_id=prepared.turn.operation_id,
            expected_operation_id=prepared.turn.operation_id,
            enforce_operation_owner=True,
            expected_status="streaming",
            release_operation=True,
        )
        if updated is None:
            raise RuntimeError(f"Chat turn disappeared: {prepared.turn.id}")
        return updated

    def _validate_turn_command(
        self,
        command: ChatCommand,
    ) -> tuple[ChatCommand, ChatTurn | None, ChatTurn | None]:
        if command.continuation_of_turn_id and command.retry_of_turn_id:
            raise ValueError("A chat turn cannot be both a continuation and a retry")
        if command.continuation_of_turn_id:
            target_id = command.continuation_of_turn_id
            if command.turn_id and command.turn_id != target_id:
                raise ValueError("turn_id must match continuation_of_turn_id")
            existing = self.repository.get_chat_turn(target_id)
            if existing is None:
                raise ValueError(f"Continuation target does not exist: {target_id}")
            if command.thread_id and command.thread_id != existing.thread_id:
                raise ValueError(f"Chat turn {target_id} belongs to a different thread")
            if existing.status != "interrupted":
                raise ValueError(
                    f"Chat turn cannot be continued from status {existing.status}: {target_id}"
                )
            return (
                replace(
                    command,
                    user_input=existing.user_message,
                    thread_id=existing.thread_id,
                    turn_id=target_id,
                ),
                existing,
                None,
            )
        retry_parent = None
        if command.retry_of_turn_id:
            retry_parent = self.repository.get_chat_turn(command.retry_of_turn_id)
            if retry_parent is None:
                raise ValueError(f"Retry target does not exist: {command.retry_of_turn_id}")
            if command.thread_id and command.thread_id != retry_parent.thread_id:
                raise ValueError(
                    f"Chat turn {command.retry_of_turn_id} belongs to a different thread"
                )
            if retry_parent.status not in {"interrupted", "failed"}:
                raise ValueError(
                    f"Chat turn cannot be retried from status {retry_parent.status}: {retry_parent.id}"
                )
            command = replace(
                command,
                user_input=retry_parent.user_message,
                thread_id=retry_parent.thread_id,
            )
        existing = self.repository.get_chat_turn(command.turn_id) if command.turn_id else None
        if existing is not None and command.thread_id and existing.thread_id != command.thread_id:
            raise ValueError(f"Chat turn {existing.id} belongs to a different thread")
        return command, existing, retry_parent

    def commit_partial_turn(
        self,
        *,
        thread_id: str,
        turn_id: str,
        user_input: str,
        assistant_message: str,
        role: str,
        mode: str,
        model: str,
        route_snapshot: dict[str, Any],
        rag_snapshot: dict[str, Any],
        conversation_instruction: str,
    ) -> tuple[ChatTurn, bool]:
        thread = self.repository.get_chat_thread(thread_id)
        if thread is None or thread.status != "active":
            raise ValueError(f"Chat thread not found or inactive: {thread_id}")
        existing = self.repository.get_chat_turn(turn_id)
        if existing is None:
            raise ValueError(f"Chat turn not found: {turn_id}")
        if existing.thread_id != thread_id:
            raise ValueError(
                f"Chat turn {turn_id} belongs to a different thread"
            )
        if existing.status not in {"streaming", "interrupted"}:
            return existing, False
        stored_reply = assistant_message
        if existing.assistant_message:
            stored_reply = _preferred_partial_reply(
                existing.assistant_message,
                assistant_message,
            )
        if existing.status == "interrupted" and existing.assistant_message == stored_reply:
            return existing, False
        updated = self.repository.update_chat_turn(
            turn_id,
            assistant_message=stored_reply,
            status="interrupted",
            expected_operation_id=existing.operation_id,
            enforce_operation_owner=existing.status == "streaming",
            expected_status=existing.status,
            release_operation=existing.status == "streaming",
        )
        if updated is None:
            raise ValueError(f"Chat turn not found: {turn_id}")
        return updated, True

    def _runtime_modes(self, requested: str | None):
        runtime_modes = self.dependencies.load_runtime_modes()
        if not requested:
            return runtime_modes
        if requested not in PERFORMANCE_MODES:
            raise ValueError(f"Invalid performance_mode: {requested}")
        return replace(runtime_modes, performance_mode=requested)


def _previous_assistant_role(history: list[dict[str, Any]]) -> str | None:
    valid_roles = {"nahida", "march7", "keqing", "firefly"}
    for message in reversed(history):
        if message.get("role") != "assistant":
            continue
        avatar_role = message.get("avatarRole")
        if avatar_role in valid_roles:
            return str(avatar_role)
    return None


def _continuation_instruction(command: ChatCommand) -> str:
    if not command.continuation_of_turn_id or not command.partial_reply.strip():
        return ""
    return (
        "[继续生成指令]\n"
        "请从下面已经输出的内容之后继续回答，不要重复已输出的部分。\n"
        f"已输出内容：\n{command.partial_reply.strip()[:800]}"
    )


def _preferred_partial_reply(stored: str, supplied: str) -> str:
    if not stored:
        return supplied
    if not supplied or supplied == stored:
        return stored
    if supplied.startswith(stored):
        return supplied
    if stored.startswith(supplied):
        return stored
    raise ValueError("Supplied partial reply conflicts with the stored turn")


def _session_settings(command: ChatCommand, context_mode: str) -> dict[str, Any]:
    chat_top_k = command.rag_chat_top_k or command.rag_top_k
    return {
        "selectedRole": command.selected_role,
        "selectedMode": command.selected_mode,
        "selectedModel": command.selected_model,
        "relationshipMode": command.relationship_mode,
        "contextMode": context_mode,
        "ragEnabled": command.rag_enabled,
        "ragSettings": {
            "chatTopK": chat_top_k,
            "topK": command.rag_search_top_k or chat_top_k,
            "retrievalMode": command.rag_retrieval_mode,
            "minScore": command.rag_min_score,
        },
        "keepCurrentRole": command.keep_current_role,
    }
