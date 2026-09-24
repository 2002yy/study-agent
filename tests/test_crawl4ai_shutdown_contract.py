"""§142-4 shutdown contract regression guard.

Locks the §142-4 root cause: ``Worker.close_all`` was referenced by the shutdown
path (in-loop and in ``finally``) but never defined, so a real ``shutdown`` op
raised ``AttributeError`` -> the worker exited rc=1 and **never emitted BYE**.

This is a *worker-level* test on purpose: the bridge's ``stop()`` swallows the
missing BYE and then terminates the process, which is exactly why the defect was
invisible to the rest of the suite. Nothing here asserts more than the shutdown
contract itself.

Skips cleanly when the isolated Crawl4AI venv is unavailable.
"""

from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
ISOLATED = Path(
    r"C:\Users\Zhang\AppData\Local\Temp\opencode\a3-crawl4ai-venv\Scripts\python.exe"
)
WORKER = REPO_ROOT / "src" / "web" / "research" / "crawl4ai_worker.py"


def _readline(proc: subprocess.Popen, timeout: float) -> str:
    box: dict[str, str] = {}

    def _r() -> None:
        box["line"] = proc.stdout.readline()  # type: ignore[union-attr]

    t = threading.Thread(target=_r, daemon=True)
    t.start()
    t.join(timeout)
    return box.get("line", "")


@pytest.mark.skipif(
    not ISOLATED.exists() or not WORKER.exists(),
    reason="isolated Crawl4AI venv / worker unavailable",
)
def test_real_worker_shutdown_emits_bye_and_exits_cleanly() -> None:
    """shutdown -> BYE, bounded, rc==0, and no AttributeError on stderr."""

    proc = subprocess.Popen(
        [str(ISOLATED), "-u", "-X", "utf8", str(WORKER)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        cwd=str(REPO_ROOT),
    )
    try:
        ready = _readline(proc, 60.0)
        assert '"event": "READY"' in ready, f"worker did not become ready: {ready!r}"

        proc.stdin.write(json.dumps({"op": "shutdown", "request_id": "bye1"}) + "\n")
        proc.stdin.flush()

        bye = _readline(proc, 20.0)
        assert '"event": "BYE"' in bye, f"shutdown did not emit BYE: {bye!r}"

        rc = proc.wait(timeout=20.0)
        assert rc == 0, f"clean shutdown must exit 0, got {rc}"

        stderr = proc.stderr.read() or ""  # type: ignore[union-attr]
        assert "close_all" not in stderr, f"shutdown raised on close_all:\n{stderr[-800:]}"
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
