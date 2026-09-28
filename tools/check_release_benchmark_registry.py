"""Validate release registry and hidden gold without executing cases."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.evals.release_benchmark_plan import load_release_benchmark_plan  # noqa: E402
from src.evals.release_benchmark_registry import (  # noqa: E402
    admission_report,
    load_gold,
    load_registry,
)

FIXTURES = REPO_ROOT / "tests" / "fixtures" / "release_benchmark"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=FIXTURES / "plan_v1.json")
    parser.add_argument("--registry", type=Path, default=FIXTURES / "registry_v1.json")
    parser.add_argument("--gold", type=Path, default=FIXTURES / "gold_v1.json")
    args = parser.parse_args()
    plan = load_release_benchmark_plan(args.plan)
    registry = load_registry(args.registry, REPO_ROOT, plan)
    gold = load_gold(args.gold, registry)
    print(json.dumps(admission_report(plan, registry, gold), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
