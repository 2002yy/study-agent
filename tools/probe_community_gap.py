"""Compare a scoped fast search and a real community-site browser search.

Zero model/API calls. Run after #368 lands in the Windows environment that has
the ``browse`` extension installed. Search hits are *not* evidence: the probe
also records whether the normal reader can open a small number of result pages.

    python tools/probe_community_gap.py --out D:/study-agent-validation/community-gap.json

The lexical hit counts below are diagnostics, not a model relevance judgment.
No source body, cookies, session data, or credentials are written to the JSON.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.web.research.facet_coverage import community_hosts_for
from src.web.tool_gateway import GeneralWebGateway, _result_key


@dataclass(frozen=True)
class ProbeCase:
    key: str
    question: str
    search: str
    expected_host: str
    must_mention: tuple[str, ...]


CASES: tuple[ProbeCase, ...] = (
    ProbeCase("product", "Notion 和 Obsidian 哪个更适合长期笔记？求真实使用体验",
              "Notion Obsidian 长期笔记 体验", "v2ex.com", ("notion", "obsidian")),
    ProbeCase("game", "星铁流萤配队推荐，玩家实战体验",
              "星铁 流萤 配队 实战", "miyoushe.com", ("流萤", "配队")),
    ProbeCase("jobs", "2026届 Java 校招牛客面经真实体验",
              "2026届 Java 校招 面经", "nowcoder.com", ("java", "面经")),
    ProbeCase("hardware", "RTX 5060 Laptop 显卡用户实测体验",
              "RTX 5060 Laptop 实测", "chiphell.com", ("rtx", "5060")),
)


def _rows(payload: dict[str, Any], max_results: int) -> list[dict[str, str]]:
    return [
        {"title": str(row.get("title") or ""),
         "url": str(row.get("url") or ""),
         "snippet": str(row.get("snippet") or "")}
        for row in payload.get("results", [])[:max_results]
        if isinstance(row, dict) and str(row.get("url") or "").startswith(("http://", "https://"))
    ]


def _lexical_hits(rows: list[dict[str, str]], terms: tuple[str, ...]) -> int:
    return sum(
        all(term.casefold() in f"{row['title']} {row['snippet']}".casefold() for term in terms)
        for row in rows
    )


def _call(fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    started = time.monotonic()
    try:
        outcome = fn()
        if not isinstance(outcome, dict):
            raise ValueError("unexpected_provider_payload")
    except Exception as exc:
        outcome = {"status": "unavailable", "reason": type(exc).__name__, "results": []}
    return {"elapsed_ms": round((time.monotonic() - started) * 1000), "outcome": outcome}


def run(
    cases: tuple[ProbeCase, ...] = CASES,
    *,
    gateway_factory: Callable[[], Any] = GeneralWebGateway,
    max_results: int = 5,
    read_limit: int = 1,
) -> dict[str, Any]:
    """Use two independent gateways concurrently; compare delivered URL sets.

    Browser-first completion is reported as observed, not guessed. The probe
    does not expose a progressive search API or change production routing.
    """

    max_results = max(1, min(max_results, 12))
    read_limit = max(0, min(read_limit, 3))
    details = []
    for case in cases:
        routed_hosts = community_hosts_for(case.question)
        host = routed_hosts[0] if routed_hosts else ""
        if host != case.expected_host:
            details.append({"case": case.key, "question": case.question,
                            "route": list(routed_hosts), "route_ok": False,
                            "reason": "unexpected_community_route"})
            continue
        scoped = f"{case.search} site:{host}"
        fast = gateway_factory()
        browser = gateway_factory()
        started = time.monotonic()
        order: list[str] = []
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="community-probe") as pool:
            work = {
                pool.submit(_call, lambda: fast.search_exact(scoped, max_results=max_results)): "fast",
                pool.submit(_call, lambda: browser.search_community_site(
                    scoped, host=host, max_results=max_results)): "browser",
            }
            returned: dict[str, dict[str, Any]] = {}
            for future in as_completed(work):
                lane = work[future]
                order.append(lane)
                returned[lane] = future.result()
        channels = {}
        rows_by_lane = {}
        for lane in ("fast", "browser"):
            attempt = returned[lane]
            result = attempt["outcome"]
            rows = _rows(result, max_results)
            rows_by_lane[lane] = rows
            channels[lane] = {
                "status": result.get("status"),
                "reason": result.get("reason"),
                "elapsed_ms": attempt["elapsed_ms"],
                "result_count": len(rows),
                "lexical_title_snippet_hits": _lexical_hits(rows, case.must_mention),
                "provider_outcomes": result.get("provider_outcomes", []),
                "site_outcomes": result.get("site_outcomes", []),
                "urls": [row["url"] for row in rows],
            }
        fast_keys = {_result_key(row) for row in rows_by_lane["fast"]}
        browser_extra = [row for row in rows_by_lane["browser"]
                         if _result_key(row) not in fast_keys]
        reads = []
        seen: set[str] = set()
        for lane in ("fast", "browser"):
            lane_reads = 0
            for row in rows_by_lane[lane]:
                if lane_reads >= read_limit:
                    break
                marker = _result_key(row)
                if not marker or marker in seen:
                    continue
                seen.add(marker)
                lane_reads += 1
                started_read = time.monotonic()
                try:
                    result = gateway_factory().read(row["url"], max_chars=3000, timeout=6.0)
                    success = bool(result.get("ok") and str(result.get("content") or "").strip())
                    chars = len(str(result.get("content") or "")) if success else 0
                    error = "" if success else str(result.get("error_code") or "empty_body")
                except Exception as exc:
                    success, chars, error = False, 0, type(exc).__name__
                reads.append({"lane": lane, "url": row["url"], "ok": success,
                              "content_chars": chars, "error": error,
                              "elapsed_ms": round((time.monotonic() - started_read) * 1000)})
        details.append({
            "case": case.key,
            "question": case.question,
            "scoped_search": scoped,
            "route": list(routed_hosts),
            "route_ok": True,
            "return_order": order,
            "elapsed_ms": round((time.monotonic() - started) * 1000),
            "channels": channels,
            "browser_unique_urls": [row["url"] for row in browser_extra],
            "browser_unique_count": len(browser_extra),
            "reads": reads,
        })
    return {
        "kind": "community_gap_browser_vs_fast_free_probe",
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "model_calls": 0,
        "lexical_scores_are_not_semantic_relevance": True,
        "cases": details,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, help="JSON report location")
    parser.add_argument("--cases", default="", help="comma-separated case keys")
    parser.add_argument("--read-limit", type=int, default=1)
    args = parser.parse_args(argv)
    selected = {item.strip() for item in args.cases.split(",") if item.strip()}
    if selected - {case.key for case in CASES}:
        parser.error(f"unknown cases: {sorted(selected - {case.key for case in CASES})}")
    cases = tuple(case for case in CASES if not selected or case.key in selected)
    report = run(cases, read_limit=args.read_limit)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for case in report["cases"]:
        if not case["route_ok"]:
            print(f"{case['case']}: route mismatch {case['route']}")
            continue
        print(f"{case['case']}: {case['return_order']} "
              f"fast={case['channels']['fast']['result_count']} "
              f"browser={case['channels']['browser']['result_count']} "
              f"new={case['browser_unique_count']} "
              f"readable={sum(item['ok'] for item in case['reads'])}")
    print(f"wrote {out}")
    return 0 if all(case["route_ok"] for case in report["cases"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
