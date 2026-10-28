"""Provider Relevance Routing-1: capture and replay.

Two phases:

- ``--capture`` performs rate-limited real searches for the frozen query set and
  stores, per case and provider, the bounded result metadata (titles, URLs,
  source labels, latency, status, error codes). No model is called.
- ``--replay`` (the default) reads that capture and simulates four routing
  strategies offline: E0 first non-empty provider, E1 merge + dedupe, E2 merge +
  relevance ranking, E3 try another provider only when E0's top-3 has no
  relevant result.

Relevance here is a transparent keyword rule over multi-character anchors and
task-focus tokens. It measures retrieval relevance only; it is not evidence
support, not version correctness, and it is not the repository's
``source_assessment`` score (that score is not used as a routing gate because its
Chinese single-character overlap would call a dictionary page relevant).
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import statistics
import sys
import time
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

DEFAULT_QUERIES = (
    REPO_ROOT / "tests" / "fixtures" / "provider_routing" / "qp1c_queries_v1.json"
)
DEFAULT_CAPTURE = REPO_ROOT / "docs" / "research_quality" / "PROVIDER_ROUTING_CAPTURE.json"
DEFAULT_REPLAY = REPO_ROOT / "docs" / "research_quality" / "PROVIDER_ROUTING_REPLAY.json"

PROVIDERS = ("bing", "ddg")
PROVIDER_ENV: dict[str, dict[str, str]] = {
    "bing": {
        "WEB_ENABLE_SEARXNG": "true",
        "WEB_ENABLE_BING_RSS": "true",
        "WEB_ENABLE_DUCKDUCKGO": "false",
    },
    "ddg": {
        "WEB_ENABLE_SEARXNG": "false",
        "WEB_ENABLE_BING_RSS": "false",
        "WEB_ENABLE_DUCKDUCKGO": "true",
    },
}
ENV_KEYS = ("WEB_ENABLE_SEARXNG", "WEB_ENABLE_BING_RSS", "WEB_ENABLE_DUCKDUCKGO")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def _apply(mode: str) -> None:
    for key, value in PROVIDER_ENV[mode].items():
        os.environ[key] = value


def _anchor_tokens(case: dict[str, Any]) -> list[str]:
    # Single-character anchors are what made a dictionary entry look relevant.
    return [token for token in case["anchors"] if len(token.strip()) > 1]


def verdict(item: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    surface = " ".join(
        str(item.get(key) or "") for key in ("title", "url", "snippet")
    ).casefold()
    anchors = [token.casefold() for token in _anchor_tokens(case)]
    focus = [token.casefold() for token in case["focus"]]
    anchor_hits = [token for token in anchors if token in surface]
    focus_hits = [token for token in focus if token in surface]
    relevant = len(anchor_hits) >= 2 or (len(anchor_hits) >= 1 and bool(focus_hits))
    return {
        "relevant": relevant,
        "anchor_hits": anchor_hits,
        "focus_hits": focus_hits,
    }


def _dedupe(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for item in results:
        url = str(item.get("url") or "")
        if not url or url in seen:
            continue
        seen.add(url)
        rows.append(item)
    return rows


def capture(
    *, queries: Path, output: Path, limit: int, pace_ddg: float, pace_other: float
) -> dict[str, Any]:
    load_dotenv(REPO_ROOT / ".env")
    from src.web.tool_gateway import GeneralWebGateway

    document = json.loads(queries.read_text(encoding="utf-8"))
    original = {key: os.environ.get(key) for key in ENV_KEYS}
    artifact: dict[str, Any] = {
        "schema_version": "provider-routing-capture-v1",
        "started_at": _utc_now(),
        "queries_fixture": _display_path(queries),
        "query_set_version": document.get("schema_version"),
        "limit": limit,
        "cases": [],
        "scope": {"stores_page_bodies": False, "uses_model": False},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        gateway = GeneralWebGateway()
        for case in document["cases"]:
            record: dict[str, Any] = {
                "id": case["id"],
                "query": case["query"],
                "providers": {},
            }
            for mode in PROVIDERS:
                _apply(mode)
                started = time.monotonic()
                payload = gateway.search_detailed(case["query"], max_results=limit)
                elapsed = round(time.monotonic() - started, 2)
                results = [item for item in payload.get("results", []) if item.get("url")]
                record["providers"][mode] = {
                    "status": payload.get("status"),
                    "elapsed": elapsed,
                    "provider_errors": list(payload.get("provider_errors", [])),
                    "results": [
                        {
                            "title": str(item.get("title") or "")[:200],
                            "url": str(item.get("url") or "")[:300],
                            "source": str(item.get("source") or "")[:60],
                            "snippet_chars": len(str(item.get("snippet") or "")),
                        }
                        for item in results
                    ],
                }
                time.sleep(pace_ddg if mode == "ddg" else pace_other)
            artifact["cases"].append(record)
            output.write_text(
                json.dumps(artifact, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(f"[capture] {record['id']}: " + ", ".join(
                f"{mode}={len(record['providers'][mode]['results'])}" for mode in PROVIDERS
            ), flush=True)
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    artifact["completed_at"] = _utc_now()
    output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return artifact


def _rank(results: list[dict[str, Any]], case: dict[str, Any]) -> list[dict[str, Any]]:
    """Rank with a production-like scorer, never with the evaluation rule.

    Using `verdict()` here would rank by the very signal the metrics measure, so
    E2 would always score perfectly. `assess_sources` is the repository's own
    relevance scorer; its Chinese single-character overlap is a known weakness,
    which is exactly why it is reported rather than hidden.
    """

    from src.web.source_assessment import assess_sources

    assessed, _rejected = assess_sources(results, canonical_query=case["question"])
    scored: list[tuple[float, int, dict[str, Any]]] = []
    for index, record in enumerate(assessed):
        item = record.get("item") if isinstance(record, dict) else None
        if not isinstance(item, dict) or not item.get("url"):
            continue
        assessment = record.get("assessment") if isinstance(record, dict) else {}
        score = float((assessment or {}).get("relevance") or 0.0)
        scored.append((score, index, item))
    ranked = [item for _score, _index, item in sorted(scored, key=lambda row: (-row[0], row[1]))]
    # Anything the assessor dropped keeps its original relative order at the end.
    known = {str(item.get("url") or "") for item in ranked}
    ranked.extend(item for item in results if str(item.get("url") or "") not in known)
    return ranked


def _first_relevant_rank(results: list[dict[str, Any]], case: dict[str, Any]) -> int | None:
    for index, item in enumerate(results, start=1):
        if verdict(item, case)["relevant"]:
            return index
    return None


def _metrics(results: list[dict[str, Any]], case: dict[str, Any], limit: int) -> dict[str, Any]:
    top = results[:limit]
    rank = _first_relevant_rank(top, case)
    return {
        "relevant_rank": rank,
        "hit_at_3": bool(rank and rank <= 3),
        "hit_at_6": bool(rank),
        "mrr_at_6": round(1 / rank, 3) if rank else 0.0,
        "relevant_count": sum(1 for item in top if verdict(item, case)["relevant"]),
    }


def replay(*, capture_path: Path, output: Path, limit: int) -> dict[str, Any]:
    capture_doc = json.loads(capture_path.read_text(encoding="utf-8"))
    cases = {row["id"]: row for row in capture_doc["cases"]}
    queries = json.loads(DEFAULT_QUERIES.read_text(encoding="utf-8"))
    artifact: dict[str, Any] = {
        "schema_version": "provider-routing-replay-v1",
        "started_at": _utc_now(),
        "capture": _display_path(capture_path),
        "limit": limit,
        "strategies": {},
        "cases": [],
        "relevance_rule": {
            "anchors": "multi-character only; single-character anchors are ignored",
            "relevant": ">=2 anchors, or >=1 anchor plus a focus token",
            "not_measured": ["evidence_support", "version_correctness", "answer_quality"],
        },
    }
    for case in queries["cases"]:
        recorded = cases.get(case["id"])
        if recorded is None:
            continue
        providers = {mode: recorded["providers"][mode] for mode in PROVIDERS}
        row: dict[str, Any] = {"id": case["id"], "query": case["query"], "strategies": {}}

        # E0: first provider with any result.
        e0_mode = next((mode for mode in PROVIDERS if providers[mode]["results"]), None)
        e0_results = providers[e0_mode]["results"] if e0_mode else []
        e0_calls = PROVIDERS.index(e0_mode) + 1 if e0_mode else len(PROVIDERS)
        e0_latency = sum(
            providers[mode]["elapsed"] for mode in PROVIDERS[:e0_calls]
        )
        row["strategies"]["E0"] = {
            "providers": PROVIDERS[:e0_calls],
            "results": len(e0_results),
            "provider_calls": e0_calls,
            "latency": round(e0_latency, 2),
            **_metrics(e0_results, case, limit),
        }

        # E1: all providers, merge + dedupe, keep provider order.
        merged = _dedupe([*providers["bing"]["results"], *providers["ddg"]["results"]])
        row["strategies"]["E1"] = {
            "providers": list(PROVIDERS),
            "results": len(merged),
            "provider_calls": len(PROVIDERS),
            "latency": round(sum(providers[mode]["elapsed"] for mode in PROVIDERS), 2),
            **_metrics(merged, case, limit),
        }

        # E2: merge + relevance ranking.
        ranked = _rank(merged, case)
        row["strategies"]["E2"] = {
            "providers": list(PROVIDERS),
            "results": len(ranked),
            "provider_calls": len(PROVIDERS),
            "latency": round(sum(providers[mode]["elapsed"] for mode in PROVIDERS), 2),
            **_metrics(ranked, case, limit),
        }

        # E3: E0, then the next provider only when E0's top-3 has nothing relevant.
        if e0_mode and e0_mode != PROVIDERS[-1] and _first_relevant_rank(
            e0_results[:limit][:3], case
        ) is None:
            extra_mode = PROVIDERS[PROVIDERS.index(e0_mode) + 1]
            extra = providers[extra_mode]["results"]
            e3_results = _rank(_dedupe([*e0_results, *extra]), case)
            e3_calls = e0_calls + 1
            e3_latency = e0_latency + providers[extra_mode]["elapsed"]
            e3_triggered = True
        else:
            e3_results = e0_results
            e3_calls = e0_calls
            e3_latency = e0_latency
            e3_triggered = False
        row["strategies"]["E3"] = {
            "providers": list(PROVIDERS[:e3_calls]),
            "results": len(e3_results),
            "provider_calls": e3_calls,
            "latency": round(e3_latency, 2),
            "triggered_extra_provider": e3_triggered,
            **_metrics(e3_results, case, limit),
        }
        artifact["cases"].append(row)

    artifact["completed_at"] = _utc_now()
    artifact["summary"] = _summarise(artifact["cases"])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return artifact


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1)))))
    return round(ordered[index], 2)


def _summarise(cases: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {"cases": len(cases), "strategies": {}}
    for name in ("E0", "E1", "E2", "E3"):
        rows = [case["strategies"][name] for case in cases]
        latencies = [row["latency"] for row in rows]
        summary["strategies"][name] = {
            "hit_at_3": sum(1 for row in rows if row["hit_at_3"]),
            "hit_at_6": sum(1 for row in rows if row["hit_at_6"]),
            "mean_mrr_at_6": round(
                sum(row["mrr_at_6"] for row in rows) / max(1, len(rows)), 3
            ),
            "total_relevant": sum(row["relevant_count"] for row in rows),
            "provider_calls": sum(row["provider_calls"] for row in rows),
            "latency_p50": _percentile(latencies, 0.5),
            "latency_p90": _percentile(latencies, 0.9),
            "latency_mean": round(statistics.fmean(latencies), 2) if latencies else None,
        }
    summary["e3_extra_provider_calls"] = sum(
        1 for case in cases if case["strategies"]["E3"]["triggered_extra_provider"]
    )
    summary["negative_control_skips"] = sum(
        1
        for case in cases
        if not case["strategies"]["E3"]["triggered_extra_provider"]
        and case["strategies"]["E0"]["hit_at_3"]
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", action="store_true", help="run the real, rate-limited searches")
    parser.add_argument("--input", type=Path, default=DEFAULT_CAPTURE)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--queries", type=Path, default=DEFAULT_QUERIES)
    parser.add_argument("--limit", type=int, default=6)
    parser.add_argument("--pace-ddg", type=float, default=6.0)
    parser.add_argument("--pace-other", type=float, default=1.0)
    args = parser.parse_args()

    if args.capture:
        artifact = capture(
            queries=args.queries.resolve(),
            output=(args.output or DEFAULT_CAPTURE).resolve(),
            limit=max(1, min(args.limit, 12)),
            pace_ddg=max(0.0, args.pace_ddg),
            pace_other=max(0.0, args.pace_other),
        )
        print(json.dumps({"cases": len(artifact["cases"])}, sort_keys=True))
        return 0

    artifact = replay(
        capture_path=(args.input).resolve(),
        output=(args.output or DEFAULT_REPLAY).resolve(),
        limit=max(1, min(args.limit, 12)),
    )
    print(json.dumps(artifact["summary"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
