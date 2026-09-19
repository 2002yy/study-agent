"""§44C replacement-provider qualification: Brave Web Search API, provider-only.

This harness never touches the merge, the query planner or the selector. It
asks one question per known target page: does the candidate provider return
the page in its raw top-20 for the three frozen query classes?

    exact title / title + entity / semantic query
    x parameter sets: default vs locale (country=us, search_lang=en, ui_lang=en)
    count = 20

Gate (frozen): Docker and PostgreSQL exact-title queries must hit in raw top20,
otherwise the provider fails qualification outright; exact/title+entity must
clearly hit overall. Metrics per probe: target_returned, target_raw_rank,
official_domain_hit, official_deep_page_count, latency, status/error.

Requires BRAVE_SEARCH_API_KEY (or BRAVE_API_KEY); exits cleanly without one.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

from tools.run_recall_target_audit import TARGETS, TargetSpec  # noqa: E402
from tools.run_provider_attribution import _has_cjk, _path_depth  # noqa: E402

SCHEMA_VERSION = "brave-provider-qualification-v1"
BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
COUNT = 20
LOCALE_PARAMS: dict[str, str] = {
    "country": "us",
    "search_lang": "en",
    "ui_lang": "en",
}
HARD_GATE_CASES = (
    "rq1c-current-policy-container-registry",
    "rq1c-current-support-postgresql",
)


def brave_api_key() -> str:
    return (
        os.getenv("BRAVE_SEARCH_API_KEY") or os.getenv("BRAVE_API_KEY") or ""
    ).strip()


def build_params(query: str, *, locale: bool) -> dict[str, str]:
    params: dict[str, str] = {"q": query, "count": str(COUNT)}
    if locale:
        params.update(LOCALE_PARAMS)
    return params


def parse_brave_payload(payload: Mapping[str, Any] | None) -> list[dict[str, str]]:
    """Pure parser for the Brave web search envelope."""

    if not isinstance(payload, Mapping):
        return []
    web = payload.get("web")
    web = web if isinstance(web, Mapping) else {}
    rows: list[dict[str, str]] = []
    for item in web.get("results") or []:
        if not isinstance(item, Mapping):
            continue
        url = str(item.get("url") or "")
        if not url:
            continue
        rows.append(
            {
                "url": url,
                "title": str(item.get("title") or ""),
                "snippet": str(item.get("description") or ""),
            }
        )
    return rows


def _domain(url: str) -> str:
    match = __import__("re").match(r"https?://([^/]+)", str(url or ""))
    return (match.group(1) if match else "").lower()


def evaluate_probe(
    results: Sequence[Mapping[str, str]], target: TargetSpec
) -> dict[str, Any]:
    normalized = target.url.rstrip("/")
    rank = next(
        (
            index
            for index, row in enumerate(results, start=1)
            if str(row.get("url") or "").rstrip("/") == normalized
        ),
        None,
    )
    target_domain = _domain(target.url)
    official_rows = [
        row for row in results if _domain(str(row.get("url") or "")) == target_domain
    ]
    deep_pages = [
        row for row in official_rows if _path_depth(str(row.get("url") or "")) >= 1
    ]
    return {
        "target_returned": rank is not None,
        "target_raw_rank": rank,
        "official_domain_hit": bool(official_rows),
        "official_result_count": len(official_rows),
        "official_deep_page_count": len(deep_pages),
        "cjk_results": sum(
            1
            for row in results
            if _has_cjk(f"{row.get('title')} {row.get('snippet')}")
        ),
    }


def _brave_search(
    query: str, *, locale: bool, api_key: str, timeout: float
) -> tuple[list[dict[str, str]], str, int | None, int]:
    params = urllib.parse.urlencode(build_params(query, locale=locale))
    request = urllib.request.Request(
        f"{BRAVE_ENDPOINT}?{params}",
        headers={
            "Accept": "application/json",
            "X-Subscription-Token": api_key,
            "User-Agent": "study-agent-provider-qualification",
        },
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
            latency_ms = int((time.monotonic() - started) * 1000)
            return parse_brave_payload(payload), "", response.status, latency_ms
    except urllib.error.HTTPError as exc:
        latency_ms = int((time.monotonic() - started) * 1000)
        return [], f"http_{exc.code}", exc.code, latency_ms
    except Exception as exc:
        latency_ms = int((time.monotonic() - started) * 1000)
        return [], f"{type(exc).__name__}", None, latency_ms


def evaluate_gate(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Frozen qualification gate over all probes."""

    def hit(case_id: str, query_class: str) -> bool:
        return any(
            row["case_id"] == case_id
            and row["query_class"] == query_class
            and row["target_returned"]
            for row in rows
        )

    hard_failures = [
        case_id
        for case_id in HARD_GATE_CASES
        if not hit(case_id, "exact_title")
    ]
    exact_failures = [
        row["case_id"]
        for row in rows
        if row["query_class"] == "exact_title" and not hit(row["case_id"], "exact_title")
    ]
    entity_failures = [
        row["case_id"]
        for row in rows
        if row["query_class"] == "entity_title"
        and not hit(row["case_id"], "entity_title")
    ]
    passed = not hard_failures
    return {
        "passed": passed,
        "hard_gate_failures": sorted(set(hard_failures)),
        "exact_title_missing": sorted(set(exact_failures)),
        "entity_title_missing": sorted(set(entity_failures)),
        "note": (
            "Docker and PostgreSQL exact-title raw top20 hits are mandatory; "
            "otherwise the provider fails qualification"
        ),
    }


def run_qualification(
    *, output_path: Path, timeout: float = 15.0, api_key: str | None = None
) -> dict[str, Any]:
    load_dotenv(REPO_ROOT / ".env")
    key = (api_key if api_key is not None else brave_api_key()).strip()
    if not key:
        raise SystemExit(
            "missing BRAVE_SEARCH_API_KEY (or BRAVE_API_KEY); add it to .env and rerun"
        )
    rows: list[dict[str, Any]] = []
    for target in TARGETS:
        queries = (
            ("exact_title", target.exact_title),
            ("entity_title", f"{target.exact_title} {target.entity_terms[0]}"),
            ("semantic", target.semantic_query),
        )
        for label, query in queries:
            for locale_variant, use_locale in (("default", False), ("locale_us_en", True)):
                results, error, status, latency_ms = _brave_search(
                    query, locale=use_locale, api_key=key, timeout=timeout
                )
                row = {
                    "case_id": target.case_id,
                    "target": target.url,
                    "query_class": label,
                    "query": query,
                    "params": "locale_us_en" if use_locale else "default",
                    "status": status,
                    "error": error,
                    "latency_ms": latency_ms,
                    "result_count": len(results),
                    "top_urls": [item["url"] for item in results[:3]],
                    **evaluate_probe(results, target),
                }
                rows.append(row)
                print(
                    f"{target.case_id} [{label}/{locale_variant}] "
                    f"hit={row['target_returned']} rank={row['target_raw_rank']} "
                    f"official={row['official_domain_hit']} n={row['result_count']} "
                    f"{error or ''}"
                )
                time.sleep(0.2)
    gate = evaluate_gate(rows)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "diagnostic_only": True,
        "qualification_evidence": False,
        "provider": "brave_web_search",
        "endpoint": BRAVE_ENDPOINT,
        "count": COUNT,
        "locale_params": LOCALE_PARAMS,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rows": rows,
        "gate": gate,
        "summary": {
            "probes": len(rows),
            "hits": sum(1 for row in rows if row["target_returned"]),
            "latency_ms_p50": sorted(int(row["latency_ms"]) for row in rows)[
                len(rows) // 2
            ]
            if rows
            else None,
            "errors": sum(1 for row in rows if row["error"]),
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=15.0)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    payload = run_qualification(output_path=args.output.resolve(), timeout=args.timeout)
    print(json.dumps(payload["gate"], ensure_ascii=False, sort_keys=True))
    return 0 if payload["gate"]["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
