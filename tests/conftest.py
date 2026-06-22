from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from src import api as api_module
from src.api import app
from src.application.chat_service import ChatDependencies, ChatService
from src.application.group_chat_service import GroupChatService, GroupDependencies
from src.application.news_service import NewsService
from src.application.tool_service import ToolService
from src.application.runtime_repository import (
    get_chat_service,
    get_group_service,
    get_news_service,
    get_session_service,
    get_tool_service,
)
from src.application.session_service import SessionService
from src.context_builder import build_messages
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.mode_manager import RuntimeModes
from src.performance_budget import chat_max_tokens
from src.repositories.runtime_repository import RuntimeRepository
from src.repositories.group_repository import GroupRepository
from src.repositories.news_repository import NewsRepository
from src.repositories.tool_repository import ToolRepository
from src.router import route_request
from src.tools.registry import create_default_tool_registry
from src.workflows.store import WorkflowStore


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
    group_repository: GroupRepository
    group_service: GroupChatService
    news_repository: NewsRepository
    news_service: NewsService
    tool_repository: ToolRepository
    tool_service: ToolService

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
    group_repository = GroupRepository(RuntimeDatabase(api_root / "runtime.db"))
    current_dir = api_root / "current"
    archive_dir = api_root / "sessions"
    session_service = SessionService(
        repository,
        current_dir=current_dir,
        archive_dir=archive_dir,
    )
    chat_service = ChatService(repository, default_chat_dependencies())
    group_dependencies = GroupDependencies(
        retrieve_local_knowledge=lambda *args, **kwargs: FakeRagResult(),
        generate_opening=lambda **kwargs: "【纳西妲】\nopening",
        generate_reply=lambda *args, **kwargs: "【纳西妲】\ngroup reply",
        generate_reply_stream=lambda *args, **kwargs: (
            iter(["【纳西妲】\n", "stream reply"]),
            False,
        ),
        normalize_reply=lambda content: content,
    )
    group_service = GroupChatService(
        group_repository,
        group_file=api_root / "chat" / "wechat_group.md",
        unread_file=api_root / "chat" / "wechat_unread.md",
        state_file=api_root / "chat" / "wechat_state.md",
        archive_dir=api_root / "group-archive",
        dependencies=group_dependencies,
    )
    news_repository = NewsRepository(RuntimeDatabase(api_root / "runtime.db"))
    news_service = NewsService(news_repository, group_service)
    tool_repository = ToolRepository(RuntimeDatabase(api_root / "runtime.db"))
    tool_service = ToolService(
        tool_repository,
        create_default_tool_registry(),
        workflow_store_factory=lambda: WorkflowStore(api_module.WORKFLOW_DIR),
    )
    app.dependency_overrides[get_chat_service] = lambda: chat_service
    app.dependency_overrides[get_session_service] = lambda: session_service
    app.dependency_overrides[get_group_service] = lambda: group_service
    app.dependency_overrides[get_news_service] = lambda: news_service
    app.dependency_overrides[get_tool_service] = lambda: tool_service
    context = RuntimeTestContext(
        repository=repository,
        session_service=session_service,
        current_dir=current_dir,
        archive_dir=archive_dir,
        group_repository=group_repository,
        group_service=group_service,
        news_repository=news_repository,
        news_service=news_service,
        tool_repository=tool_repository,
        tool_service=tool_service,
    )
    yield context
    app.dependency_overrides.pop(get_chat_service, None)
    app.dependency_overrides.pop(get_session_service, None)
    app.dependency_overrides.pop(get_group_service, None)
    app.dependency_overrides.pop(get_news_service, None)
    app.dependency_overrides.pop(get_tool_service, None)
