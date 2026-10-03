"""Offline, read-only readiness check for the release benchmark plan."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.evals.release_benchmark_plan import (  # noqa: E402
    load_release_benchmark_plan,
    readiness_report,
)

DEFAULT_PLAN = REPO_ROOT / "tests" / "fixtures" / "release_benchmark" / "plan_v1.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    args = parser.parse_args()
    plan = load_release_benchmark_plan(args.plan)
    print(json.dumps(readiness_report(plan, REPO_ROOT), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
