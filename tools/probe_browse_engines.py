"""Compare paired Browse search engines without calling a model or paid API.

Run on a machine with the ``browse`` CLI paired to a browser. The default
sample deliberately stays small to avoid automated-search challenges.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.web.browse_search import search_browse

FIXTURE = ROOT / "tests/fixtures/provider_routing/qp1c_queries_v1.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engines", default="google,duckduckgo,bing,brave")
    parser.add_argument("--case-ids", default="A01,A05")
    parser.add_argument("--timeout", type=float, default=12.0)
    args = parser.parse_args()
    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]
    selected = {name.strip() for name in args.case_ids.split(",")}
    engines = [name.strip() for name in args.engines.split(",")]
    observations = []
    for engine in engines:
        for case in cases:
            if case["id"] not in selected:
                continue
            rows, error = search_browse(case["query"], 8, args.timeout, engine=engine)
            observations.append({
                "engine": engine, "case_id": case["id"], "error": error,
                "count": len(rows), "top_results": [
                    {"title": row["title"], "url": row["url"]} for row in rows[:5]
                ],
            })
            # A human-action challenge cannot be bypassed by switching queries.
            if error == "browse:human_action_required":
                break
    print(json.dumps(observations, ensure_ascii=False, indent=2))
    return 0 if all(item["error"] != "browse:cli_unavailable" for item in observations) else 2


if __name__ == "__main__":
    raise SystemExit(main())
