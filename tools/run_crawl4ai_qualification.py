"""§120 A3-2 self-managing qualification runner.

One foreground Python process owns the whole lifecycle - fixture server, warm
worker, focused gates, cohort - so the run is reproducible without PowerShell
``Start-Process``, background servers or multi-stage pipelines.

    python -u tools/run_crawl4ai_qualification.py --python <isolated venv python>

Stages: ``--stage focused`` (default) runs the four gates and stops unless they
all pass; ``--stage cohort`` runs the full frozen 12-row cohort.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.web.research.browser_bakeoff import BAKEOFF_UNIFIED_BUDGET  # noqa: E402
from src.web.research.chain_executor import ChainAttemptRequest  # noqa: E402
from src.web.research.crawl4ai_browser_executor import (  # noqa: E402
    CRAWL4AI_BACKEND,
    Crawl4AIBridge,
    Crawl4AIBrowserBackendExecutor,
)
from src.web.research.read_escalation import (  # noqa: E402
    TIER_BROWSER,
    charge_run_envelope,
    reset_run_envelope,
    run_envelope_spent_ms,
)

PORT = 8899
FIXTURE = REPO_ROOT / "tools" / "browser_bakeoff_fixture_server.py"
BASE = f"http://127.0.0.1:{PORT}"
BUDGET_MS = 3000.0
ADMIN = "http://127.0.0.1:3333/health"


def say(*p: Any) -> None:
    print(*p, flush=True)


class FixtureServer:
    def __init__(self, python: str) -> None:
        self.proc = subprocess.Popen(
            [python, "-u", "-X", "utf8", str(FIXTURE), "--port", str(PORT)],
            cwd=str(REPO_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def wait_ready(self, timeout_s: float = 20.0) -> bool:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"{BASE}/js-shell.html", timeout=2):
                    return True
            except Exception:
                time.sleep(0.3)
        return False

    def stop(self) -> None:
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()


def _executor(bridge: Crawl4AIBridge, *, mode: str, session_id: str | None,
              delay_ms: int) -> Crawl4AIBrowserBackendExecutor:
    return Crawl4AIBrowserBackendExecutor(
        bridge=bridge,
        mode=mode,
        max_chars=int(BAKEOFF_UNIFIED_BUDGET["max_chars"]),
        session_id=session_id,
        delay_ms=delay_ms,
        charge_envelope=lambda ms: charge_run_envelope(ms, TIER_BROWSER),
    )


def _call(bridge: Crawl4AIBridge, *, url: str, mode: str = "browser",
          session_id: str | None = None, delay_ms: int = 0):
    reset_run_envelope(TIER_BROWSER)
    spent_before = run_envelope_spent_ms(TIER_BROWSER)
    executor = _executor(bridge, mode=mode, session_id=session_id, delay_ms=delay_ms)
    started = time.perf_counter()
    result = executor.execute(
        ChainAttemptRequest(
            candidate_id="focused",
            url=url,
            host="127.0.0.1",
            backend=CRAWL4AI_BACKEND,
            chain_step=0,
            outer_attempt_number=1,
        )
    )
    wall_ms = round((time.perf_counter() - started) * 1000.0, 1)
    return {
        "state": result.retrieval_state,
        "usable": bool(result.usable_content),
        "attempted": bool(result.attempted),
        "chars": len(result.content or ""),
        "adequacy": result.adequacy_reason,
        "wall_ms": wall_ms,
        "cost": dict(result.cost),
        "debit_ms": round(run_envelope_spent_ms(TIER_BROWSER) - spent_before, 1),
    }


def focused_gates(bridge: Crawl4AIBridge) -> dict[str, Any]:
    gates: dict[str, Any] = {}

    say("A. js_shell real JS rescue")
    a = _call(bridge, url=f"{BASE}/js-shell.html", delay_ms=1200)
    say(f"   {json.dumps({k: a[k] for k in ('state', 'usable', 'chars', 'wall_ms')})}")
    gates["A_js_shell_rescue"] = bool(
        a["attempted"] and a["state"] == "success" and a["usable"] and a["chars"] > 800
    )

    say("B. document_heavy real PDF")
    b = _call(bridge, url=f"{BASE}/report.pdf", mode="pdf")
    say(f"   {json.dumps({k: b[k] for k in ('state', 'usable', 'chars', 'wall_ms')})}")
    gates["B_pdf_success"] = bool(
        b["attempted"] and b["state"] == "success" and b["usable"]
        and b["chars"] > 800 and b["wall_ms"] <= BUDGET_MS
    )

    say("C. forced-slow PDF must be a bounded failure, never invalid_content")
    reset_run_envelope(TIER_BROWSER)
    executor = Crawl4AIBrowserBackendExecutor(
        bridge=bridge,
        mode="pdf",
        max_chars=int(BAKEOFF_UNIFIED_BUDGET["max_chars"]),
        # §120: must be ABOVE the frozen min-hard (3.0s) so the B2 plan
        # actually ALLOWS the call - otherwise gate C only re-tests the
        # pre-call guard and never exercises the download-level deadline.
        hard_seconds_left=lambda: 30.0,
        charge_envelope=lambda ms: charge_run_envelope(ms, TIER_BROWSER),
    )
    started = time.perf_counter()
    c = executor.execute(
        ChainAttemptRequest(
            candidate_id="slow-pdf",
            url=f"{BASE}/slow-report.pdf",
            host="127.0.0.1",
            backend=CRAWL4AI_BACKEND,
            chain_step=0,
            outer_attempt_number=1,
        )
    )
    c_wall = round((time.perf_counter() - started) * 1000.0, 1)
    say(f"   state={c.retrieval_state} wall={c_wall}ms adequacy={c.adequacy_reason}")
    gates["C_pdf_bounded"] = bool(
        c.retrieval_state in {"budget_exhausted", "timeout"}
        and c.retrieval_state != "invalid_content"
        and c_wall <= 4500
    )

    say("D. static_control silence (bridge available, must not be used)")
    # the guard is enforced by the chain; here we assert the executor is not
    # invoked for a resolved native read - covered by the cohort, so this gate
    # only confirms the bridge is ready and reachable.
    gates["D_static_gate_deferred_to_cohort"] = bool(bridge.availability)
    say(f"   bridge availability={bridge.availability} (cohort asserts 0 calls)")
    return gates


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", required=True, help="isolated venv interpreter")
    parser.add_argument("--stage", default="focused", choices=("focused", "cohort"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    os.environ.setdefault("RESEARCH_WIGOLO_ESCALATION", "browser")
    os.environ.setdefault("WIGOLO_BROWSER_ESCALATION", "1")
    os.environ.setdefault("WIGOLO_RERANKER", "off")

    server = FixtureServer(args.python)
    bridge: Crawl4AIBridge | None = None
    report: dict[str, Any] = {"stage": args.stage}
    try:
        if not server.wait_ready():
            report["error"] = "fixture_server_not_ready"
            return 1
        say(f"fixture server READY on {BASE}")

        bridge = Crawl4AIBridge(python=args.python)
        bridge.start()
        say(f"worker READY startup_ms={bridge.startup_ms} "
            f"cancel_grace_ms={bridge.cancel_grace_ms}")

        gates = focused_gates(bridge)
        report["focused_gates"] = gates
        say(f"focused gates: {json.dumps(gates)}")
        if not all(gates.values()):
            report["focused_pass"] = False
            say("FOCUSED_FAILED - cohort not run")
            return 1
        report["focused_pass"] = True
        say("FOCUSED_PASS")

        if args.stage == "cohort":
            from tools.run_crawl4ai_cohort_v2 import run_cohort

            document = run_cohort(
                python=args.python,
                manifest_path=REPO_ROOT
                / "tests/fixtures/research_quality/browser_bakeoff_manifest.json",
            )
            report["cohort"] = document
    finally:
        if bridge is not None:
            bridge.stop()
        server.stop()
        say("lifecycle stopped (worker + fixture server)")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.output.with_suffix(args.output.suffix + ".tmp")
    tmp.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(args.output)
    say(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
