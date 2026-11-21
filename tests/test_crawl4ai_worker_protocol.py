"""Portable offline protocol tests for the active isolated Crawl4AI worker.

The former §135/§142 probes depended on one developer's temporary Windows venv
and were skipped on Linux CI. These tests exercise the actual worker/bridge
process protocol without installing Crawl4AI or contacting the network.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

from src.web.research.crawl4ai_browser_executor import Crawl4AIBridge
from src.web.research.crawl4ai_worker import PdfDownloadDeadline, _bounded_pdf_fetch

FAKE_CRAWL4AI = """
import asyncio
from types import SimpleNamespace

class CacheMode:
    BYPASS = "BYPASS"

class CrawlerRunConfig:
    def __init__(self, **kwargs):
        self.options = kwargs

class AsyncWebCrawler:
    async def start(self):
        return None

    async def close(self):
        return None

    async def arun(self, *, url, config):
        await asyncio.sleep(4)
        return SimpleNamespace(
            success=True, markdown="late answer", status_code=200,
            error_message="",
        )
"""


@pytest.fixture
def fake_crawl4ai(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> str:
    (tmp_path / "crawl4ai.py").write_text(FAKE_CRAWL4AI, encoding="utf-8")
    previous = os.environ.get("PYTHONPATH", "")
    monkeypatch.setenv(
        "PYTHONPATH", str(tmp_path) + (os.pathsep + previous if previous else "")
    )
    return sys.executable


def test_worker_shutdown_emits_bye_before_bridge_closes(
    fake_crawl4ai: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    bridge = Crawl4AIBridge(python=fake_crawl4ai)
    bridge.start(timeout_ms=10000)
    proc = bridge._proc
    observed: list[dict] = []
    original_next = bridge._next

    def capture_next(timeout_ms: float) -> dict:
        message = original_next(timeout_ms)
        observed.append(message)
        return message

    monkeypatch.setattr(bridge, "_next", capture_next)
    try:
        bridge.stop()
    finally:
        bridge.stop()
    assert observed and observed[0].get("event") == "BYE"
    assert proc is not None
    proc.wait(timeout=3)


def test_nondefault_request_deadline_reaches_worker_and_cancels_provider(
    fake_crawl4ai: str,
) -> None:
    bridge = Crawl4AIBridge(python=fake_crawl4ai)
    bridge.start(timeout_ms=10000)
    try:
        result = bridge.request(
            timeout_ms=350,
            url="https://example.invalid/slow",
            mode="browser",
            max_chars=2000,
        )
        assert result["deadline_hit"] is True
        assert result["cancellation"]["requested_deadline_ms"] == 350
        assert result["cancellation"]["provider_cancelled"] is True
        assert result["request_id"] == "r1"
    finally:
        proc = bridge._proc
        bridge.stop()
        if proc is not None:
            proc.wait(timeout=3)


def test_pdf_download_uses_absolute_deadline_without_real_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SlowResponse:
        closed = False

        def read1(self, _size: int) -> bytes:
            time.sleep(0.075)
            return b"partial-pdf" * 32

        def close(self) -> None:
            self.closed = True

    response = SlowResponse()
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda *_args, **_kwargs: response
    )
    started = time.monotonic()
    with pytest.raises(PdfDownloadDeadline, match="pdf_download_deadline"):
        _bounded_pdf_fetch("https://example.invalid/slow.pdf", timeout_ms=500)
    assert time.monotonic() - started < 2
    assert response.closed is True
