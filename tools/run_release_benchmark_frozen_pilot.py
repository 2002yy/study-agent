"""Run one opt-in frozen text candidate through the real WebLookupService."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evals.release_benchmark_plan import load_release_benchmark_plan  # noqa: E402
from src.evals.release_benchmark_registry import load_registry  # noqa: E402
from src.evals.release_benchmark_replay import run_frozen_text_pilot  # noqa: E402


FIXTURES = ROOT / "tests/fixtures/release_benchmark"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-id", default="REL-F-TEXT-001")
    args = parser.parse_args()
    plan = load_release_benchmark_plan(FIXTURES / "plan_v1.json")
    registry = load_registry(FIXTURES / "registry_v1.json", ROOT, plan)
    case = next((item for item in registry.cases if item.case_id == args.case_id), None)
    if case is None:
        parser.error("unknown release candidate")
    print(json.dumps(run_frozen_text_pilot(case, ROOT), sort_keys=True))


if __name__ == "__main__":
    main()
