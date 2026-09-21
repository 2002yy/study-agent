# -*- coding: utf-8 -*-
"""F2-O2: selector single-call latency characterisation (read-only).

Answers one question: is the selector's per-call latency spread driven by input
size / call position / purpose, or by external gateway/model latency jitter?

It never changes selector behaviour; it only reads artifacts.
"""

from __future__ import annotations

import argparse
import glob
import io
import json
import math
import os
from typing import Any

ROW_FIELDS = (
    "elapsed_ms",
    "model_wait_ms",
    "local_residual_ms",
    "input_chars",
    "response_chars",
    "input_tokens",
    "output_tokens",
    "input_size",
)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


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


def _slope(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 2:
        return None
    mx, my = _mean(xs), _mean(ys)
    denom = sum((x - mx) ** 2 for x in xs)
    if denom == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def load_rows(paths: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
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
        records = metrics.get("selection_authority")
        if not isinstance(records, list) or not records:
            skipped.append(path)
            continue
        run = str(case.get("run") or os.path.basename(path).replace(".json", ""))
        host = str(case.get("category") or "")
        position = 0
        for record in records:
            if not isinstance(record, dict):
                continue
            if not str(record.get("model") or ""):
                continue  # legacy/disabled window: no model call happened
            if record.get("elapsed_ms") is None:
                continue
            position += 1
            row: dict[str, Any] = {
                "run": run,
                "artifact": os.path.basename(path),
                "host": host,
                "wave_index": record.get("wave_index"),
                "claim_id": record.get("claim_id"),
                "position": position,
                "purpose": "research_selection_authority",
                "candidates": record.get("input_size"),
                "call_status": record.get("call_status"),
                "usable": record.get("usable"),
                "selection_source": record.get("selection_source"),
            }
            for field in ROW_FIELDS:
                row[field] = _num(record.get(field))
            rows.append(row)
    return rows, skipped


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    walls = [r["elapsed_ms"] for r in rows if r["elapsed_ms"] is not None]
    waits = [r["model_wait_ms"] for r in rows if r["model_wait_ms"] is not None]
    residuals = [
        r["local_residual_ms"] for r in rows if r["local_residual_ms"] is not None
    ]
    paired = [
        (r["elapsed_ms"], r["model_wait_ms"], r["local_residual_ms"])
        for r in rows
        if None not in (r["elapsed_ms"], r["model_wait_ms"], r["local_residual_ms"])
    ]
    out: dict[str, Any] = {
        "calls": len(rows),
        "wall_ms": {
            "mean": round(_mean(walls), 1),
            "stdev": round(_stdev(walls), 1),
            "min": min(walls) if walls else None,
            "max": max(walls) if walls else None,
        },
        "model_wait_ms": {
            "mean": round(_mean(waits), 1),
            "stdev": round(_stdev(waits), 1),
            "min": min(waits) if waits else None,
            "max": max(waits) if waits else None,
        },
        "local_residual_ms": {
            "mean": round(_mean(residuals), 1),
            "stdev": round(_stdev(residuals), 1),
            "min": min(residuals) if residuals else None,
            "max": max(residuals) if residuals else None,
        },
    }
    if paired:
        w = [p[0] for p in paired]
        m = [p[1] for p in paired]
        r = [p[2] for p in paired]
        out["pairwise"] = {
            "n": len(paired),
            "corr_wall_model_wait": _round(_pearson(w, m)),
            "corr_wall_residual": _round(_pearson(w, r)),
            "corr_model_wait_residual": _round(_pearson(m, r)),
            "var_wall": round(_variance(w), 1),
            "var_model_wait": round(_variance(m), 1),
            "var_residual": round(_variance(r), 1),
            "model_wait_share_of_wall_mean": _round(
                _mean(m) / _mean(w) if _mean(w) else None
            ),
        }
    return out


def _variance(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = _mean(values)
    return sum((v - mean) ** 2 for v in values) / (len(values) - 1)


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 3)


def by_group(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(str(row.get(key)), []).append(row)
    out: dict[str, Any] = {}
    for name, items in sorted(groups.items()):
        walls = [r["elapsed_ms"] for r in items if r["elapsed_ms"] is not None]
        waits = [r["model_wait_ms"] for r in items if r["model_wait_ms"] is not None]
        residuals = [
            r["local_residual_ms"] for r in items if r["local_residual_ms"] is not None
        ]
        out[name] = {
            "n": len(items),
            "wall_mean": round(_mean(walls), 1),
            "wall_min": min(walls) if walls else None,
            "wall_max": max(walls) if walls else None,
            "model_wait_mean": round(_mean(waits), 1),
            "residual_mean": round(_mean(residuals), 1),
            "residual_max": max(residuals) if residuals else None,
            "candidates_mean": round(
                _mean([r["candidates"] for r in items if r["candidates"] is not None]), 1
            ),
            "input_chars_mean": round(
                _mean([r["input_chars"] for r in items if r["input_chars"] is not None]),
                1,
            ),
        }
    return out


def relations(rows: list[dict[str, Any]]) -> dict[str, Any]:
    pairs = {
        "latency~input_chars": ("input_chars", "elapsed_ms"),
        "latency~candidates": ("candidates", "elapsed_ms"),
        "latency~position": ("position", "elapsed_ms"),
        "latency~response_chars": ("response_chars", "elapsed_ms"),
        "model_wait~input_chars": ("input_chars", "model_wait_ms"),
        "residual~input_chars": ("input_chars", "local_residual_ms"),
    }
    out: dict[str, Any] = {}
    for name, (x_key, y_key) in pairs.items():
        xs, ys = [], []
        for row in rows:
            x, y = row.get(x_key), row.get(y_key)
            if x is None or y is None:
                continue
            xs.append(float(x))
            ys.append(float(y))
        out[name] = {
            "n": len(xs),
            "pearson": _round(_pearson(xs, ys)),
            "slope_per_unit": _round(_slope(xs, ys)),
        }
    return out


def verdict(summary: dict[str, Any], groups: dict[str, Any]) -> dict[str, Any]:
    pairwise = summary.get("pairwise") or {}
    corr_wall_wait = pairwise.get("corr_wall_model_wait")
    residual = summary.get("local_residual_ms") or {}
    wall = summary.get("wall_ms") or {}
    positions = {k: v for k, v in (groups.get("by_position") or {}).items()}
    wait = summary.get("model_wait_ms") or {}

    residual_stable = bool(
        residual.get("max") is not None
        and wall.get("max") is not None
        and residual.get("stdev") is not None
        and wall.get("stdev") is not None
        and residual["stdev"] <= max(25.0, 0.25 * (wall["stdev"] or 0.0))
    )
    wait_carries_wall = bool(
        corr_wall_wait is not None and corr_wall_wait >= 0.8
    ) or bool(
        (wait.get("max") or 0) > 0
        and (wall.get("max") or 0) > 0
        and (wait.get("max") or 0) >= 0.7 * (wall.get("max") or 0)
    )
    position_spread = None
    if positions:
        means = [v["wall_mean"] for v in positions.values() if v.get("wall_mean")]
        if means:
            position_spread = round(max(means) - min(means), 1)

    if wait_carries_wall and residual_stable:
        call = "external_latency_not_locally_recoverable"
    elif position_spread is not None and position_spread >= 0.4 * (wall.get("max") or 1):
        call = "position_specific_path"
    else:
        call = "inconclusive_needs_more_samples"
    return {
        "call": call,
        "wait_carries_wall": wait_carries_wall,
        "residual_stable": residual_stable,
        "position_spread_ms": position_spread,
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
        paths = sorted(glob.glob("docs/research_quality/O2.*.json"))

    rows, skipped = load_rows(paths)
    summary = summarise(rows)
    groups = {
        "by_position": by_group(rows, "position"),
        "by_wave": by_group(rows, "wave_index"),
        "by_host": by_group(rows, "host"),
        "by_purpose": by_group(rows, "purpose"),
    }
    report = {
        "schema": "f2-o2-selector-latency-v1",
        "artifacts": [os.path.basename(p) for p in paths],
        "skipped": [os.path.basename(p) for p in skipped],
        "summary": summary,
        "groups": groups,
        "relations": relations(rows),
        "verdict": verdict(summary, groups),
        "rows": rows,
    }

    print("calls:", summary["calls"])
    print("wall     :", json.dumps(summary.get("wall_ms"), ensure_ascii=False))
    print("modelwait:", json.dumps(summary.get("model_wait_ms"), ensure_ascii=False))
    print("residual :", json.dumps(summary.get("local_residual_ms"), ensure_ascii=False))
    print("pairwise :", json.dumps(summary.get("pairwise"), ensure_ascii=False))
    print("\nby_position:")
    for name, value in groups["by_position"].items():
        print("  ", name, json.dumps(value, ensure_ascii=False))
    print("\nby_host:")
    for name, value in groups["by_host"].items():
        print("  ", name, json.dumps(value, ensure_ascii=False))
    print("\nrelations:")
    for name, value in report["relations"].items():
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
