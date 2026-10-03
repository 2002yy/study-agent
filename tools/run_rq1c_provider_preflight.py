"""Fast RQ1-C provider preflight (diagnostic, not qualification evidence).

Runs a couple of representative queries through the production research
multi-provider policy to decide whether the local environment is worth a full
12-case Live12 run. It never writes raw query text, page content, or provider
messages; only bounded provider outcomes and a decision are recorded.

Decisions:
- ``qualified``   : every enabled provider returned results.
- ``degraded``    : at least one provider returned results, but some failed,
                    blocked, or were skipped (e.g. Bing-only environment).
- ``unqualified`` : no enabled provider returned any results at all.

Exit code: 0 for qualified/degraded, 2 for unqualified.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

from src.web.research.provider_search import (  # noqa: E402
    PROVIDER_ORDER,
    ResearchProviderSearch,
)

DEFAULT_QUERIES = (
    "Docker Hub unauthenticated pull rate limit official documentation",
    "Python 3.13 release date official announcement",
)
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "research_quality" / "RQ1C_PROVIDER_PREFLIGHT.json"
SCHEMA_VERSION = "rq1c-provider-preflight-v1"


def _provider_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for outcome in payload.get("provider_outcomes", []):
        if not isinstance(outcome, dict):
            continue
        rows.append(
            {
                "provider": outcome.get("provider"),
                "status": outcome.get("status"),
                "reason": outcome.get("reason"),
                "attempts": outcome.get("attempts"),
                "result_count": outcome.get("result_count"),
            }
        )
    return rows


def run_preflight(
    *,
    queries: tuple[str, ...] = DEFAULT_QUERIES,
    output_path: Path | None = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    load_dotenv(REPO_ROOT / ".env")
    search = ResearchProviderSearch()
    enabled = tuple(
        provider for provider in PROVIDER_ORDER if search._provider_enabled(provider)
    )

    query_rows: list[dict[str, Any]] = []
    result_bearing_providers: set[str] = set()
    for query in queries:
        payload = search.search_exact(query, max_results=5)
        rows = _provider_rows(payload)
        for row in rows:
            if row["status"] == "ok" and (row["result_count"] or 0) > 0:
                result_bearing_providers.add(str(row["provider"]))
        query_rows.append(
            {
                "query_sha256": payload.get("provider_audits", [{}])[0].get("query_sha256", "")
                if payload.get("provider_audits")
                else "",
                "status": payload.get("status"),
                "reason": payload.get("reason"),
                "providers": rows,
            }
        )

    if not result_bearing_providers:
        decision = "unqualified"
    elif result_bearing_providers == set(enabled):
        decision = "qualified"
    else:
        decision = "degraded"

    artifact = {
        "schema_version": SCHEMA_VERSION,
        "decision": decision,
        "enabled_providers": list(enabled),
        "result_bearing_providers": sorted(result_bearing_providers),
        "degraded_providers": list(search.degraded_providers()),
        "queries": query_rows,
    }
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return artifact


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main() -> int:
    args = _parser().parse_args()
    artifact = run_preflight(output_path=args.output.resolve())
    print(
        json.dumps(
            {
                "decision": artifact["decision"],
                "enabled_providers": artifact["enabled_providers"],
                "result_bearing_providers": artifact["result_bearing_providers"],
                "degraded_providers": artifact["degraded_providers"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if artifact["decision"] in {"qualified", "degraded"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
