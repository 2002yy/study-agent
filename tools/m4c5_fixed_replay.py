"""Fixed replay for M4-C5: judge the criteria on frozen material, never on a live run.

It answers the two questions the review separated:

1. criteria stability - on the SAME recorded bodies, does the selector return the same windows
   (legacy path vs qualified path vs qualified+label), and does any goal that once held support
   lose its windows?
2. model stability - the recorded extraction responses are re-read from the trace (no new model
   call), so the pipeline stage that consumed them can be inspected without a fresh generation.
   A stage that calls a model with a free prompt is NOT deterministic and is reported as such.

Usage:
    python tools/m4c5_fixed_replay.py [--product DIR] [--json OUT]

No network access and no model calls: it only reads the recorded product traces.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.web.research_claims import candidate_windows, evidence_windows  # noqa: E402


class _Body:
    """The smallest stand-in for a notebook body (text + diagnostics only)."""

    __slots__ = ("text", "url", "quality", "kind")

    def __init__(self, text: str, url: str, kind: str = "substantive") -> None:
        self.text = text
        self.url = url
        self.quality = {"prose_chars": len(text)}
        self.kind = kind


def _bodies(trace: dict) -> dict[str, _Body]:
    bodies: dict[str, _Body] = {}
    for index, raw in enumerate(trace.get("bodies") or []):
        text = str(raw.get("text") or "")
        if text:
            bodies[f"S{index}"] = _Body(text, str(raw.get("url") or ""))
    return bodies


def replay(product: Path) -> dict:
    rows = []
    model_rows = []
    for index in range(1, 7):
        path = product / f"q{index}.json"
        if not path.exists():
            continue
        trace = json.loads(path.read_text(encoding="utf-8"))
        bodies = _bodies(trace)
        goals = (trace.get("extraction_input") or {}).get("goals") or {}
        statuses = {label: (state or {}).get("status") for label, state in
                    ((trace.get("coverage_audit") or {}).get("sub_goals") or {}).items()}
        model_stage = {
            "question": index,
            "grounded": bool(goals),
            "response_recorded": bool((trace.get("extraction_input") or {}).get("raw_response")),
            "deterministic": bool(goals) and bool(bodies),
            "note": ("windows and verdicts are reproducible from the recorded material"
                     if goals and bodies else
                     "this trace recorded no goal/window input; the stage cannot be replayed"),
        }
        model_rows.append(model_stage)
        for label, payload in goals.items():
            terms = tuple(str(term) for term in (payload or {}).get("terms") or [])
            sides = tuple(str(side) for side in (payload or {}).get("sides") or [])
            if not terms:
                continue
            legacy = candidate_windows(terms, bodies, sides=sides)
            qualified0 = evidence_windows(terms, bodies, sides=sides)
            qualified = evidence_windows(terms, bodies, sides=sides, label=label)
            status = statuses.get(label)
            rows.append({
                "question": index, "goal": str(label)[:24], "status": status,
                "recorded": len((payload or {}).get("windows") or []),
                "legacy": len(legacy), "qualified0": len(qualified0), "qualified": len(qualified),
                "support_preserved": status != "supported" or len(qualified) > 0})
    return {
        "rows": rows,
        "criteria": {
            "goals": len(rows),
            "support_lost": [row for row in rows
                             if row["status"] == "supported" and not row["support_preserved"]],
            "windows_dropped_by_qualified": [row for row in rows
                                             if row["qualified"] < row["legacy"]],
            "unchanged": [row for row in rows if row["qualified"] == row["legacy"]],
        },
        "model": model_rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--product", default=r"D:\study-agent-validation\M4C5\product")
    parser.add_argument("--json", default="")
    args = parser.parse_args()

    report = replay(Path(args.product))
    for row in report["rows"]:
        print(json.dumps(row, ensure_ascii=False))
    print("\n== CRITERIA STABILITY ==")
    print(json.dumps(report["criteria"], ensure_ascii=False, indent=1))
    if args.json:
        Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=1),
                                   encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
