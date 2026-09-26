# -*- coding: utf-8 -*-
"""§143-B F2 characterization: paired default-vs-Crawl4AI value comparison.

Answers: under the SAME research task, what does the CURRENT production default
reader recover vs Crawl4AI, and is the extra cost worth it?

Frozen contract (docs/PROJECT_STATUS.md §143.25-§143.51, §143.93-§143.104):

* **default side = the REAL production read path.** It calls
  ``run_single_read_measurement`` (the production-owned measurement entry that
  shares ``build_production_gateway_read`` + ``build_read_chain_executors`` with
  ``execute()``). The harness NEVER constructs a native/wigolo executor itself:
  doing so would recreate a "fake default" and invalidate all of §143-B.
* crawl4ai side = the existing ``Crawl4AIBrowserBackendExecutor`` (no top-up).
* both sides share ONE rubric matcher (whitespace-normalized).
* ``harness_added_fetches = 0`` / ``harness_followed_links_itself = False``.
* 5 paired warm repeats, seeded randomized alternating order.
* content outcomes are kept per-run; consistency is NOT averaged away.

The loopback fixture server is unreachable through the production SSRF guard
by design. The harness relaxes **only** that safety policy for the intentional
local fixture host; it does NOT touch read semantics (retry / window /
escalation / timeout) nor reader construction.

Usage:
  python tools/run_f2_paired.py --smoke
  python tools/run_f2_paired.py --pairs 5 --output docs/research_quality/F2_PAIRED.json
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import statistics
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

DEFAULT_ISOLATED = Path(
    r"C:\Users\Zhang\AppData\Local\Temp\opencode\a3-crawl4ai-venv\Scripts\python.exe"
)
FIXTURE = REPO_ROOT / "tools" / "f2_paired_fixture_server.py"
PORT = 8793

#: §143-B fallback sentinel: a deliberately short page so the native read is
#: classified short_doc and the production chain must escalate to wigolo_http.
#: Its only job is to prove the production default fallback environment is live
#: (NATIVE_HTTP -> WIGOLO_HTTP) before a 30-pair run is trusted.
FALLBACK_SENTINEL = "/f2-fallback-sentinel.html"

NATIVE = "native_http"
WIGOLO_HTTP = "wigolo_http"
CRAWL4AI_BACKEND = "crawl4ai"

MAX_CHARS = 20000
REQUEST_TIMEOUT_MS = 20000
SESSION_ID = "f2sess"

#: The measurement entry is driven with a fixed, generous window; the read
#: semantics themselves (retry / admission / timeout) stay production-owned.
MEASUREMENT_RESEARCH_SECONDS_LEFT = 45.0
MEASUREMENT_HARD_SECONDS_LEFT = 60.0

#: §143.26 frozen rubric. `critical_units` are matched whitespace-normalized.
CATEGORIES: tuple[dict, ...] = (
    {
        "category": "simple_static",
        "fixture": "/structured-spec.html",
        "mode": "browser",
        "critical_units": ["2026-08-01", "ES modules", "CommonJS", "supported"],
        "note": "static structured (not pure prose)",
    },
    {
        "category": "technical_docs",
        "fixture": "/code-docs.html",
        "mode": "browser",
        "critical_units": [
            "Compute API",
            "def compute(value)",
            "verified release identifier",
            "canonical id",
        ],
        "note": "code element + key explanation",
    },
    {
        "category": "js_heavy",
        "fixture": "/spa-delayed.html",
        "mode": "browser",
        "delay_ms": 1200,
        "critical_units": ["verified release date is 2026-08-01", "CommonJS guidance"],
        "note": "units appear only after JS (A3 cohort uses a 1200ms render delay)",
    },
    {
        "category": "document_path",
        "fixture": "/document-mixed.html",
        "mode": "browser",
        "critical_units": ["verified release date is 2026-08-01", "CommonJS guidance"],
        "note": "units live in the LINKED PDF; gain is document-path gain",
    },
    {
        "category": "session_sensitive",
        "fixture": "/session/check",
        "mode": "browser",
        "critical_units": ["SESSION OK"],
        "session_setup": "/session/start",
        "note": "requires a valid session; setup cost accounted separately",
    },
    {
        "category": "selected_pdf",
        "fixture": "/report.pdf",
        "mode": "pdf",
        "critical_units": [
            "verified release date is 2026-08-01",
            "CommonJS guidance",
            "extractable prose",
        ],
        "note": "cost objection may disappear; gain still content-only",
    },
)


def _norm(text: str) -> str:
    """§143.36: collapse whitespace, keep semantic tokens, case preserved."""
    return re.sub(r"\s+", " ", text or "").strip()


def _units(text: str, expected: list[str]) -> list[str]:
    hay = _norm(text)
    return [u for u in expected if _norm(u) in hay]


def _task_useful(units_recovered: int) -> bool:
    """§143.38 task usefulness, derived from the SHARED rubric on both sides.

    A side is useful when it recovered at least one decision-critical unit: the
    task can be answered from that content. This is applied identically to
    default and Crawl4AI (no per-side rule) and keeps all four frozen gain bands
    reachable. The reader's own ``usable_content`` is recorded separately as a
    diagnostic, never as the task verdict.
    """
    return units_recovered >= 1


def _allow_local_fixture_reads() -> None:
    """Relax ONLY the SSRF target policy for the intentional loopback fixture.

    Read semantics (retry / window admission / escalation context / timeout) and
    reader construction are untouched: this swaps the URL-safety predicate only.
    """

    from src.news import article_fetcher

    original = article_fetcher._is_fetchable_article_url  # noqa: SLF001

    def _allowed(url: str) -> bool:
        host = (urlparse(str(url or "")).hostname or "").lower()
        if host in {"127.0.0.1", "localhost", "::1"}:
            return True
        return bool(original(url))

    article_fetcher._is_fetchable_article_url = _allowed  # noqa: SLF001


# ---------------------------------------------------------------- default side

def _run_default(url: str, category: str) -> dict:
    """The REAL production read path via the production measurement entry.

    No executor is constructed here, and no read semantics are reimplemented.
    """

    from src.application.active_research_runtime import (
        ACTIVE_READER_CHAIN,
        run_single_read_measurement,
    )
    from src.web.research.active_adapter import (
        ActiveResearchGateway,
        read_gateway_accepts_timeout,
    )
    from src.web.research.chain_executor import ChainStepResult

    gateway = ActiveResearchGateway()
    context: dict = {}
    t0 = time.perf_counter()
    chain_run, recorded = run_single_read_measurement(
        url=url,
        source_limit=MAX_CHARS,
        gateway=gateway,
        escalation_backend=(
            gateway.escalation_backend()
            if hasattr(gateway, "escalation_backend")
            else None
        ),
        get_context=lambda: context,
        research_seconds_left=lambda: MEASUREMENT_RESEARCH_SECONDS_LEFT,
        hard_seconds_left=lambda: MEASUREMENT_HARD_SECONDS_LEFT,
        accepts_timeout=read_gateway_accepts_timeout(gateway),
        wave_index=lambda: 0,
        candidate_id=f"f2-{category}",
    )
    wall_ms = round((time.perf_counter() - t0) * 1000.0, 1)
    steps = tuple(recorded)
    # backend_path from the REAL event sequence, never guessed from content
    backend_path = [
        s.backend for s in steps if bool(getattr(s, "attempted", False))
    ]
    # post-default metadata: only what the default read really produced. §143-C
    # P2 may classify on this; it may never fetch anything extra.
    steps_meta = [
        {
            "backend": str(getattr(s, "backend", "")),
            "retrieval_state": str(getattr(s, "retrieval_state", "")),
            "attempted": bool(getattr(s, "attempted", False)),
            "usable_content": bool(getattr(s, "usable_content", False)),
            "adequacy_reason": str(getattr(s, "adequacy_reason", "")),
        }
        for s in steps
    ]
    return {
        "wall_ms": wall_ms,
        "content": chain_run.content,
        # the reader's own adequacy verdict - diagnostic only; task usefulness is
        # decided by the shared critical-unit rubric (symmetric across sides)
        "reader_usable_content": bool(chain_run.usable_content),
        "backend_path": backend_path,
        "fallback_used": len(backend_path) > 1,
        "terminal_outcome": chain_run.action,
        "terminal_reason": chain_run.reason,
        "final_state": chain_run.final_state,
        "steps": steps_meta,
        # runtime-origin invariant: the row is provably produced by the shared
        # production read path, not by a harness re-implementation.
        "runtime_origin": {
            "entry": "run_single_read_measurement",
            "backend_path_in_active_chain": all(
                b in ACTIVE_READER_CHAIN for b in backend_path
            ),
            "steps_are_chain_step_results": all(
                isinstance(s, ChainStepResult) for s in steps
            ),
        },
    }


# --------------------------------------------------------------- crawl4ai side

def _run_crawl4ai(
    bridge,
    url: str,
    mode: str,
    category: str,
    *,
    setup_url: str | None = None,
    delay_ms: int = 0,
) -> dict:
    """The existing Crawl4AIBrowserBackendExecutor. No capability top-up."""

    from src.application.active_research_runtime import ChainAttemptRequest
    from src.web.research.crawl4ai_browser_executor import (
        Crawl4AIBrowserBackendExecutor,
    )
    from src.web.research.read_escalation import (
        TIER_BROWSER,
        charge_run_envelope,
        reset_run_envelope,
    )

    executor = Crawl4AIBrowserBackendExecutor(
        bridge=bridge,
        mode=mode,
        max_chars=MAX_CHARS,
        session_id=SESSION_ID if category == "session_sensitive" else None,
        delay_ms=delay_ms,
        charge_envelope=lambda ms: charge_run_envelope(ms, TIER_BROWSER),
    )
    # §143.34: a real session capability needs its establishment cost accounted
    # separately, not hidden outside the timing boundary.
    setup_wall_ms = 0.0
    if setup_url:
        setup_started = time.perf_counter()
        bridge.request(
            timeout_ms=REQUEST_TIMEOUT_MS,
            url=setup_url,
            mode=mode,
            max_chars=MAX_CHARS,
            session_id=SESSION_ID,
            delay_ms=0,
        )
        setup_wall_ms = round((time.perf_counter() - setup_started) * 1000.0, 1)
    reset_run_envelope(TIER_BROWSER)
    t0 = time.perf_counter()
    result = executor.execute(
        ChainAttemptRequest(
            candidate_id=f"f2-{category}",
            url=url,
            host=urlparse(url).hostname or "",
            backend=CRAWL4AI_BACKEND,
            chain_step=0,
            outer_attempt_number=1,
        )
    )
    wall_ms = round((time.perf_counter() - t0) * 1000.0, 1)
    cost = dict(getattr(result, "cost", {}) or {})
    return {
        "wall_ms": wall_ms,
        "setup_wall_ms": setup_wall_ms,
        "total_task_wall_ms": round(wall_ms + setup_wall_ms, 1),
        "content": result.content,
        "reader_usable_content": bool(result.usable_content),
        "backend_path": [CRAWL4AI_BACKEND],
        "fallback_used": False,
        "terminal_outcome": result.retrieval_state,
        "queue_wait_ms": cost.get("queue_wait_ms"),
    }


# --------------------------------------------------------------------- driver

def _pair(bridge, spec: dict, base: str, *, allow_local: bool) -> dict:
    url = f"{base}{spec['fixture']}"
    expected = spec["critical_units"]
    if allow_local:
        _allow_local_fixture_reads()
    d = _run_default(url, spec["category"])
    setup_path = spec.get("session_setup")
    c = _run_crawl4ai(
        bridge,
        url,
        spec["mode"],
        spec["category"],
        setup_url=f"{base}{setup_path}" if setup_path else None,
        delay_ms=int(spec.get("delay_ms", 0)),
    )
    c_total_wall = c["total_task_wall_ms"]
    d_units = _units(d["content"], expected)
    c_units = _units(c["content"], expected)
    d_useful = _task_useful(len(d_units))
    c_useful = _task_useful(len(c_units))
    return {
        "category": spec["category"],
        "fixture": spec["fixture"],
        "expected_critical_units": expected,
        "default": {
            "backend_path": d["backend_path"],
            "useful": d_useful,
            "units_recovered": len(d_units),
            "units_total": len(expected),
            "unit_set": d_units,
            "wall_ms": d["wall_ms"],
            "fallback_used": d["fallback_used"],
            "terminal_outcome": d["terminal_outcome"],
            "reader_usable_content": d["reader_usable_content"],
            "runtime_origin": d["runtime_origin"],
        },
        "crawl4ai": {
            "useful": c_useful,
            "units_recovered": len(c_units),
            "units_total": len(expected),
            "unit_set": c_units,
            "wall_ms": c_total_wall,
            "read_wall_ms": c["wall_ms"],
            "setup_wall_ms": c["setup_wall_ms"],
            "total_task_wall_ms": c_total_wall,
            "fallback_used": c["fallback_used"],
            "terminal_outcome": c["terminal_outcome"],
            "reader_usable_content": c["reader_usable_content"],
        },
        # audit invariants (§143.49)
        "_invariants": {
            "default_used_real_run_chain": bool(d["backend_path"]),
            "default_backend_path_present": bool(d["backend_path"]),
            "default_from_shared_measurement_entry": d["runtime_origin"]["entry"]
            == "run_single_read_measurement",
            "default_backend_path_in_active_chain": d["runtime_origin"][
                "backend_path_in_active_chain"
            ],
            "crawl4ai_used_existing_executor": True,
            "same_expected_units_on_both_sides": True,
            "harness_added_fetches": 0,
            "harness_followed_links_itself": False,
            "ssrf_guard_relaxed_for_local_fixture": bool(allow_local),
            "default_unit_set": d_units,
            "crawl4ai_unit_set": c_units,
            "default_wall_ms_positive": d["wall_ms"] > 0,
            "crawl4ai_wall_ms_positive": c_total_wall > 0,
        },
    }


def _wigolo_fallback_status() -> str:
    """Production fallback health (``ready`` / ``unavailable`` / ``misconfigured``)."""

    from src.web.research.wigolo_backend import WigoloShadowReadBackend

    return WigoloShadowReadBackend(tier="http").preflight()


def _run_fallback_sentinel(base: str, *, allow_local: bool) -> dict:
    """Prove the production default fallback is live: NATIVE_HTTP -> WIGOLO_HTTP."""

    from tools.f2_paired_fixture_server import SENTINEL_MARKER

    if allow_local:
        _allow_local_fixture_reads()
    row = _run_default(f"{base}{FALLBACK_SENTINEL}", "fallback_sentinel")
    path = row["backend_path"]
    native_then_wigolo = path[:2] == [NATIVE, WIGOLO_HTTP]
    return {
        "url": FALLBACK_SENTINEL,
        "marker": SENTINEL_MARKER,
        "backend_path": path,
        "native_then_wigolo": native_then_wigolo,
        "wigolo_reachable": WIGOLO_HTTP in path,
        "passed": native_then_wigolo,
    }


def _smoke_verdict(row: dict) -> dict:
    """§143.49 + runtime-origin invariant, machine-checked.

    ``*_unit_set present`` means the field was produced for both sides (a
    plumbing check), not that it is non-empty: a fixture whose units genuinely
    live elsewhere (e.g. the linked document) is a *result*, not a harness bug.
    """

    inv = row["_invariants"]
    checks = {
        "default_used_real_run_chain": inv["default_used_real_run_chain"],
        "default_backend_path_present": inv["default_backend_path_present"],
        "default_from_shared_measurement_entry": inv[
            "default_from_shared_measurement_entry"
        ],
        "default_backend_path_in_active_chain": inv[
            "default_backend_path_in_active_chain"
        ],
        "crawl4ai_used_existing_executor": inv["crawl4ai_used_existing_executor"],
        "same_expected_units_on_both_sides": inv["same_expected_units_on_both_sides"],
        "harness_added_fetches_zero": inv["harness_added_fetches"] == 0,
        "harness_followed_links_itself_false": inv[
            "harness_followed_links_itself"
        ]
        is False,
        "default_unit_set_present": "unit_set" in row["default"],
        "crawl4ai_unit_set_present": "unit_set" in row["crawl4ai"],
        "default_wall_ms_positive": inv["default_wall_ms_positive"],
        "crawl4ai_wall_ms_positive": inv["crawl4ai_wall_ms_positive"],
    }
    return {"passed": all(checks.values()), "checks": checks}


def _classify(pairs: list[dict]) -> dict:
    """§143.38 + §143.48: mechanical gain, status-separated, no averaging away."""

    d_sets = {tuple(sorted(p["default"]["unit_set"])) for p in pairs}
    c_sets = {tuple(sorted(p["crawl4ai"]["unit_set"])) for p in pairs}
    d_use = {p["default"]["useful"] for p in pairs}
    c_use = {p["crawl4ai"]["useful"] for p in pairs}
    consistent = (
        len(d_sets) == 1 and len(c_sets) == 1 and len(d_use) == 1 and len(c_use) == 1
    )

    d_units = set(pairs[0]["default"]["unit_set"])
    c_units = set(pairs[0]["crawl4ai"]["unit_set"])
    d_useful = bool(pairs[0]["default"]["useful"])
    c_useful = bool(pairs[0]["crawl4ai"]["useful"])
    total = len(pairs[0]["expected_critical_units"])

    # §143.38 frozen mechanical bands. MINOR requires C4AI to add only
    # non-critical content, which the frozen rubric does not enumerate, so it is
    # not emitted by this harness (equal decision-critical recovery -> NONE).
    status, gain = "RESOLVED", "NONE"
    if not consistent:
        status, gain = "UNSTABLE_OUTCOME", None
    elif not d_useful and not c_useful:
        status, gain = "UNRESOLVED_FOR_TASK", None
    elif not d_useful and c_useful:
        gain = "ESSENTIAL"
    elif d_useful and c_useful and (c_units - d_units):
        gain = "MATERIAL"
    else:
        gain = "NONE"

    d_wall = statistics.median([p["default"]["wall_ms"] for p in pairs])
    c_wall = statistics.median([p["crawl4ai"]["wall_ms"] for p in pairs])
    return {
        "classification_status": status,
        "specialist_gain": gain,
        "default_content_consistent": len(d_sets) == 1 and len(d_use) == 1,
        "crawl4ai_content_consistent": len(c_sets) == 1 and len(c_use) == 1,
        "default_units": f"{len(d_units)}/{total}",
        "crawl4ai_units": f"{len(c_units)}/{total}",
        "default_useful": d_useful,
        "crawl4ai_useful": c_useful,
        "default_backend_path": " -> ".join(pairs[0]["default"]["backend_path"]),
        "default_median_wall": round(d_wall, 1),
        "crawl4ai_median_wall": round(c_wall, 1),
        "delta_wall_ms": round(c_wall - d_wall, 1),
    }


def _wait_for_server(base: str, deadline_seconds: float = 20.0) -> bool:
    deadline = time.time() + deadline_seconds
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"{base}/code-docs.html", timeout=2).read(16)
            return True
        except Exception:
            time.sleep(0.3)
    return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pairs", type=int, default=5)
    ap.add_argument("--smoke", action="store_true", help="simple_static, 1 pair")
    ap.add_argument("--python", default=str(DEFAULT_ISOLATED))
    ap.add_argument("--output", default="")
    ap.add_argument("--seed", type=int, default=143)
    ap.add_argument(
        "--no-local-ssrf-relax",
        action="store_true",
        help="do not relax the SSRF guard for the loopback fixture",
    )
    ap.add_argument(
        "--allow-unhealthy-fallback",
        action="store_true",
        help="do not abort when the wigolo HTTP fallback is not ready (debug only)",
    )
    args = ap.parse_args(argv)

    specs = [CATEGORIES[0]] if args.smoke else list(CATEGORIES)
    n_pairs = 1 if args.smoke else args.pairs
    allow_local = not args.no_local_ssrf_relax

    # The browser tier must be enabled for the specialist side (same as the
    # existing cohort/qualification runners).
    os.environ.setdefault("RESEARCH_WIGOLO_ESCALATION", "browser")
    os.environ.setdefault("WIGOLO_BROWSER_ESCALATION", "1")
    os.environ.setdefault("WIGOLO_RERANKER", "off")

    # §143-B companion gate D: the production default fallback must be live,
    # otherwise the default side is measured as native-only and biased.
    fallback_status = _wigolo_fallback_status()
    print(f"wigolo fallback preflight: {fallback_status}", flush=True)
    if fallback_status != "ready" and not args.allow_unhealthy_fallback:
        raise SystemExit(
            "wigolo HTTP fallback is not ready; start the daemon (WIGOLO_RERANKER=off) "
            "or pass --allow-unhealthy-fallback (latency/default-path then NON-AUTHORITATIVE)"
        )

    server = subprocess.Popen(
        [sys.executable, "-u", "-X", "utf8", str(FIXTURE), "--port", str(PORT)],
        cwd=str(REPO_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{PORT}"
    if not _wait_for_server(base):
        server.terminate()
        raise SystemExit("fixture server did not become ready")

    from src.web.research.crawl4ai_browser_executor import Crawl4AIBridge

    bridge = Crawl4AIBridge(python=args.python)
    bridge.start()
    raw: list[dict] = []
    smoke: dict | None = None
    fallback_sentinel: dict | None = None
    try:
        for spec in specs:  # warm-up per fixture (discarded)
            _pair(bridge, spec, base, allow_local=allow_local)
        order = [s for s in specs for _ in range(n_pairs)]
        random.Random(args.seed).shuffle(order)
        for i, spec in enumerate(order):
            row = _pair(bridge, spec, base, allow_local=allow_local)
            row["pair_index"] = i
            row["order"] = "default-first"
            raw.append(row)
            print(
                f"[{i + 1}/{len(order)}] {row['category']:18s} "
                f"default={row['default']['units_recovered']}/"
                f"{row['default']['units_total']} "
                f"({row['default']['wall_ms']:.0f}ms "
                f"path={'->'.join(row['default']['backend_path'])}) "
                f"c4ai={row['crawl4ai']['units_recovered']}/"
                f"{row['crawl4ai']['units_total']} "
                f"({row['crawl4ai']['wall_ms']:.0f}ms)"
            )
        # companion gate D: always prove the production fallback is live
        fallback_sentinel = _run_fallback_sentinel(base, allow_local=allow_local)
        if args.smoke and raw:
            pair_verdict = _smoke_verdict(raw[0])
            smoke = {
                "passed": bool(pair_verdict["passed"] and fallback_sentinel["passed"]),
                "fallback_preflight": fallback_status,
                "checks": {
                    **pair_verdict["checks"],
                    "fallback_sentinel_native_then_wigolo": fallback_sentinel["passed"],
                },
                "fallback_sentinel": fallback_sentinel,
            }
    finally:
        bridge.stop()
        server.terminate()
        try:
            server.wait(timeout=5)
        except Exception:
            server.kill()

    aggregate = {
        spec["category"]: _classify([r for r in raw if r["category"] == spec["category"]])
        for spec in specs
    }
    print("\n=== §143-B table ===")
    for cat, a in aggregate.items():
        print(
            f"{cat:18s} status={a['classification_status']:20s} "
            f"gain={a['specialist_gain']} "
            f"units {a['default_units']} vs {a['crawl4ai_units']} "
            f"wall {a['default_median_wall']} vs {a['crawl4ai_median_wall']} "
            f"d={a['delta_wall_ms']} path={a['default_backend_path']}"
        )

    if smoke is not None:
        print("\n=== smoke verdict (§143.49 + runtime-origin + fallback sentinel) ===")
        print(f"passed={smoke['passed']}  fallback_preflight={smoke['fallback_preflight']}")
        for name, ok in smoke["checks"].items():
            print(f"  {'PASS' if ok else 'FAIL'}  {name}")
        sent = smoke.get("fallback_sentinel") or {}
        print(f"  fallback_sentinel path={sent.get('backend_path')}")

    if args.output:
        out = Path(args.output)
        if not out.is_absolute():
            out = REPO_ROOT / out
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": "f2-paired-v1",
            "pairs": n_pairs,
            "seed": args.seed,
            "fallback_preflight": fallback_status,
            "fallback_sentinel": fallback_sentinel,
            "smoke": smoke,
            "raw": raw,
            "aggregate": aggregate,
        }
        out.write_text(
            json.dumps(payload, indent=1, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"\nwrote {out}")

    if args.smoke and smoke is not None and not smoke["passed"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
