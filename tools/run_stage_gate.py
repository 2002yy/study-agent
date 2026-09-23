"""§109 Staged Regression Policy runner (thin manifest reader, not a framework).

Resolves a named L1 impact set or L2 stage gate from ``tests/stage_gates.json``
and hands the paths to pytest. It exists so the policy has one fixed command
instead of a hand-typed argument list that drifts.

Usage::

    python tools/run_stage_gate.py --list
    python tools/run_stage_gate.py --impact-set a3_browser
    python tools/run_stage_gate.py --stage p2-a-retrieval-stack
    python tools/run_stage_gate.py --stage p2-a-retrieval-stack --print-paths
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = REPO_ROOT / "tests" / "stage_gates.json"


def load_manifest(path: Path = MANIFEST) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "staged-regression-policy-v1":
        raise SystemExit(f"unexpected manifest schema: {payload.get('schema_version')!r}")
    return payload


def resolve(payload: dict[str, Any], *, impact_set: str = "", stage: str = "") -> list[str]:
    if bool(impact_set) == bool(stage):
        raise SystemExit("pass exactly one of --impact-set / --stage")
    if impact_set:
        sets = payload.get("impact_sets") or {}
        if impact_set not in sets:
            raise SystemExit(f"unknown impact set: {impact_set!r}")
        paths = list(sets[impact_set])
    else:
        gates = payload.get("stage_gates") or {}
        if stage not in gates:
            raise SystemExit(f"unknown stage gate: {stage!r}")
        paths = list(gates[stage])

    missing = [item for item in paths if not (REPO_ROOT / item).exists()]
    if missing:
        raise SystemExit("manifest references missing paths: " + ", ".join(missing))
    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--impact-set", default="")
    parser.add_argument("--stage", default="")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--print-paths", action="store_true")
    args, extra = parser.parse_known_args(argv)

    payload = load_manifest()

    if args.list:
        for name in (payload.get("impact_sets") or {}):
            print(f"impact-set {name}")
        for name in (payload.get("stage_gates") or {}):
            print(f"stage      {name}")
        return 0

    paths = resolve(payload, impact_set=args.impact_set, stage=args.stage)
    if args.print_paths:
        print(" ".join(paths))
        return 0
    return subprocess.call([sys.executable, "-m", "pytest", *paths, *extra])


if __name__ == "__main__":
    raise SystemExit(main())
