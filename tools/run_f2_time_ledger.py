"""§F2 time ledger: attribute a run's wall clock to named segments.

Offline, diagnostic only - it reads existing artifacts and never changes any
count, timeout, selector or retry policy. Segments are taken from the fields the
runtime already records, so a fast/slow delta can be decomposed before any new
instrumentation is added:

  research window      metrics.research_window
  phases               metrics.phase_seconds (search/assessment/read/extraction)
  B1 critical path     metrics.b1_critical_path (start -> admission)
  late tail            metrics.late_assessment_tail
  selector             metrics.selection_authority (per-call latency_ms)
  retry                metrics.read_retry (attempts/retries counts)
  inventory            metrics.inventory_fetch
  finalization         finalization_breakdown (answer stage, total)

Usage::

    python -m tools.run_f2_time_ledger --artifacts a.json b.json ...
"""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
RESEARCH_QUALITY = REPO_ROOT / "docs" / "research_quality"


def _metrics(case: Mapping[str, Any]) -> Mapping[str, Any]:
    value = case.get("metrics")
    return value if isinstance(value, Mapping) else {}


def _sum_phase(metrics: Mapping[str, Any], key: str) -> tuple[float, int]:
    phase = (metrics.get("phase_seconds") or {}).get(key)
    if not isinstance(phase, Mapping):
        return 0.0, 0
    return float(phase.get("seconds") or 0.0), int(phase.get("calls") or 0)


def ledger_row(name: str, case: Mapping[str, Any]) -> dict[str, Any]:
    metrics = _metrics(case)
    row: dict[str, Any] = {
        "run": name,
        "elapsed": case.get("elapsed_seconds"),
        "gate": (case.get("gate") or {}).get("status"),
    }
    window = metrics.get("research_window") or {}
    row["research_elapsed"] = window.get("research_elapsed_seconds")
    row["research_exhausted"] = window.get("exhausted")

    for phase in ("search", "assessment", "read", "extraction"):
        seconds, calls = _sum_phase(metrics, phase)
        row[f"{phase}_s"] = round(seconds, 2)
        row[f"{phase}_calls"] = calls

    path = (metrics.get("b1_critical_path") or [{}])[0]
    row["b1_start_s"] = (
        round(float(path["t_started_ms"]) / 1000.0, 2) if path.get("t_started_ms") else None
    )
    row["b1_admission_s"] = path.get("admission_seconds")
    row["b1_segment_s"] = (
        round(float(path["critical_path_ms"]) / 1000.0, 1)
        if path.get("critical_path_ms")
        else None
    )

    tail = (metrics.get("late_assessment_tail") or [{}])[0]
    row["tail_cost_ms"] = (
        round(
            float(tail.get("t_tail_gate_ms") or 0) - float(tail.get("t_tail_selected_ms") or 0),
            1,
        )
        if tail.get("t_tail_selected_ms")
        else None
    )

    selectors = metrics.get("selection_authority") or []
    row["selector_s"] = round(
        sum(float(item.get("elapsed_ms") or 0) for item in selectors) / 1000.0, 2
    )
    row["selector_calls"] = len(selectors)

    retry = metrics.get("read_retry") or {}
    row["retry_attempts"] = retry.get("attempts")
    row["retry_retries"] = retry.get("retries")
    row["retry_skipped"] = retry.get("skipped_due_to_budget")

    inventory = metrics.get("inventory_fetch") or {}
    row["inventory_fetches"] = inventory.get("fetches")
    row["inventory_retries"] = inventory.get("retries")

    breakdown = case.get("finalization_breakdown") or {}
    row["answer_stage_s"] = breakdown.get("answer_stage_seconds")
    row["post_research_s"] = breakdown.get("post_research_projection_seconds")

    # attribution: named segments vs the research window
    named = sum(
        float(row.get(key) or 0.0)
        for key in ("search_s", "assessment_s", "read_s", "extraction_s", "selector_s")
    )
    row["named_segments_s"] = round(named, 2)
    if row["research_elapsed"]:
        row["unattributed_s"] = round(float(row["research_elapsed"]) - named, 2)
    return row


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", nargs="+", required=True)
    args = parser.parse_args(list(argv) if argv is not None else None)

    rows = []
    for name in args.artifacts:
        path = Path(name)
        if not path.is_absolute():
            path = RESEARCH_QUALITY / name
        case = json.loads(io.open(path, encoding="utf-8").read())["cases"][0]
        rows.append(ledger_row(path.name, case))

    header = (
        f"{'run':26s} {'elapsed':>7s} {'research':>8s} {'search':>6s} {'assess':>6s} "
        f"{'read':>6s} {'extract':>7s} {'selector':>8s} {'b1_adm':>7s} {'b1_seg':>7s} "
        f"{'named':>6s} {'unattr':>7s}"
    )
    print(header)
    for row in rows:
        print(
            f"{row['run']:26s} {str(row['elapsed']):>7s} {str(row['research_elapsed']):>8s} "
            f"{row['search_s']:>6.1f} {row['assessment_s']:>6.1f} {row['read_s']:>6.1f} "
            f"{row['extraction_s']:>7.1f} {row['selector_s']:>8.2f} "
            f"{str(row['b1_admission_s']):>7s} {str(row['b1_segment_s']):>7s} "
            f"{row['named_segments_s']:>6.1f} {str(row.get('unattributed_s')):>7s}"
        )

    fast = [r for r in rows if (r["b1_admission_s"] or 99) < 35]
    slow = [r for r in rows if (r["b1_admission_s"] or 0) >= 35]
    if fast and slow:
        print("\nfast (admission <35s) vs slow (>=35s) medians:")
        for key in (
            "search_s", "assessment_s", "read_s", "extraction_s", "selector_s",
            "b1_segment_s", "named_segments_s", "unattributed_s",
        ):
            fast_values = sorted(float(r[key] or 0.0) for r in fast)
            slow_values = sorted(float(r[key] or 0.0) for r in slow)
            fast_med = fast_values[len(fast_values) // 2]
            slow_med = slow_values[len(slow_values) // 2]
            print(f"  {key:20s} fast={fast_med:7.2f}  slow={slow_med:7.2f}  delta={slow_med - fast_med:+7.2f}")
    print("\nrows json:")
    print(json.dumps(rows, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
