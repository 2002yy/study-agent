"""Retrieval-layer baseline for Search-to-Answer-1.

This runs the *real* gateway (search + page read) over the frozen question set in
``tests/fixtures/search_to_answer/baseline_v1.json`` and records bounded
operational metadata only: case id, providers, public URLs, titles, error codes
and timings. It stores no page bodies, no credentials and no proxy address.

Why a separate runner instead of ``run_research_quality_live_observation.py``:
that tool is bound to the trap-case schema (``research-quality`` gold contracts
with primary/secondary source roles). Filling those contracts for ordinary user
questions would mean inventing gold we cannot verify, so this runner reuses the
same ``GeneralWebGateway`` and the same read path but not that schema.

Answer quality is deliberately not measured here: there is no zero-cost answer
generator wired into this checkout, so ``answer_status``, ``ttfu_seconds`` and
``evidence_verdict`` are reported as ``not_measured`` rather than inferred from
retrieval metrics.

Provider modes (all isolated to this process, no global config change):

- ``auto``: whatever the deployment configures (the path a user actually hits).
- ``fallback``: SearXNG disabled, Bing RSS and DuckDuckGo available.
- ``ddg_only``: only DuckDuckGo, so the last fallback is measured on its own.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
import uuid
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

from src.web.tool_gateway import GeneralWebGateway  # noqa: E402

DEFAULT_CASES = REPO_ROOT / "tests" / "fixtures" / "search_to_answer" / "baseline_v1.json"
DEFAULT_OUTPUT = (
    REPO_ROOT / "docs" / "research_quality" / "SEARCH_TO_ANSWER_BASELINE_1.json"
)
SCHEMA_VERSION = "search-to-answer-baseline-artifact-v1"

PROVIDER_MODES: dict[str, dict[str, str]] = {
    "auto": {},
    "fallback": {
        "WEB_ENABLE_SEARXNG": "false",
        "WEB_ENABLE_BING_RSS": "true",
        "WEB_ENABLE_DUCKDUCKGO": "true",
    },
    "ddg_only": {
        "WEB_ENABLE_SEARXNG": "false",
        "WEB_ENABLE_BING_RSS": "false",
        "WEB_ENABLE_DUCKDUCKGO": "true",
    },
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _bounded(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _head_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except Exception:
        return "unknown"


def load_cases(path: Path, selected: set[str] | None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    cases = document.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError(f"{path} has no cases")
    required = {"id", "category", "prompt", "expected_behavior", "evaluation"}
    seen: set[str] = set()
    for case in cases:
        missing = required - set(case or {})
        if missing:
            raise ValueError(f"{path}: case missing {sorted(missing)}")
        if case["id"] in seen:
            raise ValueError(f"{path}: duplicate case id {case['id']}")
        seen.add(case["id"])
    if selected:
        unknown = selected - seen
        if unknown:
            raise ValueError(f"unknown case ids: {', '.join(sorted(unknown))}")
        cases = [case for case in cases if case["id"] in selected]
    return document, cases


def _results_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    sources: dict[str, int] = {}
    with_snippet = 0
    for item in results:
        source = _bounded(item.get("source") or "unknown", 60) or "unknown"
        sources[source] = sources.get(source, 0) + 1
        if str(item.get("snippet") or "").strip():
            with_snippet += 1
    return {
        "result_count": len(results),
        "result_sources": sources,
        "results_with_snippet": with_snippet,
        "snippet_present_ratio": (
            round(with_snippet / len(results), 3) if results else None
        ),
    }


def _read_probe(
    gateway: GeneralWebGateway, url: str, *, max_chars: int
) -> dict[str, Any]:
    started = time.monotonic()
    try:
        payload = gateway.read(url, max_chars=max_chars)
    except Exception as exc:  # noqa: BLE001 - the probe records, it does not fail
        return {
            "url": url,
            "ok": False,
            "error_type": type(exc).__name__,
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }
    content = str(payload.get("content") or "")
    return {
        "url": _bounded(payload.get("url") or url, 2000),
        "ok": bool(payload.get("ok")) and bool(content.strip()),
        "content_chars": len(content),
        "error_code": _bounded(payload.get("error_code"), 120) if not payload.get("ok") else "",
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }


def _median(values: list[float]) -> float | None:
    return round(statistics.median(values), 3) if values else None


def _p90(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round(0.9 * (len(ordered) - 1)))))
    return round(ordered[index], 3)


def _summarise(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_mode: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        by_mode.setdefault(record["provider_mode"], []).append(record)

    summary: dict[str, Any] = {}
    for mode, items in by_mode.items():
        latencies = [item["search_latency_seconds"] for item in items]
        reads = [read for item in items for read in item["reads"]]
        sources: dict[str, int] = {}
        for item in items:
            for name, count in item["result_sources"].items():
                sources[name] = sources.get(name, 0) + count
        summary[mode] = {
            "cases": len(items),
            "search_ok_cases": sum(1 for item in items if item["search_status"] == "ok"),
            "cases_with_results": sum(1 for item in items if item["result_count"] > 0),
            "search_latency_seconds_median": _median(latencies),
            "search_latency_seconds_p90": _p90(latencies),
            "total_results": sum(item["result_count"] for item in items),
            "result_sources": sources,
            "snippet_present_ratio": (
                round(
                    sum(item["results_with_snippet"] for item in items)
                    / max(1, sum(item["result_count"] for item in items)),
                    3,
                )
            ),
            "read_attempts": len(reads),
            "read_successes": sum(1 for read in reads if read["ok"]),
            "read_error_codes": sorted(
                {read.get("error_code") for read in reads if read.get("error_code")}
            ),
            "provider_error_codes": sorted(
                {
                    str(error).split(":")[0] + ":" + str(error).split(":")[1]
                    for item in items
                    for error in item["provider_errors"]
                    if str(error).count(":") >= 1
                }
            ),
        }
    return summary


def run_baseline(
    *,
    cases_path: Path,
    output_path: Path,
    modes: list[str],
    max_results: int,
    max_reads: int,
    max_chars: int,
    selected_cases: set[str] | None,
) -> dict[str, Any]:
    load_dotenv(REPO_ROOT / ".env")
    document, cases = load_cases(cases_path, selected_cases)

    artifact: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": uuid.uuid4().hex,
        "head_sha": _head_sha(),
        "started_at": _utc_now(),
        "completed_at": None,
        "cases_fixture": str(cases_path.relative_to(REPO_ROOT)).replace("\\", "/"),
        "cases_fixture_version": document.get("schema_version"),
        "cases_fixture_frozen_at": document.get("frozen_at"),
        "provider_modes": modes,
        "records": [],
        "summary": {},
        "not_measured": {
            "answer_status": "no zero-cost answer generator in this checkout",
            "ttfu_seconds": "requires a real answer stream",
            "evidence_verdict": "requires generated claims to verify",
            "follow_up_behaviour": "requires a conversation run",
        },
        "scope": {
            "stores_page_bodies": False,
            "stores_credentials": False,
            "uses_model_synthesis": False,
            "real_network_requests": True,
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)

    original_env = {name: os.environ.get(name) for name in {
        "WEB_ENABLE_SEARXNG",
        "WEB_ENABLE_BING_RSS",
        "WEB_ENABLE_DUCKDUCKGO",
    }}
    try:
        for mode in modes:
            for name, value in PROVIDER_MODES[mode].items():
                os.environ[name] = value
            gateway = GeneralWebGateway()
            for index, case in enumerate(cases, start=1):
                started = time.monotonic()
                search = gateway.search_detailed(
                    case["prompt"], max_results=max_results
                )
                latency = round(time.monotonic() - started, 3)
                results = [
                    item for item in search.get("results", []) if isinstance(item, dict)
                ]
                summary = _results_summary(results)
                reads = [
                    _read_probe(gateway, str(item.get("url") or ""), max_chars=max_chars)
                    for item in results[:max_reads]
                    if str(item.get("url") or "").strip()
                ]
                record = {
                    "case_id": case["id"],
                    "category": case["category"],
                    "round_1": bool(case.get("round_1")),
                    "provider_mode": mode,
                    "prompt": _bounded(case["prompt"], 400),
                    "search_status": _bounded(search.get("status"), 40),
                    "search_reason": _bounded(search.get("reason"), 120),
                    "attempted_queries": [
                        _bounded(value, 200)
                        for value in search.get("attempted_queries", [])
                    ],
                    "provider_errors": [
                        _bounded(value, 200)
                        for value in search.get("provider_errors", [])
                    ],
                    "search_latency_seconds": latency,
                    **summary,
                    "results": [
                        {
                            "title": _bounded(item.get("title"), 300),
                            "url": _bounded(item.get("url"), 500),
                            "source": _bounded(item.get("source"), 60),
                            "snippet_chars": len(str(item.get("snippet") or "")),
                        }
                        for item in results
                    ],
                    "reads": reads,
                    "read_attempts": len(reads),
                    "read_successes": sum(1 for read in reads if read["ok"]),
                    "answer_status": "not_measured",
                    "ttfu_seconds": None,
                    "evidence_verdict": "not_measured",
                }
                artifact["records"].append(record)
                output_path.write_text(
                    json.dumps(artifact, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                print(
                    f"[{mode} {index}/{len(cases)}] {record['case_id']}: "
                    f"{record['search_status']} · results={record['result_count']} · "
                    f"snippets={record['results_with_snippet']}/{record['result_count']} · "
                    f"reads={record['read_successes']}/{record['read_attempts']} · "
                    f"{record['search_latency_seconds']}s",
                    flush=True,
                )
    finally:
        for name, value in original_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    artifact["completed_at"] = _utc_now()
    artifact["summary"] = _summarise(artifact["records"])
    output_path.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return artifact


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--mode", action="append", choices=sorted(PROVIDER_MODES), default=[])
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--max-results", type=int, default=6)
    parser.add_argument("--max-reads", type=int, default=2)
    parser.add_argument("--max-chars", type=int, default=6000)
    return parser


def main() -> int:
    args = _parser().parse_args()
    artifact = run_baseline(
        cases_path=args.cases.resolve(),
        output_path=args.output.resolve(),
        modes=args.mode or ["auto"],
        max_results=max(1, min(args.max_results, 12)),
        max_reads=max(0, min(args.max_reads, 5)),
        max_chars=max(500, min(args.max_chars, 20_000)),
        selected_cases=set(args.case) or None,
    )
    print(json.dumps(artifact["summary"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
