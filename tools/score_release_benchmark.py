"""Score bounded recorded observations; NO_GO until release gates are qualified."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.evals.release_benchmark_plan import load_release_benchmark_plan  # noqa: E402
from src.evals.release_benchmark_registry import load_gold, load_registry  # noqa: E402
from src.evals.release_benchmark_scoring import (  # noqa: E402
    load_recording,
    score_recordings,
)

FIXTURES = REPO_ROOT / "tests" / "fixtures" / "release_benchmark"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=FIXTURES / "plan_v1.json")
    parser.add_argument("--registry", type=Path, default=FIXTURES / "registry_v1.json")
    parser.add_argument("--gold", type=Path, default=FIXTURES / "gold_v1.json")
    parser.add_argument("--observation", type=Path, action="append", default=[])
    parser.add_argument("--expected-code-sha", help="Exact 40-character source HEAD for observations")
    args = parser.parse_args()
    if args.observation and not args.expected_code_sha:
        parser.error("--expected-code-sha is required with observations")
    plan = load_release_benchmark_plan(args.plan)
    registry = load_registry(args.registry, REPO_ROOT, plan)
    gold = load_gold(args.gold, registry)
    runs = tuple(load_recording(path, plan, registry, gold, args.expected_code_sha)
                 for path in args.observation)
    print(json.dumps(score_recordings(plan, registry, gold, runs), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
