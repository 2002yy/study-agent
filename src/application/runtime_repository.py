"""Runtime repository factory used by application services."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.runtime_repository import RuntimeRepository

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUNTIME_DB = ROOT / "logs" / "runtime" / "study_agent.db"
DEFAULT_CURRENT_DIR = ROOT / "logs" / "current"
DEFAULT_ARCHIVE_DIR = ROOT / "logs" / "sessions"


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


def reset_runtime_repository_cache() -> None:
    get_chat_service.cache_clear()
    get_session_service.cache_clear()
    get_runtime_repository.cache_clear()
