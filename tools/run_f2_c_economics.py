# -*- coding: utf-8 -*-
"""§143-C routing economics characterization (pre-route + post-default signals).

Frozen contract (see docs/PROJECT_STATUS.md §143.118-§143.121):

* Question: which **preregistered** signals can identify Crawl4AI high-gain
  scenarios and avoid no-gain escalation, producing economics evidence for a
  later routing review?
* Evidence cohort: the 6 threshold-safe §143-B fixtures. Categories, critical
  units and rubric are unchanged. No new fixture class.
* Signal classes (the finite, preregistered set below):
    P0 zero-fetch pre-route      URL / extension / path
    P1 costed metadata pre-route HEAD Content-Type (probe wall counted)
    P2 post-default escalation   only the default read's real outcome/metadata
* Forbidden: specialist-result feedback, online learning, extra content fetch
  for classification, any production routing change.
* Economics are reported as a **decision vector**, never a single scalar:
    quality/resolution uplift + incremental wall + false-positive rate +
    false-positive wall cost.
* Latency is C-local steady state (same process, fallback ready, 1 discarded
  warm-up, >=5 timed repetitions, median + p95), not B's warm median.

STOP: after the Pareto / decision table. If no rule meets
``ESSENTIAL recall = 100%`` and ``NONE false positives = 0``, the conclusion is
"current preregistered signals are insufficient for automatic routing" - a valid
negative result. No signal may be added after seeing a miss.

Usage::

    python tools/run_f2_c_economics.py --reps 5 --output docs/research_quality/F2_C_ECONOMICS.json
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.run_f2_paired import (  # noqa: E402
    CATEGORIES,
    DEFAULT_ISOLATED,
    PORT,
    _allow_local_fixture_reads,
    _run_crawl4ai,
    _run_default,
    _wigolo_fallback_status,
)

FIXTURE = REPO_ROOT / "tools" / "f2_paired_fixture_server.py"
REQUEST_TIMEOUT_MS = 20000
SESSION_ID = "f2sess"

#: §143-B frozen labels. C does NOT re-derive these; it consumes the closed B
#: verdict so quality uplift stays attributable to B.
C_LABELS: dict[str, str] = {
    "simple_static": "NONE",
    "technical_docs": "NONE",
    "js_heavy": "ESSENTIAL",
    "session_sensitive": "ESSENTIAL",
    "selected_pdf": "MATERIAL",
    "document_path": "UNRESOLVED_FOR_TASK",
}

ESSENTIAL = frozenset(c for c, label in C_LABELS.items() if label == "ESSENTIAL")
NONE = frozenset(c for c, label in C_LABELS.items() if label == "NONE")
MATERIAL = frozenset(c for c, label in C_LABELS.items() if label == "MATERIAL")
UNRESOLVED = frozenset(
    c for c, label in C_LABELS.items() if label == "UNRESOLVED_FOR_TASK"
)

JS_PATH_TOKENS = ("spa-", "js-shell", "/app")


def _path_of(url: str) -> str:
    return "/" + url.split("://", 1)[-1].split("/", 1)[-1] if "://" in url else url


def _is_pdf_path(path: str) -> bool:
    return path.lower().split("?", 1)[0].endswith(".pdf")


def _is_js_path(path: str) -> bool:
    lowered = path.lower()
    return any(token in lowered for token in JS_PATH_TOKENS)


def _is_session_path(path: str) -> bool:
    return "session" in path.lower()


def _is_document_path(path: str) -> bool:
    return "document" in path.lower()


#: The FINITE, preregistered signal set. ``match`` sees only the allowed inputs
#: for its class. Nothing here may be added after a miss is observed.
RULES: tuple[dict[str, Any], ...] = (
    {
        "name": "p0_ext_pdf",
        "signal_class": "P0_zero_fetch",
        "signal": "url:extension",
        "match": lambda ctx: _is_pdf_path(ctx["path"]),
    },
    {
        "name": "p0_path_session",
        "signal_class": "P0_zero_fetch",
        "signal": "url_path",
        "match": lambda ctx: _is_session_path(ctx["path"]),
    },
    {
        "name": "p0_path_js",
        "signal_class": "P0_zero_fetch",
        "signal": "url_path",
        "match": lambda ctx: _is_js_path(ctx["path"]),
    },
    {
        "name": "p0_path_document",
        "signal_class": "P0_zero_fetch",
        "signal": "url_path",
        "match": lambda ctx: _is_document_path(ctx["path"]),
    },
    {
        "name": "p0_essential_targets",
        "signal_class": "P0_zero_fetch",
        "signal": "url_path(union:session|js)",
        "match": lambda ctx: _is_session_path(ctx["path"]) or _is_js_path(ctx["path"]),
    },
    {
        "name": "p0_all_targeted",
        "signal_class": "P0_zero_fetch",
        "signal": "url_path+ext(union)",
        "match": lambda ctx: (
            _is_pdf_path(ctx["path"])
            or _is_session_path(ctx["path"])
            or _is_js_path(ctx["path"])
            or _is_document_path(ctx["path"])
        ),
    },
    {
        "name": "p1_ct_pdf",
        "signal_class": "P1_metadata_costed",
        "signal": "content_type",
        "match": lambda ctx: "pdf" in str(ctx.get("content_type", "")).lower(),
    },
    {
        "name": "p1_ct_non_html",
        "signal_class": "P1_metadata_costed",
        "signal": "content_type",
        "match": lambda ctx: bool(ctx.get("content_type"))
        and "html" not in str(ctx["content_type"]).lower(),
    },
    {
        "name": "p2_did_not_resolve",
        "signal_class": "P2_post_default",
        "signal": "terminal_outcome",
        "match": lambda ctx: ctx["default"]["terminal_outcome"] != "resolve",
    },
    {
        "name": "p2_short_doc_or_invalid",
        "signal_class": "P2_post_default",
        "signal": "step shape",
        "match": lambda ctx: any(
            str(s.get("adequacy_reason", "")) == "short_doc"
            or str(s.get("retrieval_state", "")) == "invalid_content"
            for s in ctx["default"]["steps"]
        ),
    },
    {
        "name": "p2_default_escalated",
        "signal_class": "P2_post_default",
        "signal": "backend_path",
        "match": lambda ctx: "wigolo_http" in ctx["default"]["backend_path"],
    },
)


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(0.95 * len(ordered)) - 1))
    return round(ordered[index], 1)


def _median(values: list[float]) -> float:
    return round(statistics.median(values), 1) if values else 0.0


def _probe_content_type(url: str) -> tuple[str, float]:
    """A cost-bearing P1 metadata probe (HEAD). Never a content read."""

    request = urllib.request.Request(url, method="HEAD")
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
            content_type = response.headers.get("Content-Type", "")
    except Exception:
        content_type = ""
    return content_type, round((time.perf_counter() - started) * 1000.0, 1)


def passes_gate(result: Mapping[str, Any]) -> bool:
    return (
        result["essential_recall"] == 1.0
        and result["essential_missed"] == []
        and result["none_false_positives"] == []
    )


def evaluate_rule(
    rule: Mapping[str, Any],
    contexts: Mapping[str, Mapping[str, Any]],
    labels: Mapping[str, str],
    latency: Mapping[str, Mapping[str, float]],
) -> dict[str, Any]:
    """Pure rule evaluation over the frozen cohort (no I/O)."""

    triggered = sorted(
        category
        for category, ctx in contexts.items()
        if bool(rule["match"](ctx))
    )
    essential = {c for c, label in labels.items() if label == "ESSENTIAL"}
    none = {c for c, label in labels.items() if label == "NONE"}
    material = {c for c, label in labels.items() if label == "MATERIAL"}
    unresolved = {c for c, label in labels.items() if label == "UNRESOLVED_FOR_TASK"}

    essential_hits = sorted(set(triggered) & essential)
    essential_missed = sorted(essential - set(triggered))
    essential_recall = round(len(essential_hits) / len(essential), 4) if essential else 1.0
    none_fp = sorted(set(triggered) & none)
    material_capture = sorted(set(triggered) & material)
    unresolved_trigger = sorted(set(triggered) & unresolved)

    def incremental_for(category: str) -> float:
        entry = latency.get(category, {})
        extra = float(entry.get("specialist_median_wall_ms", 0.0))
        if rule["signal_class"] == "P1_metadata_costed":
            extra += float(entry.get("probe_median_wall_ms", 0.0))
        return round(extra, 1)

    incremental = {c: incremental_for(c) for c in triggered}
    fp_wall_cost = _median([incremental_for(c) for c in none_fp]) if none_fp else 0.0
    incremental_median = _median(list(incremental.values())) if incremental else 0.0

    return {
        "name": rule["name"],
        "signal_class": rule["signal_class"],
        "signal": rule["signal"],
        "triggered": triggered,
        "confusion": {
            "ESSENTIAL": {"hit": essential_hits, "missed": essential_missed},
            "NONE": {"false_positive": none_fp},
            "MATERIAL": {"captured": material_capture, "missed": sorted(material - set(triggered))},
            "UNRESOLVED_FOR_TASK": {"no_current_gain_escalation": unresolved_trigger},
        },
        "essential_recall": essential_recall,
        "essential_missed": essential_missed,
        "none_false_positives": none_fp,
        "material_capture": material_capture,
        "unresolved_no_gain_escalation": unresolved_trigger,
        "false_positive_rate": round(len(none_fp) / len(none), 4) if none else 0.0,
        "incremental_wall_ms_by_triggered": incremental,
        "incremental_median_wall_ms": incremental_median,
        "false_positive_wall_cost_ms": fp_wall_cost,
        "gate_pass": passes_gate(
            {
                "essential_recall": essential_recall,
                "essential_missed": essential_missed,
                "none_false_positives": none_fp,
            }
        ),
    }


def _pareto_front(results: list[dict[str, Any]]) -> list[str]:
    """Rules not dominated on (max essential_recall, min NONE FP, min FP wall)."""

    front: list[str] = []
    for candidate in results:
        dominated = False
        for other in results:
            if other is candidate:
                continue
            better_or_equal = (
                other["essential_recall"] >= candidate["essential_recall"]
                and len(other["none_false_positives"]) <= len(candidate["none_false_positives"])
                and other["false_positive_wall_cost_ms"] <= candidate["false_positive_wall_cost_ms"]
            )
            strictly_better = (
                other["essential_recall"] > candidate["essential_recall"]
                or len(other["none_false_positives"]) < len(candidate["none_false_positives"])
                or other["false_positive_wall_cost_ms"] < candidate["false_positive_wall_cost_ms"]
            )
            if better_or_equal and strictly_better:
                dominated = True
                break
        if not dominated:
            front.append(candidate["name"])
    return front


def _result_summary(result: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "name": result["name"],
        "class": result["signal_class"],
        "essential_recall": result["essential_recall"],
        "none_fp": result["none_false_positives"],
        "material_capture": result["material_capture"],
        "unresolved_trigger": result["unresolved_no_gain_escalation"],
        "incremental_median_wall_ms": result["incremental_median_wall_ms"],
        "fp_wall_cost_ms": result["false_positive_wall_cost_ms"],
        "gate_pass": result["gate_pass"],
    }


def _wait_for_server(base: str, deadline_seconds: float = 20.0) -> bool:
    deadline = time.time() + deadline_seconds
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"{base}/structured-spec.html", timeout=2).read(16)
            return True
        except Exception:
            time.sleep(0.3)
    return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reps", type=int, default=5, help="timed repetitions (>=5)")
    ap.add_argument("--python", default=str(DEFAULT_ISOLATED))
    ap.add_argument("--output", default="")
    ap.add_argument(
        "--allow-unhealthy-fallback",
        action="store_true",
        help="debug only: do not abort when the fallback is not ready",
    )
    args = ap.parse_args(argv)
    reps = max(1, int(args.reps))

    import os

    os.environ.setdefault("RESEARCH_WIGOLO_ESCALATION", "browser")
    os.environ.setdefault("WIGOLO_BROWSER_ESCALATION", "1")
    os.environ.setdefault("WIGOLO_RERANKER", "off")

    fallback_status = _wigolo_fallback_status()
    print(f"wigolo fallback preflight: {fallback_status}", flush=True)
    if fallback_status != "ready" and not args.allow_unhealthy_fallback:
        raise SystemExit("wigolo HTTP fallback is not ready; start the daemon first")

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

    specs = list(CATEGORIES)
    samples: dict[str, dict[str, list[float]]] = {
        spec["category"]: {"probe": [], "default": [], "specialist": []} for spec in specs
    }
    content_types: dict[str, str] = {}
    default_meta: dict[str, dict[str, Any]] = {}
    urls: dict[str, str] = {}

    def one_round(discard: bool) -> None:
        for spec in specs:
            category = spec["category"]
            url = f"{base}{spec['fixture']}"
            urls[category] = url
            ctype, probe_ms = _probe_content_type(url)
            content_types[category] = ctype
            _allow_local_fixture_reads()
            d = _run_default(url, category)
            setup_path = spec.get("session_setup")
            c = _run_crawl4ai(
                bridge,
                url,
                spec["mode"],
                category,
                setup_url=f"{base}{setup_path}" if setup_path else None,
                delay_ms=int(spec.get("delay_ms", 0)),
            )
            default_meta[category] = d
            if not discard:
                samples[category]["probe"].append(probe_ms)
                samples[category]["default"].append(float(d["wall_ms"]))
                samples[category]["specialist"].append(float(c["total_task_wall_ms"]))

    try:
        one_round(discard=True)  # 1 discarded warm-up
        for _ in range(reps):
            one_round(discard=False)
    finally:
        bridge.stop()
        server.terminate()
        try:
            server.wait(timeout=5)
        except Exception:
            server.kill()

    latency = {
        category: {
            "probe_median_wall_ms": _median(values["probe"]),
            "probe_p95_wall_ms": _p95(values["probe"]),
            "default_median_wall_ms": _median(values["default"]),
            "default_p95_wall_ms": _p95(values["default"]),
            "specialist_median_wall_ms": _median(values["specialist"]),
            "specialist_p95_wall_ms": _p95(values["specialist"]),
        }
        for category, values in samples.items()
    }
    contexts = {
        category: {
            "url": urls[category],
            "path": _path_of(urls[category]),
            "content_type": content_types[category],
            "default": default_meta[category],
        }
        for category in urls
    }

    results = [evaluate_rule(rule, contexts, C_LABELS, latency) for rule in RULES]
    front = _pareto_front(results)
    gate_passers = [r["name"] for r in results if r["gate_pass"]]

    if gate_passers:
        conclusion = "SOME_RULES_MEET_GATE"
        note = (
            "At least one preregistered rule meets ESSENTIAL recall=100% and NONE "
            "false positives=0 on this frozen cohort. C is characterization on this "
            "cohort only, not a generalization proof; routing review decides."
        )
    else:
        conclusion = "INSUFFICIENT_PREREGISTERED_SIGNALS"
        note = (
            "No preregistered rule meets ESSENTIAL recall=100% and NONE false "
            "positives=0. Valid negative result: current signals are insufficient "
            "for automatic routing. No signal may be added after this miss."
        )

    print("\n=== §143-C decision table ===")
    for summary in [_result_summary(r) for r in results]:
        print(
            f"{summary['name']:28s} {summary['class']:20s} "
            f"recall={summary['essential_recall']:.2f} "
            f"none_fp={summary['none_fp']} "
            f"mat={summary['material_capture']} "
            f"unres={summary['unresolved_trigger']} "
            f"incr={summary['incremental_median_wall_ms']:.1f}ms "
            f"fpwall={summary['fp_wall_cost_ms']:.1f}ms "
            f"gate={'PASS' if summary['gate_pass'] else 'fail'}"
        )
    print(f"\nPareto front: {front}")
    print(f"STOP conclusion: {conclusion}")
    print(note)

    if args.output:
        out = Path(args.output)
        if not out.is_absolute():
            out = REPO_ROOT / out
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": "f2-c-economics-v1",
            "reps": reps,
            "fallback_preflight": fallback_status,
            "labels": C_LABELS,
            "latency": latency,
            "content_types": content_types,
            "default_observed": {
                category: {
                    "terminal_outcome": meta.get("terminal_outcome"),
                    "terminal_reason": meta.get("terminal_reason"),
                    "backend_path": meta.get("backend_path"),
                    "steps": meta.get("steps"),
                }
                for category, meta in default_meta.items()
            },
            "rules": results,
            "pareto_front": front,
            "gate_passers": gate_passers,
            "conclusion": conclusion,
            "note": note,
        }
        out.write_text(
            json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"\nwrote {out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
