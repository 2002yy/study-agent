"""§135.5 FG2 timeout-propagation regression guard.

Locks the §135 root cause: ``timeout_ms`` is a keyword-only parameter of the
bridge's ``request()`` and was never placed in the payload, so the worker
silently fell back to its 30s default.

Two invariants, deliberately loose where wall-clock is involved:

1. an explicit request timeout reaches the worker's timeout authority
   (checked with a NON-default value, so 30000-vs-30000 cannot pass);
2. the PDF primitive's initial remaining budget is derived from that same
   request timeout, not from the default.

The test needs the isolated Crawl4AI venv and the local fixture server; it skips
cleanly when either is unavailable.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
ISOLATED = Path(
    r"C:\Users\Zhang\AppData\Local\Temp\opencode\a3-crawl4ai-venv\Scripts\python.exe"
)
FIXTURE = REPO_ROOT / "tools" / "browser_bakeoff_fixture_server.py"
PORT = 8899
BASE = f"http://127.0.0.1:{PORT}"

#: A deliberately non-default request timeout (the worker default is 30000).
REQUESTED_MS = 1379
SLOP_MS = 1500


def _available() -> bool:
    return ISOLATED.exists() and FIXTURE.exists()


pytestmark = pytest.mark.skipif(
    not _available(), reason="isolated Crawl4AI venv / fixture server unavailable"
)


@pytest.fixture()
def bridge_and_server():
    sys.path.insert(0, str(REPO_ROOT))
    server = subprocess.Popen(
        [sys.executable, "-u", "-X", "utf8", str(FIXTURE), "--port", str(PORT)],
        cwd=str(REPO_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"{BASE}/report.pdf", timeout=2).read(16)
            break
        except Exception:
            time.sleep(0.3)

    os.environ["CRAWL4AI_PDF_DIAG"] = "1"
    from src.web.research.crawl4ai_browser_executor import Crawl4AIBridge

    bridge = Crawl4AIBridge(python=str(ISOLATED))
    bridge.start()
    try:
        yield bridge
    finally:
        bridge.stop()
        server.terminate()
        try:
            server.wait(timeout=5)
        except Exception:
            server.kill()


def test_explicit_request_timeout_reaches_the_worker(bridge_and_server) -> None:
    """A non-default explicit timeout must not be replaced by the 30s default."""

    bridge = bridge_and_server
    reply = bridge.request(
        timeout_ms=REQUESTED_MS,
        url=f"{BASE}/slow-report.pdf",
        mode="pdf",
        max_chars=20000,
    )
    cancellation = reply.get("cancellation") or {}
    assert cancellation, "a deadline-hit reply must report its cancellation record"
    assert cancellation["requested_deadline_ms"] == REQUESTED_MS, (
        "the request's explicit timeout must reach the worker's timeout authority"
    )
    assert reply.get("deadline_hit") is True, "a 1.4s budget cannot finish a 6.3s transfer"


def test_pdf_primitive_budget_is_derived_from_the_request(bridge_and_server) -> None:
    """The PDF path must consume the request budget, not the 30s default.

    Observable proof that needs no stderr parsing: a 1379ms budget can only
    return quickly. If the primitive had used the 30000ms default it would have
    downloaded the whole 6.3s trickle.
    """

    bridge = bridge_and_server
    started = time.monotonic()
    bridge.request(
        timeout_ms=REQUESTED_MS,
        url=f"{BASE}/slow-report.pdf",
        mode="pdf",
        max_chars=20000,
    )
    wall_ms = (time.monotonic() - started) * 1000.0
    assert wall_ms <= REQUESTED_MS + SLOP_MS, (
        f"the PDF path took {wall_ms:.0f}ms for a {REQUESTED_MS}ms budget; "
        "that means it fell back to the 30000ms default"
    )


def test_worker_default_is_preserved_for_calls_without_a_timeout() -> None:
    """The 30s default stays available; it is only *not* allowed to override."""

    import inspect

    from src.web.research.crawl4ai_browser_executor import Crawl4AIBridge

    signature = inspect.signature(Crawl4AIBridge.request)
    assert signature.parameters["timeout_ms"].kind is inspect.Parameter.KEYWORD_ONLY
    source = Path(
        REPO_ROOT / "src" / "web" / "research" / "crawl4ai_browser_executor.py"
    ).read_text(encoding="utf-8")
    assert 'payload["timeout_ms"] = int(timeout_ms)' in source, (
        "the propagation line is the fix for §135; it must not be removed"
    )
