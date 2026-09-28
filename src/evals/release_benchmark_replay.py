"""Opt-in frozen-source replay for release benchmark pilots.

Only text/HTML snapshots can enter the current WebLookupService read protocol.
Binary visual sources remain byte-verifiable candidates for a later reader pilot.
"""

from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path
import socket
import sqlite3
from tempfile import TemporaryDirectory
from typing import Any, Iterator
from unittest.mock import patch

from src.application.web_lookup_service import WebLookupService
from src.evals.release_benchmark_registry import ReleaseCase, ReleaseSource
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.web_lookup_repository import WebLookupRepository


class _PilotDatabase(RuntimeDatabase):
    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.connections: list[sqlite3.Connection] = []

    def connect(self) -> sqlite3.Connection:
        connection = super().connect()
        self.connections.append(connection)
        return connection

    def close_all(self) -> None:
        for connection in self.connections:
            connection.close()
        self.connections.clear()


class _VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignored = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "nav", "header", "footer"}:
            self.ignored += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "nav", "header", "footer"}:
            self.ignored = max(0, self.ignored - 1)

    def handle_data(self, data: str) -> None:
        if not self.ignored and data.strip():
            self.parts.append(data.strip())


def _verified_bytes(source: ReleaseSource, root: Path) -> bytes:
    if source.snapshot_path is None or source.sha256 is None:
        raise ValueError("frozen replay requires a byte-bound source")
    base = root.resolve()
    allowed = (base / "tests/fixtures/release_benchmark/sources").resolve()
    path = (base / source.snapshot_path).resolve()
    if not path.is_relative_to(allowed) or not path.is_file():
        raise ValueError("frozen source path escapes snapshot root")
    data = path.read_bytes()
    if sha256(data).hexdigest() != source.sha256:
        raise ValueError("frozen source byte digest drift")
    return data


class FrozenTextGateway:
    """Allowlist search and read against one frozen text case's snapshots."""

    def __init__(self, case: ReleaseCase, root: Path) -> None:
        if case.mode != "frozen" or case.modality != "text":
            raise ValueError("frozen text gateway accepts only frozen text cases")
        self.case = case
        self.root = root
        self.sources = {source.locator: source for source in case.sources}
        if len(self.sources) != len(case.sources):
            raise ValueError("duplicate frozen source locator")
        for source in case.sources:
            if Path(source.snapshot_path or "").suffix.lower() not in {".html", ".htm", ".txt"}:
                raise ValueError("binary source needs a modality-specific reader")
            _verified_bytes(source, root)

    def search(self, query: str, *, max_items: int = 10) -> list[dict[str, Any]]:
        if query != self.case.question or not 1 <= max_items <= 20:
            raise ValueError("frozen replay query or search budget mismatch")
        return [
            {"title": source.source_id, "url": source.locator,
             "source": source.source_id, "search_excerpt": self.case.question}
            for source in self.case.sources[:max_items]
        ]

    def read(self, url: str, *, max_chars: int = 6000) -> dict[str, Any]:
        if url not in self.sources or max_chars < 1:
            raise ValueError("frozen replay read is outside the case allowlist")
        source = self.sources[url]
        data = _verified_bytes(source, self.root)
        decoded = data.decode("utf-8", errors="strict")
        if Path(source.snapshot_path or "").suffix.lower() in {".html", ".htm"}:
            parser = _VisibleText()
            parser.feed(decoded)
            content = " ".join(parser.parts)
        else:
            content = decoded
        if not content.strip():
            raise ValueError("frozen text source has no readable content")
        return {"ok": True, "url": url, "title": source.source_id,
                "content": content[:max_chars], "source_sha256": source.sha256}

    def warnings(self) -> list[dict[str, str]]:
        return []


@contextmanager
def block_python_network() -> Iterator[None]:
    """Deny Python socket connects during the opt-in pilot execution."""

    def denied(*args: object, **kwargs: object) -> None:
        raise RuntimeError("network disabled for frozen replay")

    with (patch.object(socket.socket, "connect", denied),
          patch.object(socket.socket, "connect_ex", denied),
          patch.object(socket, "create_connection", denied)):
        yield


def run_frozen_text_pilot(case: ReleaseCase, root: Path) -> dict[str, Any]:
    """Execute the real WebLookupService with a source-bound offline gateway."""

    gateway = FrozenTextGateway(case, root)
    with TemporaryDirectory(prefix="release-frozen-") as temporary:
        database = _PilotDatabase(Path(temporary) / "runtime.db")
        service = WebLookupService(
            WebLookupRepository(database),
            gateway,
        )
        try:
            with block_python_network():
                run = service.lookup(case.question, max_items=len(case.sources))
        finally:
            database.close_all()
    return {
        "schema_version": "release-benchmark-frozen-text-pilot-v1",
        "case_id": case.case_id,
        "case_content_sha256": case.content_sha256,
        "run_id": run.id,
        "run_status": run.status,
        "provider_status": run.provider_status,
        "stop_reason": run.stop_reason,
        "network_guard": "python_socket_connect_blocked",
        "source_reads": [
            {"source_id": (record.get("assessment") or {}).get("source_id"),
             "locator": (record.get("item") or {}).get("url"),
             "state": (record.get("read") or {}).get("status"),
             "source_sha256": (record.get("read") or {}).get("source_sha256")}
            for record in run.selected_sources
        ],
        "release_gate": "NO_GO",
        "qualification": "diagnostic_text_pilot_only",
    }
