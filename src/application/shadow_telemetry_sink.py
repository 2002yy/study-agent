"""Durable, best-effort JSONL sink for shadow telemetry.

Telemetry may be dropped; it may never break research. Writes are append-only and
swallow every failure, so a full disk or permissions error degrades to "no record",
never to a failed turn.

Path is configurable via ``BSEARCH_STANDARD_SHADOW_LOG``; the default keeps
observations under ``artifacts/shadow/`` in the process working directory.
"""

from __future__ import annotations

import atexit
import json
import os
import threading
from pathlib import Path
from typing import Any

LOG_PATH_ENV = "BSEARCH_STANDARD_SHADOW_LOG"
DEFAULT_RELATIVE = Path("artifacts") / "shadow" / "bsearch_standard.jsonl"


def shadow_log_path() -> Path:
    raw = (os.getenv(LOG_PATH_ENV) or "").strip()
    return Path(raw) if raw else Path.cwd() / DEFAULT_RELATIVE


class JsonlShadowSink:
    """Append one JSON object per line. Never raises."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or shadow_log_path()
        self._lock = threading.Lock()
        self.written = 0
        self.dropped = 0

    def record(self, observation: Any) -> None:
        try:
            line = json.dumps(observation, ensure_ascii=False, default=str)
        except Exception:  # noqa: BLE001 - unserialisable telemetry is dropped
            self.dropped += 1
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock, self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
            self.written += 1
        except Exception:  # noqa: BLE001 - telemetry may be dropped, never raised
            self.dropped += 1


_SHARED: Any = None
_SHARED_LOCK = threading.Lock()


def shadow_telemetry() -> Any:
    """The one shadow telemetry instance for this process.

    ``BestEffortTelemetry`` starts a dedicated flusher thread, so a per-service
    instance would multiply threads whenever a service is constructed more than once.
    The instance is shared across phases and closed at interpreter exit. The sink stays
    best-effort: a record can still be dropped and must never be assumed persisted
    from ``submitted=True`` alone.
    """
    global _SHARED
    with _SHARED_LOCK:
        if _SHARED is None:
            from src.application.shadow_isolation import BestEffortTelemetry

            _SHARED = BestEffortTelemetry(JsonlShadowSink())
            atexit.register(close_shadow_telemetry)
        return _SHARED


def close_shadow_telemetry() -> None:
    """Stop the shared flusher thread. Idempotent; safe at interpreter exit."""
    global _SHARED
    with _SHARED_LOCK:
        if _SHARED is not None:
            _SHARED.close()
            _SHARED = None
