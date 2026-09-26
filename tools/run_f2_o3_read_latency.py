# -*- coding: utf-8 -*-
"""F2-O3a: read latency characterisation (read-only).

One question: is the 1.0-17.5s read spread "more read work" or "the same read
work waiting longer on the network/remote host"?

It splits each read into network wait, retry backoff and local post-fetch work,
then reports reads/attempts per run, per-attempt fetch statistics, host and
error-signature concentration, and whether bytes explain latency. It never
changes timeouts, concurrency, the reader, fallbacks or the circuit breaker.
"""

from __future__ import annotations

import argparse
import glob
import io
import json
import math
import os
from typing import Any


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = _mean(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / (len(values) - 1))


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3 or len(xs) != len(ys):
        return None
    mx, my = _mean(xs), _mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy)


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def load_runs(paths: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    runs: list[dict[str, Any]] = []
    skipped: list[str] = []
    for path in paths:
        try:
            data = json.loads(io.open(path, encoding="utf-8").read())
        except Exception:
            skipped.append(path)
            continue
        cases = data.get("cases") if isinstance(data, dict) else None
        if not isinstance(cases, list) or not cases:
            skipped.append(path)
            continue
        case = cases[0]
        metrics = case.get("metrics") or {}
        timing = metrics.get("read_timing")
        if not isinstance(timing, list) or not timing:
            skipped.append(path)
            continue
        reads = [
            {
                "host": str(row.get("host") or ""),
                "wave": row.get("wave_index"),
                "status": str(row.get("status") or ""),
                "wall_ms": _num(row.get("wall_ms")) or 0.0,
                "fetch_ms": _num(row.get("fetch_ms")) or 0.0,
                "backoff_ms": _num(row.get("backoff_ms")) or 0.0,
                "local_ms": _num(row.get("local_ms")) or 0.0,
                "escalation_ms": _num(row.get("escalation_ms")) or 0.0,
                "attempts": _num(row.get("attempts")) or 1.0,
                "retries": _num(row.get("retries")) or 0.0,
                "chars": _num(row.get("chars")) or 0.0,
                "error_signature": str(row.get("error_signature") or ""),
                "attempts_detail": row.get("attempts_detail") or [],
            }
            for row in timing
            if isinstance(row, dict)
        ]
        runs.append(
            {
                "artifact": os.path.basename(path),
                "run": str(case.get("run") or os.path.basename(path)),
                "host_case": str(case.get("category") or ""),
                "elapsed_seconds": _num(case.get("elapsed_seconds")) or 0.0,
                "reads": reads,
            }
        )
    return runs, skipped


def run_summary(run: dict[str, Any]) -> dict[str, Any]:
    reads = run["reads"]
    walls = [r["wall_ms"] for r in reads]
    fetches = [r["fetch_ms"] for r in reads]
    locals_ = [r["local_ms"] for r in reads]
    retry_fetch = sum(r["fetch_ms"] for r in reads if r["retries"] > 0)
    return {
        "artifact": run["artifact"],
        "reads": len(reads),
        "attempts": int(sum(r["attempts"] for r in reads)),
        "success": sum(1 for r in reads if r["status"] == "success"),
        "wall_total_ms": round(sum(walls), 1),
        "fetch_total_ms": round(sum(fetches), 1),
        "local_total_ms": round(sum(locals_), 1),
        "retry_fetch_total_ms": round(retry_fetch, 1),
        "fetch_mean_ms": round(_mean(fetches), 1),
        "fetch_median_ms": round(_median(fetches), 1),
        "fetch_max_ms": round(max(fetches), 1) if fetches else 0.0,
        "wall_max_ms": round(max(walls), 1) if walls else 0.0,
        "local_max_ms": round(max(locals_), 1) if locals_ else 0.0,
    }


def analyse(runs: list[dict[str, Any]]) -> dict[str, Any]:
    reads = [r for run in runs for r in run["reads"]]
    walls = [r["wall_ms"] for r in reads]
    fetches = [r["fetch_ms"] for r in reads]
    locals_ = [r["local_ms"] for r in reads]
    backoffs = [r["backoff_ms"] for r in reads]

    by_host: dict[str, dict[str, Any]] = {}
    for read in reads:
        bucket = by_host.setdefault(
            read["host"], {"n": 0, "fetch": [], "wall": [], "local": [], "fail": 0}
        )
        bucket["n"] += 1
        bucket["fetch"].append(read["fetch_ms"])
        bucket["wall"].append(read["wall_ms"])
        bucket["local"].append(read["local_ms"])
        bucket["fail"] += 1 if read["status"] != "success" else 0

    by_signature: dict[str, dict[str, Any]] = {}
    for read in reads:
        if read["status"] == "success":
            continue
        signature = read["error_signature"] or "(none)"
        bucket = by_signature.setdefault(signature, {"n": 0, "fetch": []})
        bucket["n"] += 1
        bucket["fetch"].append(read["fetch_ms"])

    slow = sorted(reads, key=lambda r: -r["fetch_ms"])[:8]
    return {
        "calls": len(reads),
        "wall_ms": {
            "mean": round(_mean(walls), 1),
            "median": round(_median(walls), 1),
            "stdev": round(_stdev(walls), 1),
            "min": min(walls) if walls else None,
            "max": max(walls) if walls else None,
            "total": round(sum(walls), 1),
        },
        "fetch_ms": {
            "mean": round(_mean(fetches), 1),
            "median": round(_median(fetches), 1),
            "stdev": round(_stdev(fetches), 1),
            "min": min(fetches) if fetches else None,
            "max": max(fetches) if fetches else None,
            "total": round(sum(fetches), 1),
        },
        "local_ms": {
            "mean": round(_mean(locals_), 1),
            "median": round(_median(locals_), 1),
            "stdev": round(_stdev(locals_), 1),
            "max": max(locals_) if locals_ else None,
            "total": round(sum(locals_), 1),
        },
        "backoff_ms_total": round(sum(backoffs), 1),
        "share_of_wall": {
            "fetch": round(sum(fetches) / sum(walls), 3) if sum(walls) else None,
            "local": round(sum(locals_) / sum(walls), 3) if sum(walls) else None,
            "backoff": round(sum(backoffs) / sum(walls), 3) if sum(walls) else None,
        },
        "variance": {
            "var_wall": round(_variance(walls), 1),
            "var_fetch": round(_variance(fetches), 1),
            "var_local": round(_variance(locals_), 1),
            "corr_wall_fetch": _round(_pearson(walls, fetches)),
            "corr_wall_local": _round(_pearson(walls, locals_)),
            "corr_fetch_chars": _round(
                _pearson(
                    [r["fetch_ms"] for r in reads],
                    [r["chars"] for r in reads],
                )
            ),
        },
        "by_host": {
            name: {
                "n": value["n"],
                "fail": value["fail"],
                "fetch_mean": round(_mean(value["fetch"]), 1),
                "fetch_max": round(max(value["fetch"]), 1),
                "wall_mean": round(_mean(value["wall"]), 1),
                "local_mean": round(_mean(value["local"]), 1),
            }
            for name, value in sorted(
                by_host.items(), key=lambda item: -_mean(item[1]["fetch"])
            )
        },
        "failures_by_signature": {
            name: {"n": value["n"], "fetch_mean": round(_mean(value["fetch"]), 1)}
            for name, value in sorted(
                by_signature.items(), key=lambda item: -item[1]["n"]
            )
        },
        "slowest_reads": [
            {
                "host": read["host"],
                "status": read["status"],
                "fetch_ms": read["fetch_ms"],
                "wall_ms": read["wall_ms"],
                "local_ms": read["local_ms"],
                "attempts": read["attempts"],
                "chars": read["chars"],
                "signature": read["error_signature"],
            }
            for read in slow
        ],
    }


def _variance(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = _mean(values)
    return sum((v - mean) ** 2 for v in values) / (len(values) - 1)


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 3)


def verdict(analysis: dict[str, Any]) -> dict[str, Any]:
    share = analysis["share_of_wall"]
    variance = analysis["variance"]
    fetch_share = share.get("fetch") or 0.0
    local_share = share.get("local") or 0.0
    corr_wall_fetch = variance.get("corr_wall_fetch")
    corr_wall_local = variance.get("corr_wall_local")
    corr_fetch_chars = variance.get("corr_fetch_chars")
    hosts = analysis["by_host"]
    signatures = analysis["failures_by_signature"]
    total = analysis["calls"] or 1
    concentrated = bool(hosts) and (
        sum(v["fail"] for v in hosts.values()) / total >= 0.4
        or max(v["fetch_max"] for v in hosts.values()) >= 5000
    )
    total_fetch = analysis["fetch_ms"]["total"] or 0.0
    top_host_share = None
    if total_fetch and hosts:
        # ``by_host`` is sorted by descending mean fetch, so the first entry is
        # the host holding the largest share of the run's network wait.
        first = next(iter(hosts.values()))
        top_host_share = round(first["fetch_mean"] * first["n"] / total_fetch, 3)

    if fetch_share >= 0.6 and (corr_wall_fetch or 0) >= 0.8:
        call = "network_dominated"
    elif local_share >= 0.4 or (corr_wall_local or 0) > (corr_wall_fetch or 0):
        call = "local_post_fetch_dominated"
    else:
        call = "inconclusive_needs_more_samples"

    return {
        "call": call,
        "fetch_share_of_wall": fetch_share,
        "local_share_of_wall": local_share,
        "backoff_share_of_wall": share.get("backoff"),
        "corr_wall_fetch": corr_wall_fetch,
        "corr_wall_local": corr_wall_local,
        "corr_fetch_chars": corr_fetch_chars,
        "host_concentration": concentrated,
        "top_host_fetch_share": top_host_share,
        "top_hosts": list(hosts)[:3],
        "top_failure_signatures": list(signatures)[:3],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifacts", nargs="*")
    parser.add_argument("--glob", action="append", default=[])
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    paths: list[str] = []
    for pattern in args.glob:
        paths.extend(sorted(glob.glob(pattern)))
    paths.extend(args.artifacts)
    if not paths:
        paths = sorted(glob.glob("docs/research_quality/O3.*.json"))

    runs, skipped = load_runs(paths)
    analysis = analyse(runs)
    report = {
        "schema": "f2-o3a-read-latency-v1",
        "artifacts": [os.path.basename(p) for p in paths],
        "skipped": [os.path.basename(p) for p in skipped],
        "runs": [run_summary(run) for run in runs],
        "analysis": analysis,
        "verdict": verdict(analysis),
    }

    print(f"runs: {len(runs)}  reads: {analysis['calls']}")
    print("\nper run (reads x attempts x fetch):")
    print(
        f"  {'artifact':22s} {'reads':>5s} {'att':>4s} {'ok':>3s} {'wall_tot':>9s} "
        f"{'fetch_tot':>10s} {'local_tot':>10s} {'retry_f':>8s} {'f_mean':>7s} {'f_max':>7s}"
    )
    for run in report["runs"]:
        print(
            f"  {run['artifact']:22s} {run['reads']:>5d} {run['attempts']:>4d} "
            f"{run['success']:>3d} {run['wall_total_ms']:>9.0f} {run['fetch_total_ms']:>10.0f} "
            f"{run['local_total_ms']:>10.0f} {run['retry_fetch_total_ms']:>8.0f} "
            f"{run['fetch_mean_ms']:>7.0f} {run['fetch_max_ms']:>7.0f}"
        )
    print("\npooled:", json.dumps(
        {
            "wall": analysis["wall_ms"],
            "fetch": analysis["fetch_ms"],
            "local": analysis["local_ms"],
            "backoff_total": analysis["backoff_ms_total"],
        },
        ensure_ascii=False,
    ))
    print("share_of_wall:", json.dumps(analysis["share_of_wall"], ensure_ascii=False))
    print("variance     :", json.dumps(analysis["variance"], ensure_ascii=False))
    print("\nby_host:")
    for name, value in analysis["by_host"].items():
        print("  ", name, json.dumps(value, ensure_ascii=False))
    print("\nfailures_by_signature:")
    for name, value in analysis["failures_by_signature"].items():
        print("  ", name, json.dumps(value, ensure_ascii=False))
    print("\nslowest_reads:")
    for row in analysis["slowest_reads"]:
        print("  ", json.dumps(row, ensure_ascii=False))
    print("\nverdict:", json.dumps(report["verdict"], ensure_ascii=False))

    if args.output:
        io.open(args.output, "w", encoding="utf-8", newline="\n").write(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        )
        print("\nwrote", args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
