"""Read-only audit for the next stage: comparison questions, their side coverage, and whether any
recorded claim already states the comparison.

It answers two questions the evidence must settle before any fact-composition contract is designed:

1. how many recorded goals are true comparisons (sides, or a comparison-shaped question whose sides
   were never derived - a missed comparison is a wiring gap worth reporting);
2. among them, how many hold material for BOTH sides yet produced no claim that states a comparison
   (the composition candidates).

No network access, no model call: it reads the recorded product traces only.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

CONTRAST = ("区别", "不同", "相反", "而", "但", "相比", "差异")
#: comparison shapes that must produce sides even when the derivation misses them
COMPARISON_SHAPES = (r"有何不同", r"有什么区别", r"的区别", r"与.+不同的", r"对比")


def _is_comparison_question(question: str) -> bool:
    return any(re.search(shape, str(question or "")) for shape in COMPARISON_SHAPES)


def audit(product: Path) -> dict:
    goals: list[dict] = []
    missed: list[dict] = []
    for index in range(1, 7):
        path = product / f"q{index}.json"
        if not path.exists():
            continue
        trace = json.loads(path.read_text(encoding="utf-8"))
        question = str(trace.get("question") or "")
        extraction = trace.get("extraction_input") or {}
        recorded = extraction.get("goals") or {}
        has_sides = any(len((item or {}).get("sides") or ()) >= 2 for item in recorded.values())
        if not has_sides and _is_comparison_question(question):
            missed.append({"q": index, "question": question[:60],
                           "why": "comparison-shaped question with no derived sides"})
        for label, item in recorded.items():
            sides = [str(side) for side in (item or {}).get("sides") or ()]
            if len(sides) < 2:
                continue
            windows = (item or {}).get("windows") or []
            per_side = {side: sum(1 for w in windows
                                  if side in [str(n) for n in w.get("sides") or ()])
                        for side in sides}
            verdicts = [v for v in (trace.get("claim_verdicts") or []) if isinstance(v, dict)
                        and str(v.get("goal_id")) == str(label)]
            comparative = 0
            for verdict in verdicts:
                text = str(verdict.get("quote") or "") + str(verdict.get("claim") or "")
                if all(side in text for side in sides) and any(m in text for m in CONTRAST):
                    comparative += 1
            goals.append({"q": index, "goal": str(label)[:32], "sides": sides,
                          "windows_per_side": per_side, "claims": len(verdicts),
                          "comparative_claims": comparative,
                          "both_sides_covered": all(per_side.values())})
    return {
        "comparison_goals": goals,
        "composition_candidates": [g for g in goals
                                   if g["both_sides_covered"] and g["comparative_claims"] == 0],
        "missed_comparisons": missed,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--product", default=r"D:\study-agent-validation\M4C5\product")
    parser.add_argument("--json", default="")
    args = parser.parse_args()

    report = audit(Path(args.product))
    for goal in report["comparison_goals"]:
        print(json.dumps(goal, ensure_ascii=False))
    print("\n== COMPOSITION CANDIDATES (both sides covered, no comparative claim) ==")
    print(json.dumps(report["composition_candidates"], ensure_ascii=False, indent=1))
    print("\n== MISSED COMPARISONS (shape without derived sides) ==")
    print(json.dumps(report["missed_comparisons"], ensure_ascii=False, indent=1))
    if args.json:
        Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=1),
                                   encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
