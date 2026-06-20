from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from src.api import app
from src.application.chat_service import ChatDependencies, ChatService
from src.application.runtime_repository import get_chat_service, get_session_service
from src.application.session_service import SessionService
from src.context_builder import build_messages
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.mode_manager import RuntimeModes
from src.performance_budget import chat_max_tokens
from src.repositories.runtime_repository import RuntimeRepository
from src.router import route_request


class FakeRagResult:
    status = "skipped"
    context = ""

    def to_dict(self):
        return {
            "status": self.status,
            "context": self.context,
            "result_count": 0,
            "results": [],
        }


@dataclass
class RuntimeTestContext:
    repository: RuntimeRepository
    session_service: SessionService
    current_dir: Path
    archive_dir: Path

    def override_chat(self, dependencies: ChatDependencies) -> ChatService:
        service = ChatService(self.repository, dependencies)
        app.dependency_overrides[get_chat_service] = lambda: service
        return service


def default_chat_dependencies() -> ChatDependencies:
    async def async_tokens(*args, **kwargs):
        yield "Hello"
        yield " stream"

    return ChatDependencies(
        load_runtime_modes=lambda: RuntimeModes(performance_mode="fast"),
        read_memory_bundle=lambda context_mode: {},
        build_role_prompt=lambda role, **kwargs: f"role prompt for {role}",
        route_request=route_request,
        retrieve_local_knowledge=lambda *args, **kwargs: FakeRagResult(),
        build_messages=build_messages,
        chat=lambda messages, **kwargs: f"reply:{messages[-1]['content']}",
        stream_chat=lambda *args, **kwargs: iter(["Hello", " stream"]),
        async_stream_chat=async_tokens,
        chat_max_tokens=chat_max_tokens,
    )


@pytest.fixture(autouse=True)
def runtime_test_context(tmp_path):
    api_root = tmp_path / "api-runtime"
    repository = RuntimeRepository(RuntimeDatabase(api_root / "runtime.db"))
    current_dir = api_root / "current"
    archive_dir = api_root / "sessions"
    session_service = SessionService(
        repository,
        current_dir=current_dir,
        archive_dir=archive_dir,
    )
    chat_service = ChatService(repository, default_chat_dependencies())
    app.dependency_overrides[get_chat_service] = lambda: chat_service
    app.dependency_overrides[get_session_service] = lambda: session_service
    context = RuntimeTestContext(
        repository=repository,
        session_service=session_service,
        current_dir=current_dir,
        archive_dir=archive_dir,
    )
    yield context
    app.dependency_overrides.pop(get_chat_service, None)
    app.dependency_overrides.pop(get_session_service, None)
