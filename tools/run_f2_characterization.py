# -*- coding: utf-8 -*-
"""§143-A F2_CHARACTERIZATION: warm steady-state ledger.

Protocol (frozen, docs/PROJECT_STATUS.md §143.8-143.15):
  fixture server -> bridge/worker -> 1 disposable global warm-up
  -> per-fixture discarded warm-up -> N measured repeats in INTERLEAVED order

Measures only at harness call boundaries. NO production instrumentation changes.
Raw ledger is the artifact; the aggregate table is a view.

Usage:
  python tools/run_f2_characterization.py --repeats 20 --output docs/research_quality/F2_WARM_LEDGER.json
  python tools/run_f2_characterization.py --repeats 3 --only simple_static   # §143-A2 validation
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

DEFAULT_ISOLATED = Path(
    r"C:\Users\Zhang\AppData\Local\Temp\opencode\a3-crawl4ai-venv\Scripts\python.exe"
)
FIXTURE = REPO_ROOT / "tools" / "browser_bakeoff_fixture_server.py"
PORT = 8791

#: §143.12 frozen mapping. `mode` is execution config for the capability the
#: fixture already demands - never a second routing authority.
CATEGORIES: tuple[tuple[str, str, str], ...] = (
    ("simple_static", "/structured-spec.html", "browser"),
    ("technical_docs", "/code-docs.html", "browser"),
    ("js_heavy", "/spa-delayed.html", "browser"),
    ("difficult_html", "/document-mixed.html", "browser"),
    ("session_sensitive", "/session-gated.html", "browser"),
    ("selected_pdf", "/report.pdf", "pdf"),
)

REQUEST_TIMEOUT_MS = 20000


def _start_fixture(port: int) -> subprocess.Popen:
    proc = subprocess.Popen(
        [sys.executable, "-u", "-X", "utf8", str(FIXTURE), "--port", str(port)],
        cwd=str(REPO_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"{base}/code-docs.html", timeout=2).read(16)
            return proc
        except Exception:
            time.sleep(0.3)
    raise SystemExit("fixture server did not start")


def _measure(bridge, url: str, mode: str, session_id: str | None) -> dict:
    """One measured run. Timing is taken at the harness call boundary only."""

    payload: dict = {"url": url, "mode": mode, "max_chars": 20000}
    if session_id:
        payload["session_id"] = session_id

    t0 = time.perf_counter()
    reply = bridge.request(timeout_ms=REQUEST_TIMEOUT_MS, **payload)
    total_wall_ms = round((time.perf_counter() - t0) * 1000.0, 1)

    queue_wait_ms = reply.get("queue_wait_ms")
    content = reply.get("content") or ""
    # worker-side handle duration: a DISTINCT observable, NOT "reader_execution_ms"
    # (it wraps task creation + wait_for + invalidate; §143.8).
    worker_handle_ms = (reply.get("cancellation") or {}).get("actual_return_ms")

    # Residual accounting (§143.9): components may overlap or leak; the residual
    # IS the result. normalization/provenance are not separable at this boundary
    # for the raw provider call, so they are reported as null here and only the
    # clean sub-component (queue_wait) is subtracted.
    unattributed_ms = (
        None if queue_wait_ms is None else round(total_wall_ms - float(queue_wait_ms), 1)
    )

    return {
        "total_wall_ms": total_wall_ms,
        "queue_wait_ms": queue_wait_ms,
        "worker_handle_ms": worker_handle_ms,
        "reader_execution_ms": None,  # §143.8: not cleanly separable at this boundary
        "normalization_ms": None,
        "provenance_ms": None,
        "unattributed_ms": unattributed_ms,
        "content_units_recovered": len(content),
        "deadline_ms": reply.get("cancellation", {}).get("requested_deadline_ms"),
        "fallback_used": reply.get("fallback_used"),
        "provider_success": bool(reply.get("provider_success")),
        "deadline_hit": reply.get("deadline_hit"),
        "error_message": reply.get("error_message") or "",
    }


def _aggregate(runs: list[dict]) -> dict:
    def col(key: str) -> list[float]:
        return [r[key] for r in runs if isinstance(r.get(key), (int, float))]

    def pct(vals: list[float], p: float) -> float | None:
        if not vals:
            return None
        s = sorted(vals)
        idx = min(len(s) - 1, max(0, int(round((p / 100.0) * (len(s) - 1)))))
        return round(s[idx], 1)

    totals = col("total_wall_ms")
    qw = col("queue_wait_ms")
    p50_total = statistics.median(totals) if totals else None
    out = {
        "n_runs": len(runs),
        "n_success": sum(1 for r in runs if r.get("provider_success")),
        "p50_total": round(p50_total, 1) if p50_total is not None else None,
        "p95_total": pct(totals, 95),
        "max_total": round(max(totals), 1) if totals else None,
        "p50_queue_wait": statistics.median(qw) if qw else None,
    }
    if p50_total:
        out["queue_wait_share"] = round((statistics.median(qw) / p50_total), 4) if qw else None
        med_un = statistics.median(col("unattributed_ms"))
        out["unattributed_share"] = round(med_un / p50_total, 4)
        out["accounted_share"] = round(1.0 - med_un / p50_total, 4)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=20)
    ap.add_argument("--python", default=str(DEFAULT_ISOLATED))
    ap.add_argument("--output", default="")
    ap.add_argument("--only", default="")
    ap.add_argument("--seed", type=int, default=143)
    args = ap.parse_args()

    cats = [c for c in CATEGORIES if not args.only or c[0] == args.only]
    if not cats:
        raise SystemExit(f"unknown category: {args.only}")

    server = _start_fixture(PORT)
    base = f"http://127.0.0.1:{PORT}"
    from src.web.research.crawl4ai_browser_executor import Crawl4AIBridge

    bridge = Crawl4AIBridge(python=args.python)
    bridge.start()
    raw: list[dict] = []
    try:
        # §143.10 step 1: disposable global warm-up (no fixture in particular)
        _measure(bridge, f"{base}/code-docs.html", "browser", None)
        # §143.10 step 2: per-fixture discarded warm-up
        for name, path, mode in cats:
            _measure(bridge, f"{base}{path}", mode, None)
        # §143.10 step 3: measured repeats in INTERLEAVED order
        order = [c for c in cats for _ in range(args.repeats)]
        random.Random(args.seed).shuffle(order)
        for i, (name, path, mode) in enumerate(order):
            session_id = "f2sess" if name == "session_sensitive" else None
            row = _measure(bridge, f"{base}{path}", mode, session_id)
            row.update({"category": name, "fixture": path, "run_index": i, "warm": True})
            raw.append(row)
            print(
                f"[{i + 1}/{len(order)}] {name:18s} total={row['total_wall_ms']:8.1f}ms "
                f"queue={row['queue_wait_ms']} ok={row['provider_success']} "
                f"chars={row['content_units_recovered']}"
            )
    finally:
        bridge.stop()
        server.terminate()
        try:
            server.wait(timeout=5)
        except Exception:
            server.kill()

    aggregates = {c[0]: _aggregate([r for r in raw if r["category"] == c[0]]) for c in cats}
    print("\n=== aggregate (view over raw) ===")
    print(json.dumps(aggregates, indent=2, ensure_ascii=False))

    if args.output:
        doc = {
            "schema": "f2-warm-ledger-v1",
            "repeats_per_category": args.repeats,
            "seed": args.seed,
            "raw": raw,
            "aggregate": aggregates,
        }
        out = Path(args.output)
        if not out.is_absolute():
            out = REPO_ROOT / out
        out.write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
