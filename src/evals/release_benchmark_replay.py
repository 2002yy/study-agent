"""Opt-in frozen-source replay for release benchmark pilots.

Text/HTML and PDF text snapshots can enter the WebLookupService read protocol.
Visual sources use the existing multimodal pipeline, defaulting to unavailable
without an explicitly injected vision adapter.
"""

from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
from tempfile import TemporaryDirectory
from typing import Any, Iterator
from unittest.mock import patch

from pypdf import PdfReader

from src.application.web_lookup_service import WebLookupService
from src.evals.release_benchmark_registry import ReleaseCase, ReleaseSource
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.web_lookup_repository import WebLookupRepository
from src.web.research.multimodal_reader import (
    VisionAdapter,
    VisualImage,
    VisualReadBudget,
    read_visual_candidates,
)


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


class FrozenPdfGateway(FrozenTextGateway):
    """Read selected pages of a byte-bound PDF without a network request."""

    def __init__(self, case: ReleaseCase, root: Path) -> None:
        if case.mode != "frozen" or case.modality not in {"pdf", "mixed"}:
            raise ValueError("frozen PDF gateway accepts only frozen PDF or mixed cases")
        self.case = case
        self.root = root
        self.sources = {source.locator: source for source in case.sources}
        if len(self.sources) != len(case.sources):
            raise ValueError("duplicate frozen source locator")
        for source in case.sources:
            if Path(source.snapshot_path or "").suffix.lower() != ".pdf":
                raise ValueError("frozen PDF case requires PDF snapshots")
            self._page_text(source)

    def _page_text(self, source: ReleaseSource) -> str:
        data = _verified_bytes(source, self.root)
        reader = PdfReader(BytesIO(data))
        page_number = source.page or 1
        if page_number > len(reader.pages):
            raise ValueError("frozen PDF page is outside the snapshot")
        content = reader.pages[page_number - 1].extract_text() or ""
        if not content.strip():
            raise ValueError("frozen PDF page has no extractable text")
        return content

    def read(self, url: str, *, max_chars: int = 6000) -> dict[str, Any]:
        if url not in self.sources or max_chars < 1:
            raise ValueError("frozen replay read is outside the case allowlist")
        source = self.sources[url]
        return {"ok": True, "url": url, "title": source.source_id,
                "content": self._page_text(source)[:max_chars],
                "page": source.page or 1, "region": source.region,
                "source_sha256": source.sha256}


@contextmanager
def block_python_network() -> Iterator[None]:
    """Deny Python socket connects during the opt-in pilot execution."""

    def denied(*args: object, **kwargs: object) -> None:
        raise RuntimeError("network disabled for frozen replay")

    with (patch.object(socket.socket, "connect", denied),
          patch.object(socket.socket, "connect_ex", denied),
          patch.object(socket, "create_connection", denied)):
        yield


def _run_gateway_pilot(case: ReleaseCase, gateway: FrozenTextGateway) -> dict[str, Any]:
    """Execute the real WebLookupService with a source-bound offline gateway."""

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
        "schema_version": (
            "release-benchmark-frozen-text-pilot-v1" if case.modality == "text"
            else "release-benchmark-frozen-pdf-pilot-v1"
        ),
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
             "source_sha256": (record.get("read") or {}).get("source_sha256"),
             "page": (record.get("read") or {}).get("page"),
             "region": (record.get("read") or {}).get("region")}
            for record in run.selected_sources
        ],
        "release_gate": "NO_GO",
        "qualification": (
            "diagnostic_text_pilot_only" if case.modality == "text"
            else "diagnostic_pdf_text_pilot_only"
        ),
    }


def run_frozen_text_pilot(case: ReleaseCase, root: Path) -> dict[str, Any]:
    return _run_gateway_pilot(case, FrozenTextGateway(case, root))


def run_frozen_pdf_pilot(case: ReleaseCase, root: Path) -> dict[str, Any]:
    if case.modality != "pdf":
        raise ValueError("PDF text pilot requires a PDF case")
    return _run_gateway_pilot(case, FrozenPdfGateway(case, root))


def run_frozen_visual_pilot(
    case: ReleaseCase, root: Path, *, adapter: VisionAdapter | None = None,
) -> dict[str, Any]:
    """Run actual visual escalation on byte-verified raster or PDF pages."""

    if case.mode != "frozen" or case.modality not in {"image", "chart", "mixed"}:
        raise ValueError("visual pilot requires a frozen visual case")
    outcomes: list[dict[str, Any]] = []
    for source in case.sources:
        data = _verified_bytes(source, root)
        suffix = Path(source.snapshot_path or "").suffix.lower()
        if suffix not in {".pdf", ".gif", ".png", ".jpg", ".jpeg"}:
            raise ValueError("unsupported frozen visual snapshot")
        with TemporaryDirectory(prefix="release-visual-") as temporary:
            local_path = Path(temporary) / ("source" + suffix)
            local_path.write_bytes(data)
            renderer = "original_raster"
            if suffix == ".pdf":
                executable = shutil.which("pdftoppm")
                if executable is None:
                    outcomes.append({"source_id": source.source_id,
                                     "locator": source.locator,
                                     "source_sha256": source.sha256,
                                     "status": "unavailable",
                                     "reason": "pdf_visual_page_renderer_not_available",
                                     "page": source.page, "region": source.region})
                    continue
                page = source.page or 1
                if page > len(PdfReader(BytesIO(data)).pages):
                    raise ValueError("frozen visual PDF page is outside the snapshot")
                prefix = Path(temporary) / "rendered"
                completed = subprocess.run(
                    [executable, "-f", str(page), "-l", str(page),
                     "-singlefile", "-scale-to", "1600", "-png",
                     str(local_path), str(prefix)],
                    capture_output=True, timeout=30, check=False,
                )
                local_path = prefix.with_suffix(".png")
                if completed.returncode != 0 or not local_path.is_file():
                    outcomes.append({"source_id": source.source_id,
                                     "locator": source.locator,
                                     "source_sha256": source.sha256,
                                     "status": "unavailable",
                                     "reason": "pdf_visual_page_render_failed",
                                     "page": source.page, "region": source.region})
                    continue
                renderer = "pdftoppm"
            image = VisualImage(
                image_id=source.source_id,
                kind="diagram" if case.modality == "image" else "chart"
                if case.modality == "chart" else "pdf_figure",
                source=source.locator,
                page=source.page,
                region=source.region or "",
                triggers=("user_requested",),
                carries_required_evidence=True,
                local_path=str(local_path),
            )
            with block_python_network():
                result = read_visual_candidates(
                    images=[image], required_units=case.required_units,
                    adapter=adapter, budget=VisualReadBudget(max_vision_calls=1),
                )
            for item in result.outcomes:
                outcomes.append({**item.to_dict(), "source_id": source.source_id,
                                 "locator": source.locator,
                                 "source_sha256": source.sha256,
                                 "materialized_sha256": sha256(local_path.read_bytes()).hexdigest(),
                                 "page": source.page, "region": source.region,
                                 "renderer": renderer})
    return {
        "schema_version": "release-benchmark-frozen-visual-pilot-v1",
        "case_id": case.case_id,
        "case_content_sha256": case.content_sha256,
        "source_outcomes": outcomes,
        "network_guard": "python_socket_connect_blocked",
        "release_gate": "NO_GO",
        "qualification": "diagnostic_visual_pipeline_only",
    }


def run_frozen_mixed_pilot(case: ReleaseCase, root: Path) -> dict[str, Any]:
    if case.modality != "mixed":
        raise ValueError("mixed pilot requires a mixed case")
    return {
        "schema_version": "release-benchmark-frozen-mixed-pilot-v1",
        "case_id": case.case_id,
        "text_read": _run_gateway_pilot(case, FrozenPdfGateway(case, root)),
        "visual_read": run_frozen_visual_pilot(case, root),
        "release_gate": "NO_GO",
        "qualification": "diagnostic_partial_mixed_pilot_only",
    }
