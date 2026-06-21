"""Runtime repository factory used by application services."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.runtime_repository import RuntimeRepository
from src.repositories.group_repository import GroupRepository

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUNTIME_DB = ROOT / "logs" / "runtime" / "study_agent.db"
DEFAULT_CURRENT_DIR = ROOT / "logs" / "current"
DEFAULT_ARCHIVE_DIR = ROOT / "logs" / "sessions"
DEFAULT_GROUP_FILE = ROOT / "chat" / "wechat_group.md"
DEFAULT_GROUP_UNREAD_FILE = ROOT / "chat" / "wechat_unread.md"
DEFAULT_GROUP_STATE_FILE = ROOT / "chat" / "wechat_state.md"
DEFAULT_GROUP_ARCHIVE_DIR = ROOT / "chat" / "archive"


def runtime_database_path() -> Path:
    configured = os.getenv("STUDY_AGENT_RUNTIME_DB", "").strip()
    return Path(configured).expanduser() if configured else DEFAULT_RUNTIME_DB


def runtime_current_dir() -> Path:
    configured = os.getenv("STUDY_AGENT_CURRENT_EXPORT_DIR", "").strip()
    return Path(configured).expanduser() if configured else DEFAULT_CURRENT_DIR


def runtime_archive_dir() -> Path:
    configured = os.getenv("STUDY_AGENT_ARCHIVE_EXPORT_DIR", "").strip()
    return Path(configured).expanduser() if configured else DEFAULT_ARCHIVE_DIR


@lru_cache(maxsize=1)
def get_runtime_repository() -> RuntimeRepository:
    return RuntimeRepository(RuntimeDatabase(runtime_database_path()))


@lru_cache(maxsize=1)
def get_group_repository() -> GroupRepository:
    return GroupRepository(RuntimeDatabase(runtime_database_path()))


@lru_cache(maxsize=1)
def get_chat_service():
    from src.application.chat_service import ChatService

    return ChatService(get_runtime_repository())


@lru_cache(maxsize=1)
def get_session_service():
    from src.application.session_service import SessionService

    return SessionService(
        get_runtime_repository(),
        current_dir=runtime_current_dir(),
        archive_dir=runtime_archive_dir(),
    )


@lru_cache(maxsize=1)
def get_group_service():
    from src.application.group_chat_service import GroupChatService

    return GroupChatService(
        get_group_repository(),
        group_file=DEFAULT_GROUP_FILE,
        unread_file=DEFAULT_GROUP_UNREAD_FILE,
        state_file=DEFAULT_GROUP_STATE_FILE,
        archive_dir=DEFAULT_GROUP_ARCHIVE_DIR,
    )


def reset_runtime_repository_cache() -> None:
    get_group_service.cache_clear()
    get_chat_service.cache_clear()
    get_session_service.cache_clear()
    get_group_repository.cache_clear()
    get_runtime_repository.cache_clear()
