# -*- coding: utf-8 -*-
"""F2-O4a: checkpoint cost characterisation (read-only).

One question: is the 0.9-2.9s spent in checkpoints "persistence cost that must be
paid every time" or "repeated writing / too-frequent writing / mergeable work"?

It never debounces, coalesces or skips a checkpoint, and never touches durability
or recovery semantics. It only reads what the run already recorded.
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
        timing = metrics.get("checkpoint_timing")
        if not isinstance(timing, list) or not timing:
            skipped.append(path)
            continue
        entries = [
            {
                "ordinal": int(_num(row.get("ordinal")) or 0),
                "wall_ms": _num(row.get("wall_ms")) or 0.0,
                "stage": str(row.get("stage") or ""),
                "caller": str(row.get("caller") or ""),
                "phase": str(row.get("phase") or ""),
                "since_previous_ms": _num(row.get("since_previous_ms")),
                "serialize_ms": _num(row.get("serialize_ms")) or 0.0,
                "write_ms": _num(row.get("write_ms")) or 0.0,
                "load_ms": _num(row.get("load_ms")) or 0.0,
                "prep_ms": _num(row.get("prep_ms")) or 0.0,
                "repo_call_ms": _num(row.get("repo_call_ms")) or 0.0,
                "repo_other_ms": _num(row.get("repo_other_ms")) or 0.0,
                "hash_ms": _num(row.get("hash_ms")) or 0.0,
                "bytes_total": _num(row.get("bytes_total")) or 0.0,
                "bytes_by_section": {
                    str(k): int(_num(v) or 0)
                    for k, v in (row.get("bytes_by_section") or {}).items()
                },
                "changed_sections": list(row.get("changed_sections") or []),
                "changed_bytes": _num(row.get("changed_bytes")) or 0.0,
                "unchanged_bytes": _num(row.get("unchanged_bytes")) or 0.0,
                "conflicts": int(_num(row.get("conflicts")) or 0),
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
                "unattributed_ms": sum(
                    _num(entry.get("unattributed_ms")) or 0.0
                    for entry in (metrics.get("wave_timeline") or [])
                    if isinstance(entry, dict)
                ),
                "entries": entries,
            }
        )
    return runs, skipped


def run_summary(run: dict[str, Any]) -> dict[str, Any]:
    entries = run["entries"]
    walls = [e["wall_ms"] for e in entries]
    changed = [e["changed_bytes"] for e in entries]
    unchanged = [e["unchanged_bytes"] for e in entries]
    repeated = [e for e in entries if e["unchanged_bytes"] > 0]
    return {
        "artifact": run["artifact"],
        "checkpoints": len(entries),
        "wall_total_ms": round(sum(walls), 1),
        "wall_mean_ms": round(_mean(walls), 1),
        "wall_median_ms": round(_median(walls), 1),
        "wall_max_ms": round(max(walls), 1) if walls else 0.0,
        "serialize_total_ms": round(sum(e["serialize_ms"] for e in entries), 1),
        "write_total_ms": round(sum(e["write_ms"] for e in entries), 1),
        "bytes_total": int(sum(e["bytes_total"] for e in entries)),
        "bytes_mean": int(_mean([e["bytes_total"] for e in entries])),
        "changed_bytes_total": int(sum(changed)),
        "unchanged_bytes_total": int(sum(unchanged)),
        "fully_repeated": sum(1 for e in entries if not e["changed_sections"]),
        "partially_repeated": sum(1 for e in repeated if e["changed_sections"]),
        "conflicts": sum(e["conflicts"] for e in entries),
        "share_of_run": (
            round(sum(walls) / (run["elapsed_seconds"] * 1000.0), 3)
            if run["elapsed_seconds"]
            else None
        ),
        "unattributed_ms": round(run["unattributed_ms"], 1),
        "share_of_unattributed": (
            round(sum(walls) / run["unattributed_ms"], 3)
            if run["unattributed_ms"]
            else None
        ),
    }


def analyse(runs: list[dict[str, Any]]) -> dict[str, Any]:
    entries = [e for run in runs for e in run["entries"]]
    walls = [e["wall_ms"] for e in entries]
    serializes = [e["serialize_ms"] for e in entries]
    writes = [e["write_ms"] for e in entries]
    loads = [e["load_ms"] for e in entries]
    preps = [e["prep_ms"] for e in entries]
    repo_calls = [e["repo_call_ms"] for e in entries]
    repo_others = [e["repo_other_ms"] for e in entries]
    hashes = [e["hash_ms"] for e in entries]
    bytes_totals = [e["bytes_total"] for e in entries]
    unchanged = [e["unchanged_bytes"] for e in entries]
    changed = [e["changed_bytes"] for e in entries]
    gaps = [
        e["since_previous_ms"]
        for e in entries
        if e["since_previous_ms"] is not None
    ]
    fully_repeated = [e for e in entries if not e["changed_sections"]]
    by_caller: dict[str, dict[str, Any]] = {}
    for entry in entries:
        bucket = by_caller.setdefault(
            entry["caller"] or "(unknown)",
            {"n": 0, "wall": [], "unchanged": [], "bytes": []},
        )
        bucket["n"] += 1
        bucket["wall"].append(entry["wall_ms"])
        bucket["unchanged"].append(entry["unchanged_bytes"])
        bucket["bytes"].append(entry["bytes_total"])
    by_phase: dict[str, dict[str, Any]] = {}
    for entry in entries:
        bucket = by_phase.setdefault(
            entry["phase"] or "(none)", {"n": 0, "wall": [], "bytes": [], "unchanged": []}
        )
        bucket["n"] += 1
        bucket["wall"].append(entry["wall_ms"])
        bucket["bytes"].append(entry["bytes_total"])
        bucket["unchanged"].append(entry["unchanged_bytes"])
    total_bytes = sum(bytes_totals) or 0.0
    return {
        "checkpoints": len(entries),
        "wall_ms": {
            "mean": round(_mean(walls), 1),
            "median": round(_median(walls), 1),
            "stdev": round(_stdev(walls), 1),
            "min": min(walls) if walls else None,
            "max": max(walls) if walls else None,
            "total": round(sum(walls), 1),
        },
        "serialize_ms": {
            "mean": round(_mean(serializes), 1),
            "median": round(_median(serializes), 1),
            "total": round(sum(serializes), 1),
        },
        "write_ms": {
            "mean": round(_mean(writes), 1),
            "median": round(_median(writes), 1),
            "total": round(sum(writes), 1),
            "max": max(writes) if writes else None,
            "p90": _percentile(writes, 0.90),
            "p99": _percentile(writes, 0.99),
            "over_50ms": sum(1 for value in writes if value > 50.0),
            "over_50ms_share_of_write": (
                round(
                    sum(value for value in writes if value > 50.0) / sum(writes), 3
                )
                if sum(writes)
                else None
            ),
            "top_1pct_share_of_write": _top_share(writes, 0.01),
        },
        "hash_ms_total": round(sum(hashes), 1),
        "share_of_wall": {
            "serialize": round(sum(serializes) / sum(walls), 3) if sum(walls) else None,
            "write": round(sum(writes) / sum(walls), 3) if sum(walls) else None,
            "load": round(sum(loads) / sum(walls), 3) if sum(walls) else None,
            "repo_other": round(sum(repo_others) / sum(walls), 3) if sum(walls) else None,
            "prep": round(sum(preps) / sum(walls), 3) if sum(walls) else None,
            "instrumentation": round(sum(hashes) / sum(walls), 3) if sum(walls) else None,
        },
        "decomposition_ms": {
            "total_wall": round(sum(walls), 1),
            "prep_total": round(sum(preps), 1),
            "repo_total": round(sum(repo_calls), 1),
            "load_total": round(sum(loads), 1),
            "serialize_total": round(sum(serializes), 1),
            "write_total": round(sum(writes), 1),
            "repo_other_total": round(sum(repo_others), 1),
        },
        "bytes": {
            "mean": round(_mean(bytes_totals), 1),
            "median": round(_median(bytes_totals), 1),
            "max": max(bytes_totals) if bytes_totals else None,
            "total": int(total_bytes),
        },
        "changed_vs_previous": {
            "changed_bytes_total": int(sum(changed)),
            "unchanged_bytes_total": int(sum(unchanged)),
            "unchanged_share": (
                round(sum(unchanged) / total_bytes, 3) if total_bytes else None
            ),
            "fully_repeated_checkpoints": len(fully_repeated),
            "fully_repeated_share": (
                round(len(fully_repeated) / len(entries), 3) if entries else None
            ),
        },
        "gaps_ms": {
            "mean": round(_mean(gaps), 1),
            "median": round(_median(gaps), 1),
            "min": min(gaps) if gaps else None,
            "p10": _percentile(gaps, 0.10),
        },
        "correlations": {
            "wall~bytes": _round(_pearson(walls, bytes_totals)),
            "wall~serialize": _round(_pearson(walls, serializes)),
            "wall~write": _round(_pearson(walls, writes)),
            "serialize~bytes": _round(_pearson(serializes, bytes_totals)),
            "write~bytes": _round(_pearson(writes, bytes_totals)),
        },
        "by_caller": {
            name: {
                "n": value["n"],
                "wall_mean": round(_mean(value["wall"]), 1),
                "wall_total": round(sum(value["wall"]), 1),
                "unchanged_share": (
                    round(sum(value["unchanged"]) / sum(value["bytes"]), 3)
                    if sum(value["bytes"])
                    else None
                ),
            }
            for name, value in sorted(
                by_caller.items(), key=lambda item: -item[1]["n"]
            )
        },
        "by_phase": {
            name: {
                "n": value["n"],
                "wall_mean": round(_mean(value["wall"]), 1),
                "wall_total": round(sum(value["wall"]), 1),
                "unchanged_share": (
                    round(sum(value["unchanged"]) / sum(value["bytes"]), 3)
                    if sum(value["bytes"])
                    else None
                ),
            }
            for name, value in sorted(
                by_phase.items(), key=lambda item: -item[1]["n"]
            )
        },
    }


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1)))))
    return round(ordered[index], 1)


def _top_share(values: list[float], fraction: float) -> float | None:
    """Share of the total held by the slowest ``fraction`` of the samples."""

    if not values or sum(values) == 0:
        return None
    ordered = sorted(values, reverse=True)
    count = max(1, int(round(fraction * len(ordered))))
    return round(sum(ordered[:count]) / sum(ordered), 3)


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 3)


def verdict(analysis: dict[str, Any]) -> dict[str, Any]:
    share = analysis["share_of_wall"]
    changed = analysis["changed_vs_previous"]
    gaps = analysis["gaps_ms"]
    serial_share = share.get("serialize") or 0.0
    write_share = share.get("write") or 0.0
    corr_bytes = analysis["correlations"].get("wall~bytes")
    unchanged_share = changed.get("unchanged_share") or 0.0
    repeated_share = changed.get("fully_repeated_share") or 0.0

    if unchanged_share >= 0.5 and (repeated_share >= 0.25 or (gaps.get("p10") or 1e9) < 250):
        call = "repetition_or_frequency_worth_o4b"
    elif serial_share >= 0.4:
        call = "serialization_dominated_worth_o4b"
    elif (corr_bytes or 0) >= 0.7 and unchanged_share < 0.5:
        call = "necessary_persistence_cost"
    else:
        call = "small_and_not_clearly_redundant"
    write_stats = analysis["write_ms"]
    write_jitter = bool(
        (write_stats.get("max") or 0) >= 100.0
        and (write_stats.get("median") or 0) > 0
        and (write_stats.get("max") or 0) >= 10 * (write_stats.get("median") or 1)
        and (corr_bytes or 0) < 0.3
    )
    return {
        "call": call,
        "write_jitter": write_jitter,
        "write_ms_median": write_stats.get("median"),
        "write_ms_max": write_stats.get("max"),
        "write_ms_p99": write_stats.get("p99"),
        "over_50ms": write_stats.get("over_50ms"),
        "over_50ms_share_of_write": write_stats.get("over_50ms_share_of_write"),
        "top_1pct_share_of_write": write_stats.get("top_1pct_share_of_write"),
        "serialize_share_of_wall": serial_share,
        "write_share_of_wall": write_share,
        "instrumentation_share_of_wall": share.get("instrumentation"),
        "wall~bytes": corr_bytes,
        "unchanged_bytes_share": unchanged_share,
        "fully_repeated_checkpoint_share": repeated_share,
        "median_gap_ms": gaps.get("median"),
        "p10_gap_ms": gaps.get("p10"),
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
        paths = sorted(glob.glob("docs/research_quality/O4.*.json"))

    runs, skipped = load_runs(paths)
    analysis = analyse(runs)
    report = {
        "schema": "f2-o4a-checkpoint-cost-v1",
        "artifacts": [os.path.basename(p) for p in paths],
        "skipped": [os.path.basename(p) for p in skipped],
        "runs": [run_summary(run) for run in runs],
        "analysis": analysis,
        "verdict": verdict(analysis),
    }

    print(f"runs: {len(runs)}  checkpoints: {analysis['checkpoints']}")
    print(
        f"\n  {'artifact':22s} {'ckpts':>5s} {'wall_tot':>9s} {'mean':>7s} {'max':>7s} "
        f"{'ser_tot':>8s} {'wr_tot':>8s} {'bytes_tot':>10s} {'unchanged':>10s} {'rept':>5s} {'of_run':>7s}"
    )
    for run in report["runs"]:
        print(
            f"  {run['artifact']:22s} {run['checkpoints']:>5d} {run['wall_total_ms']:>9.0f} "
            f"{run['wall_mean_ms']:>7.0f} {run['wall_max_ms']:>7.0f} "
            f"{run['serialize_total_ms']:>8.0f} {run['write_total_ms']:>8.0f} "
            f"{run['bytes_total']:>10d} {run['unchanged_bytes_total']:>10d} "
            f"{run['fully_repeated']:>5d} {str(run['share_of_run']):>7s}"
        )
    print("\npooled wall   :", json.dumps(analysis["wall_ms"], ensure_ascii=False))
    print("pooled serialize:", json.dumps(analysis["serialize_ms"], ensure_ascii=False))
    print("pooled write  :", json.dumps(analysis["write_ms"], ensure_ascii=False))
    print("share_of_wall :", json.dumps(analysis["share_of_wall"], ensure_ascii=False))
    print("decomposition :", json.dumps(analysis["decomposition_ms"], ensure_ascii=False))
    print("bytes         :", json.dumps(analysis["bytes"], ensure_ascii=False))
    print("changed_vs_prev:", json.dumps(analysis["changed_vs_previous"], ensure_ascii=False))
    print("gaps_ms       :", json.dumps(analysis["gaps_ms"], ensure_ascii=False))
    print("correlations  :", json.dumps(analysis["correlations"], ensure_ascii=False))
    print("\nby_caller (top):")
    for name, value in list(analysis["by_caller"].items())[:8]:
        print("  ", name, json.dumps(value, ensure_ascii=False))
    print("\nby_phase:")
    for name, value in analysis["by_phase"].items():
        print("  ", name, json.dumps(value, ensure_ascii=False))
    print("\nverdict:", json.dumps(report["verdict"], ensure_ascii=False))

    if args.output:
        io.open(args.output, "w", encoding="utf-8", newline="\n").write(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        )
        print("\nwrote", args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
