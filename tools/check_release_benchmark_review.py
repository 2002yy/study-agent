"""Prepare a digest-bound review packet or verify a GitHub PR review live."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evals.release_benchmark_plan import load_release_benchmark_plan  # noqa: E402
from src.evals.release_benchmark_registry import load_gold, load_registry  # noqa: E402
from src.evals.release_benchmark_review import (  # noqa: E402
    build_review_packet,
    check_github_review,
    review_template,
)

FIXTURES = ROOT / "tests/fixtures/release_benchmark"


def _gh_api(endpoint: str, *, paginate: bool = False) -> Any:
    command = ["gh", "api", endpoint]
    if paginate:
        command.extend(["--paginate", "--slurp"])
    completed = subprocess.run(command, check=True, capture_output=True, text=True,
                               encoding="utf-8", cwd=ROOT, timeout=60)
    return json.loads(completed.stdout)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-id", action="append", dest="case_ids")
    parser.add_argument("--pr-number", type=int)
    parser.add_argument("--review-id", type=int)
    args = parser.parse_args()
    plan = load_release_benchmark_plan(FIXTURES / "plan_v1.json")
    registry = load_registry(FIXTURES / "registry_v1.json", ROOT, plan)
    gold = load_gold(FIXTURES / "gold_v1.json", registry)
    packet = build_review_packet(registry, gold, case_ids=args.case_ids)
    if args.review_id is None and args.pr_number is None:
        print(json.dumps({"packet": packet, "review_template": review_template(packet),
                          "admitted_release_cases": 0, "release_gate": "NO_GO"},
                         ensure_ascii=False, sort_keys=True))
        return
    if args.review_id is None or args.pr_number is None or args.review_id < 1 or args.pr_number < 1:
        parser.error("verification requires positive --pr-number and --review-id")
    local_sha = subprocess.run(["git", "rev-parse", "HEAD"], check=True,
                               capture_output=True, text=True, encoding="utf-8",
                               cwd=ROOT, timeout=10).stdout.strip()
    endpoint = f"repos/2002yy/study-agent/pulls/{args.pr_number}"
    pr = _gh_api(endpoint)
    pages = _gh_api(endpoint + "/reviews?per_page=100", paginate=True)
    if not isinstance(pages, list) or any(not isinstance(page, list) for page in pages):
        raise ValueError("GitHub review pagination was not complete")
    reviews = [review for page in pages for review in page]
    result = check_github_review(packet, pr, reviews,
                                 review_id=args.review_id, expected_head_sha=local_sha)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
