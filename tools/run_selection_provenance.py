"""§37B-selection: read a run artifact's selection trace and name the drop.

Diagnostic-only extractor. It prints, for every observed candidate, the first
observed drop (``terminal_reason``) along the real chain
``provider -> normalized -> materialized -> deduped -> pool -> window ->
scheduler -> read`` plus the per-stage fields the runtime actually recorded.

The ``--targets`` annotation file is optional: when provided, the agreed
``likely_target`` candidates are reported with their own terminal reasons, which
is the §37B success criterion (a credible first drop per target).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

SCHEMA_VERSION = "research-selection-provenance-v1"


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _artifact_cases(artifact: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    cases = artifact.get("cases")
    if isinstance(cases, list):
        return [case for case in cases if isinstance(case, Mapping)]
    if "metrics" in artifact:
        return [artifact]
    return []


def load_selection_trace(artifact: Mapping[str, Any]) -> dict[str, Any]:
    """Collect per-case trace payloads; missing traces stay explicit."""

    result: dict[str, Any] = {"cases": [], "observed": False}
    for case in _artifact_cases(artifact):
        metrics = case.get("metrics")
        metrics = metrics if isinstance(metrics, Mapping) else {}
        trace = metrics.get("selection_trace")
        row = {
            "case_id": str(case.get("case_id") or case.get("id") or ""),
            "trace_present": isinstance(trace, Mapping),
            "entries": [],
        }
        if isinstance(trace, Mapping):
            result["observed"] = True
            entries = trace.get("entries")
            if isinstance(entries, list):
                row["entries"] = [
                    entry for entry in entries if isinstance(entry, Mapping)
                ]
        result["cases"].append(row)
    return result


def agreed_likely_targets(annotations: Mapping[str, Any]) -> list[str]:
    """Agreed likely_target URLs from either annotation payload shape."""

    rows = annotations.get("annotations")
    if not isinstance(rows, list):
        rows = annotations.get("merged")
    targets: list[str] = []
    for item in rows if isinstance(rows, list) else []:
        if not isinstance(item, Mapping):
            continue
        label = str(item.get("candidate_classification") or "")
        if not label:
            # Merged two-pass rows: the agreed label only exists when both
            # passes agree; disagreements never become targets.
            pass_a = str(item.get("pass_a") or "")
            pass_b = str(item.get("pass_b") or "")
            label = pass_a if pass_a and pass_a == pass_b else ""
        if label != "likely_target":
            continue
        url = str(item.get("canonical_url") or "").strip()
        if url:
            targets.append(url)
    seen: set[str] = set()
    unique: list[str] = []
    for url in targets:
        if url not in seen:
            seen.add(url)
            unique.append(url)
    return unique


def summarize(
    trace_payload: Mapping[str, Any],
    targets: Iterable[str] = (),
) -> dict[str, Any]:
    cases = trace_payload.get("cases") or []
    counts: dict[str, int] = {}
    rows: list[dict[str, Any]] = []
    for case in cases:
        for entry in case.get("entries") or []:
            reason = str(entry.get("terminal_reason") or "unobserved")
            counts[reason] = counts.get(reason, 0) + 1
            rows.append(
                {
                    "case_id": str(case.get("case_id") or ""),
                    "canonical_url": str(entry.get("canonical_url") or ""),
                    "terminal_reason": reason,
                    "seen_in_provider": bool(entry.get("seen_in_provider")),
                    "materialized": bool(entry.get("materialized")),
                    "deduped_survivor": bool(entry.get("deduped_survivor")),
                    "entered_candidate_pool": bool(entry.get("entered_candidate_pool")),
                    "entered_scheduler": bool(entry.get("entered_scheduler")),
                    "scheduler_rank": entry.get("scheduler_rank"),
                    "scheduler_decision": str(entry.get("scheduler_decision") or ""),
                    "read_dispatched": bool(entry.get("read_dispatched")),
                    "duplicate_merges": int(entry.get("duplicate_merges") or 0),
                    "filter_decision": str(entry.get("filter_decision") or ""),
                    "filter_reason": str(entry.get("filter_reason") or ""),
                    "read_skip_reason": str(entry.get("read_skip_reason") or ""),
                    "observed_drops": list(entry.get("observed_drops") or []),
                }
            )
    by_url = {row["canonical_url"]: row for row in rows}
    target_rows = []
    for target in targets:
        row = by_url.get(target)
        target_rows.append(
            {
                "canonical_url": target,
                "observed": row is not None,
                "terminal_reason": row["terminal_reason"] if row else "unobserved",
                "row": row,
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "trace_present": bool(trace_payload.get("observed")),
        "candidate_count": len(rows),
        "terminal_reason_counts": dict(sorted(counts.items())),
        "rows": rows,
        "targets": target_rows,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--targets", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    artifact = _load(args.artifact)
    trace_payload = load_selection_trace(artifact)
    targets: list[str] = []
    if args.targets is not None and args.targets.exists():
        targets = agreed_likely_targets(_load(args.targets))
    summary = summarize(trace_payload, targets)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    print(
        json.dumps(
            {
                "trace_present": summary["trace_present"],
                "candidate_count": summary["candidate_count"],
                "terminal_reason_counts": summary["terminal_reason_counts"],
                "targets": [
                    {
                        "canonical_url": row["canonical_url"],
                        "terminal_reason": row["terminal_reason"],
                    }
                    for row in summary["targets"]
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
