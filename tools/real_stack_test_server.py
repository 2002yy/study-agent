"""Deterministic FastAPI entrypoint for real-stack browser gates.

This module keeps the production HTTP routes, application services and SQLite
repositories intact while replacing only external model and network gateways.
It must never be used as the normal application entrypoint.
"""

from __future__ import annotations

import asyncio
import gc
import os
import shutil
import time
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path
from typing import Any, AsyncIterator, Iterator

ROOT = Path(__file__).resolve().parents[1]
E2E_ROOT = Path(
    os.getenv(
        "STUDY_AGENT_E2E_ROOT",
        str(ROOT / "frontend" / "test-results" / "real-stack-runtime"),
    )
).resolve()
RAG_INDEX_PATH = E2E_ROOT / "rag_index.json"
RAG_UPLOAD_DIR = E2E_ROOT / "rag_uploads"
MEMORY_DIR = E2E_ROOT / "memory"
FRONTEND_SETTINGS_PATH = E2E_ROOT / "frontend_settings.yaml"

if os.getenv("STUDY_AGENT_E2E_RESET", "").strip() == "1":
    shutil.rmtree(E2E_ROOT, ignore_errors=True)
E2E_ROOT.mkdir(parents=True, exist_ok=True)

# These values must be fixed before importing the application assembly point.
os.environ["STUDY_AGENT_API_TOKEN"] = ""
os.environ.setdefault("STUDY_AGENT_RUNTIME_DB", str(E2E_ROOT / "runtime.db"))
os.environ.setdefault(
    "STUDY_AGENT_CURRENT_EXPORT_DIR", str(E2E_ROOT / "current")
)
os.environ.setdefault(
    "STUDY_AGENT_ARCHIVE_EXPORT_DIR", str(E2E_ROOT / "archive")
)
os.environ.setdefault("RAG_VECTOR_BACKEND", "local")
os.environ.setdefault("RAG_EMBEDDING_PROFILE", "local_hash")
os.environ.setdefault("RAG_EMBEDDING_PROVIDER", "local_hash")

from fastapi import HTTPException  # noqa: E402
from starlette.types import ASGIApp, Receive, Scope, Send  # noqa: E402

from src import api as api_package  # noqa: E402
from src import memory as memory_module  # noqa: E402
from src import memory_writer as memory_writer_module  # noqa: E402
from src.api.app import app  # noqa: E402
from src.application import memory_service as memory_service_module  # noqa: E402
from src.application.chat_service import ChatDependencies  # noqa: E402
from src.application.learning_closure_service import (  # noqa: E402
    LearningClosureService,
)
from src.application.policy_chat_service import (  # noqa: E402
    ExternalDataPolicyChatService,
)
from src.application.runtime_repository import (  # noqa: E402
    get_chat_service,
    get_learning_closure_repository,
    get_learning_closure_service,
    get_memory_service,
    get_pedagogy_eval_repository,
    get_runtime_repository,
    get_session_service,
    reset_runtime_repository_cache,
    runtime_database_path,
)
from src.context_builder import build_messages  # noqa: E402
from src.infrastructure.sqlite.database import RuntimeDatabase  # noqa: E402
from src.mode_manager import RuntimeModes  # noqa: E402
from src.pedagogy.evaluation import SemanticEvaluation  # noqa: E402
from src.rag import index as rag_index_module  # noqa: E402
from src.task_contract import (  # noqa: E402
    TaskAwarePedagogyEngine,
    TaskAwarePedagogyEvaluationService,
    route_request_with_task_contract,
)
from src.tools.local_knowledge import retrieve_local_knowledge  # noqa: E402
from src.tools.web_agent import WebToolTrace  # noqa: E402


class _ExclusiveE2EResetMiddleware:
    """Drain active HTTP requests before deleting shared real-stack state."""

    def __init__(self, app: ASGIApp):
        self.app = app
        self._condition = asyncio.Condition()
        self._active_requests = 0
        self._resetting = False

    async def __call__(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        is_reset = scope.get("path") == "/__e2e__/reset"
        reset_timed_out = False
        async with self._condition:
            if is_reset:
                await self._condition.wait_for(lambda: not self._resetting)
                self._resetting = True
                try:
                    await asyncio.wait_for(
                        self._condition.wait_for(
                            lambda: self._active_requests == 0
                        ),
                        timeout=15.0,
                    )
                except TimeoutError:
                    self._resetting = False
                    self._condition.notify_all()
                    reset_timed_out = True
            else:
                await self._condition.wait_for(lambda: not self._resetting)
                self._active_requests += 1

        if reset_timed_out:
            body = b'{"detail":"Timed out draining active E2E requests"}'
            await send(
                {
                    "type": "http.response.start",
                    "status": 503,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode("ascii")),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return

        try:
            await self.app(scope, receive, send)
        finally:
            async with self._condition:
                if is_reset:
                    self._resetting = False
                else:
                    self._active_requests -= 1
                self._condition.notify_all()


app.add_middleware(_ExclusiveE2EResetMiddleware)

FIRST_REPLY = (
    "我们先建立目标：理解为什么二分查找是 O(log n)。"
    "请说明每一轮会怎样改变候选区间？"
)
BARE_REPLY = "只说“懂了”还不足以确认掌握。请用因果关系解释候选区间怎样变化？"
CORRECT_REPLY = "这段解释已经通过理解验证；下一步把减半过程迁移到查找次数估算。"
MATERIAL_REPLY = (
    "根据刚上传的资料，目标值大于中点值时，左边界更新为 mid + 1。"
    "请解释为什么不能仍把 mid 留在候选区间。"
)
INTERRUPT_QUESTION = "请生成一段可中断的二分查找边界讲解"
INTERRUPT_REPLY = (
    "第一部分：二分查找每轮先比较中点与目标值。"
    "第二部分：目标值更大时左边界移动到 mid + 1，因为 mid 已被排除。"
    "第三部分：持续缩小区间直到找到目标或区间为空。"
)
FAIL_ONCE_QUESTION = "请触发一次可重试的确定性失败"
RETRY_REPLY = "重试成功：这次回答只提交一次，并保留失败父回合作为可审计记录。"
DEEP_QUESTION_PREFIX = "请深度研究："
DEEP_REPLY = (
    "深度研究回答完成：DEEP-ANSWER-OK，已依据本轮实际读取的正文整理。"
)
DEEP_ANSWER_REPLY = (
    "根据这次研究读取的正文：DEEP-ANSWER-OK，OMEGA 协议的延迟对比已完成。"
)
DEEP_OBSERVATION_MARKER = "DEEP-OBSERVATION-42"

_failure_attempts: dict[str, int] = {}
# G12 acceptance gate: injectable slow retrieval (decision 4).
_retrieval_delay: dict[str, float] = {"seconds": 0.0}


def _test_runtime_modes() -> RuntimeModes:
    return RuntimeModes(
        memory_mode="confirm_write",
        safe_mode=False,
        performance_mode="fast",
        entry_mode="single",
    )


# Isolate every filesystem owner used by the real upload and memory workflows.
api_package.RAG_UPLOAD_DIR = RAG_UPLOAD_DIR
api_package.MEMORY_DIR = MEMORY_DIR
api_package.FRONTEND_SETTINGS_PATH = FRONTEND_SETTINGS_PATH
api_package.load_runtime_modes = _test_runtime_modes
api_package.is_memory_write_allowed = lambda _modes: True
memory_module.MEMORY_DIR = MEMORY_DIR
rag_index_module.DEFAULT_RAG_INDEX_PATH = RAG_INDEX_PATH
memory_service_module.load_runtime_modes = _test_runtime_modes
memory_service_module.is_memory_write_allowed = lambda _modes: True
memory_writer_module.load_runtime_modes = _test_runtime_modes
memory_writer_module.is_memory_write_allowed = lambda _modes: True
memory_writer_module.MEMORY_TARGETS = {
    "index": MEMORY_DIR / "index.md",
    "summary": MEMORY_DIR / "summary.md",
    "archive_summary": MEMORY_DIR / "archive_summary.md",
    "progress": MEMORY_DIR / "progress.md",
    "current_focus": MEMORY_DIR / "current_focus.md",
    "learner_profile": MEMORY_DIR / "learner_profile.md",
    "project_context": MEMORY_DIR / "project_context.md",
    "revision_notes": MEMORY_DIR / "revision_notes.md",
    "session_archive": MEMORY_DIR / "session_archive.md",
}


class DeterministicSemanticEvaluator:
    """Accept only the explicit reasoned binary-search explanation used by E2E."""

    def evaluate(
        self,
        *,
        learner_input: str,
        objective: str,
        protocol: str,
        expected_concepts: tuple[str, ...],
        evidence: tuple[str, ...],
    ) -> SemanticEvaluation:
        del objective, protocol, expected_concepts, evidence
        compact = learner_input.lower().replace(" ", "")
        accepted = (
            "每轮" in learner_input
            and ("减半" in learner_input or "一半" in learner_input)
            and ("对数" in learner_input or "o(logn)" in compact)
        )
        if accepted:
            return SemanticEvaluation(
                claims=("候选区间每轮减半", "查找次数是对数级"),
                correct_points=("每次将剩余问题规模缩小为原来的一半",),
                reasoning_complete=True,
                transfer_ready=True,
                confidence=0.96,
            )
        return SemanticEvaluation(
            claims=(learner_input.strip(),) if learner_input.strip() else (),
            gaps=("需要说明区间缩小与复杂度之间的因果关系",),
            reasoning_complete=False,
            transfer_ready=False,
            confidence=0.35,
        )


def _last_user_message(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return str(message.get("content", ""))
    return ""


def _continuation_partial(messages: list[dict[str, Any]]) -> str:
    marker = "已输出内容：\n"
    for message in reversed(messages):
        content = str(message.get("content", ""))
        if "[继续生成指令]" not in content or marker not in content:
            continue
        return content.split(marker, 1)[1].strip()
    return ""


def _reply_for(messages: list[dict[str, Any]]) -> str:
    user_input = _last_user_message(messages).strip()
    joined = "\n".join(str(message.get("content") or "") for message in messages)
    if DEEP_OBSERVATION_MARKER in joined:
        return DEEP_ANSWER_REPLY
    if user_input.startswith(DEEP_QUESTION_PREFIX):
        return DEEP_REPLY
    if user_input == INTERRUPT_QUESTION:
        return INTERRUPT_REPLY
    if user_input == FAIL_ONCE_QUESTION:
        return RETRY_REPLY
    if "刚上传" in user_input and "左边界" in user_input:
        return MATERIAL_REPLY
    if user_input.rstrip("。！？.! ") == "懂了":
        return BARE_REPLY
    compact = user_input.lower().replace(" ", "")
    if (
        "每轮" in user_input
        and ("减半" in user_input or "一半" in user_input)
        and ("对数" in user_input or "o(logn)" in compact)
    ):
        return CORRECT_REPLY
    return FIRST_REPLY


def _chunks(text: str, size: int = 12) -> tuple[str, ...]:
    return tuple(text[index : index + size] for index in range(0, len(text), size))


def _chat(messages: list[dict[str, Any]], **_kwargs: Any) -> str:
    return _reply_for(messages)


def _stream_chat(
    messages: list[dict[str, Any]], **_kwargs: Any
) -> Iterator[str]:
    yield from _chunks(_reply_for(messages))


async def _async_stream_chat(
    messages: list[dict[str, Any]], **_kwargs: Any
) -> AsyncIterator[str]:
    user_input = _last_user_message(messages).strip()
    if user_input == FAIL_ONCE_QUESTION:
        attempts = _failure_attempts.get(user_input, 0) + 1
        _failure_attempts[user_input] = attempts
        if attempts == 1:
            await asyncio.sleep(0.02)
            raise RuntimeError("deterministic upstream failure before first token")

    full_reply = _reply_for(messages)
    partial = _continuation_partial(messages)
    reply = full_reply[len(partial) :] if partial and full_reply.startswith(partial) else full_reply
    delay = 0.18 if user_input == INTERRUPT_QUESTION and not partial else 0.003
    size = 10 if user_input == INTERRUPT_QUESTION else 12
    for chunk in _chunks(reply, size=size):
        await asyncio.sleep(delay)
        yield chunk


def _real_stack_retrieve(
    query: str,
    *,
    enabled: bool = True,
    force: bool = False,
    top_k: int = 3,
    min_score: float = 0.01,
    retrieval_mode: str = "hybrid",
    **_kwargs: Any,
):
    # G12 decision 4 gate: inject a slow retrieval so the acceptance journey
    # can measure cancel-registration → durable-terminal latency.
    if _retrieval_delay["seconds"] > 0:
        time.sleep(_retrieval_delay["seconds"])
    return retrieve_local_knowledge(
        query,
        enabled=enabled,
        force=force,
        index_path=RAG_INDEX_PATH,
        top_k=top_k,
        min_score=min_score,
        retrieval_mode=retrieval_mode,
    )


def _closure_generator(
    structured_input: dict[str, Any],
    _memory_context: dict[str, str],
    _role: str,
    _mode: str,
    **_kwargs: Any,
) -> dict[str, str]:
    committed = structured_input.get("committed_learning_state")
    committed_state = committed if isinstance(committed, dict) else {}
    confirmed = [
        str(item).strip()
        for item in committed_state.get("confirmed_points", [])
        if str(item).strip()
    ]
    unresolved = str(committed_state.get("unresolved_gap") or "").strip()
    progress = confirmed[-1] if confirmed else "本次没有足够证据形成新的确认结论"
    return {
        "progress_update": f"已确认：{progress}",
        "learner_profile_update": "本轮无需更新",
        "current_focus_update": "下一步练习二分查找边界迁移",
        "revision_notes_update": unresolved or "继续解释左右边界更新时机",
        "session_archive_update": "完成二分查找复杂度理解验证并保留后续边界练习",
        "role_updates": "本轮无需更新",
    }


@lru_cache(maxsize=1)
def _real_stack_chat_service() -> ExternalDataPolicyChatService:
    dependencies = ChatDependencies(
        load_runtime_modes=_test_runtime_modes,
        read_memory_bundle=lambda _context_mode: {},
        build_role_prompt=lambda role, **_kwargs: f"role:{role}",
        route_request=route_request_with_task_contract,
        retrieve_local_knowledge=_real_stack_retrieve,
        build_messages=build_messages,
        chat=_chat,
        stream_chat=_stream_chat,
        async_stream_chat=_async_stream_chat,
        chat_max_tokens=lambda _performance_mode: 1000,
        pedagogy_engine=TaskAwarePedagogyEngine(),
        pedagogy_evaluation=TaskAwarePedagogyEvaluationService(
            DeterministicSemanticEvaluator()
        ),
        resolve_web_tools=lambda *_args, **_kwargs: WebToolTrace(enabled=False),
    )
    return ExternalDataPolicyChatService(get_runtime_repository(), dependencies)


@lru_cache(maxsize=1)
def _real_stack_closure_service() -> LearningClosureService:
    return LearningClosureService(
        get_learning_closure_repository(),
        get_session_service(),
        get_memory_service(),
        evaluation_repository=get_pedagogy_eval_repository(),
        generator=_closure_generator,
        memory_bundle_loader=lambda _mode: {},
    )


app.dependency_overrides[get_chat_service] = _real_stack_chat_service
app.dependency_overrides[get_learning_closure_service] = _real_stack_closure_service


def _remove_runtime_database() -> None:
    # Request draining closes repository connection contexts before Windows
    # file deletion; collect any delayed finalizers as an additional safeguard.
    gc.collect()
    database_path = runtime_database_path()
    for suffix in ("", "-wal", "-shm"):
        Path(f"{database_path}{suffix}").unlink(missing_ok=True)


def _reset_filesystem_state() -> None:
    RAG_INDEX_PATH.unlink(missing_ok=True)
    FRONTEND_SETTINGS_PATH.unlink(missing_ok=True)
    for directory in (
        E2E_ROOT / "current",
        E2E_ROOT / "archive",
        RAG_UPLOAD_DIR,
        MEMORY_DIR,
    ):
        shutil.rmtree(directory, ignore_errors=True)
    memory_module._read_text_file_cached.cache_clear()


@app.post("/__e2e__/reset")
def reset_real_stack_state() -> dict[str, Any]:
    """Reset all durable test state between isolated browser journeys."""

    _failure_attempts.clear()
    _retrieval_delay["seconds"] = 0.0
    _real_stack_chat_service.cache_clear()
    _real_stack_closure_service.cache_clear()
    reset_runtime_repository_cache()
    _remove_runtime_database()
    RuntimeDatabase(runtime_database_path()).initialize()
    _reset_filesystem_state()
    return {
        "reset": True,
        "database_path": str(runtime_database_path()),
        "rag_index_path": str(RAG_INDEX_PATH),
        "memory_dir": str(MEMORY_DIR),
    }


@app.post("/__e2e__/retrieval-delay")
def set_retrieval_delay(payload: dict[str, Any]) -> dict[str, Any]:
    """Inject a slow local retrieval for the G12 cancel-latency gate."""

    seconds = float(payload.get("seconds", 0))
    _retrieval_delay["seconds"] = max(0.0, min(seconds, 30.0))
    return {"seconds": _retrieval_delay["seconds"]}


@app.get("/__e2e__/state/{session_id}")
def read_real_stack_state(session_id: str) -> dict[str, Any]:
    """Expose raw durable truth only from this dedicated test entrypoint."""

    repository = get_runtime_repository()
    thread = repository.get_chat_thread(session_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return {
        "database_path": str(runtime_database_path()),
        "thread": asdict(thread),
        "turns": [asdict(turn) for turn in repository.list_chat_turns(session_id)],
        "summary": get_session_service().summary_payload(session_id),
    }


@app.get("/__e2e__/latest-thread")
def read_latest_thread() -> dict[str, Any]:
    """Latest chat thread that actually has turns — G12 acceptance helper.

    The cooperative-cancel journey can settle a turn before the browser ever
    receives the session SSE event, so tests cannot rely on localStorage to
    discover the session id. Empty threads (e.g. freshly created sessions)
    are skipped so the cancelled journey remains observable.
    """

    repository = get_runtime_repository()
    for thread in repository.list_chat_threads(limit=20):
        turns = repository.list_chat_turns(thread.id)
        if turns:
            return {
                "session_id": thread.id,
                "thread": asdict(thread),
                "turns": [asdict(turn) for turn in turns],
            }
    raise HTTPException(status_code=404, detail="No chat threads with turns yet")
