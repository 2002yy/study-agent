"""Search-2 probe: run the real retrieval entry, then read and fact-check top-1.

Small on purpose. It answers one question per case, in the order a user needs
it: is the delivered first result about the question, can that page be read, and
does the read text actually contain the fact the question asks for. It is not a
benchmark harness and it does not call a model.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
import sys
import time
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

DEFAULT_CASES = (
    REPO_ROOT / "tests" / "fixtures" / "provider_routing" / "search_2_fact_checks_v1.json"
)
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "research_quality" / "SEARCH_2_PROBE.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1)))))
    return round(ordered[index], 2)


def _read_text(result: dict[str, Any]) -> str:
    """All human-readable text a read result carries, whatever its kind.

    GitHub reads return ``description``/``readme``/``entries`` instead of
    ``content``; ignoring them would score a successful repository read as an
    empty page.
    """

    parts = [str(result.get(key) or "") for key in ("content", "readme", "description")]
    entries = result.get("entries")
    if isinstance(entries, list):
        parts.extend(
            str(item.get("name") or "") for item in entries if isinstance(item, dict)
        )
    return "\n".join(part for part in parts if part)


def _matches(text: str, case: dict[str, Any]) -> dict[str, Any]:
    folded = text.casefold()
    missing = [token for token in case["expect_all"] if token.casefold() not in folded]
    groups = [
        [token for token in group if token.casefold() in folded]
        for group in case["expect_any_group"]
    ]
    return {
        "fact_ok": not missing and all(groups),
        "missing_all": missing,
        "matched_any": [hits for hits in groups],
    }


def probe(
    *,
    cases_path: Path,
    output: Path,
    arms: tuple[str, ...],
    max_results: int,
    read_timeout: float,
    pace: float,
) -> dict[str, Any]:
    load_dotenv(REPO_ROOT / ".env")
    from src.web.tool_gateway import GeneralWebGateway

    cases = json.loads(cases_path.read_text(encoding="utf-8"))["cases"]
    artifact: dict[str, Any] = {
        "schema_version": "search-2-probe-v1",
        "started_at": _now(),
        "cases_fixture": str(cases_path.relative_to(REPO_ROOT)).replace("\\", "/"),
        "arms": list(arms),
        "max_results": max_results,
        "read_timeout": read_timeout,
        "scope": {
            "uses_model": False,
            "reads_only_top1": True,
            "read_cache": "one read per URL per run, reused across arms",
        },
        "rows": [],
    }
    reads: dict[str, dict[str, Any]] = {}
    for case in cases:
        row: dict[str, Any] = {"id": case["id"], "category": case["category"], "arms": {}}
        for arm in arms:
            gateway = GeneralWebGateway(search_strategy=arm)
            started = time.monotonic()
            payload = gateway.search_exact(case["query"], max_results=max_results)
            elapsed = round(time.monotonic() - started, 2)
            results = payload.get("results", [])
            top = results[0] if results else None
            entry: dict[str, Any] = {
                "status": payload.get("status"),
                "elapsed": elapsed,
                "providers_attempted": payload.get("providers_attempted", []),
                "fallback_used": payload.get("fallback_used"),
                "provider_errors": payload.get("provider_errors", []),
                "top_url": str((top or {}).get("url") or ""),
                "top_title": str((top or {}).get("title") or ""),
            }
            if top is None:
                entry.update({"read_ok": False, "read_error": "no_results", "fact_ok": False})
            else:
                url = entry["top_url"]
                cached = reads.get(url)
                reused = cached is not None
                if cached is None:
                    read_started = time.monotonic()
                    try:
                        result = gateway.read(url, timeout=read_timeout)
                        text = _read_text(result)
                        cached = {
                            "read_ok": bool(result.get("ok")),
                            "read_error": str(result.get("error") or ""),
                            "read_kind": str(result.get("kind") or ""),
                            "chars": len(text),
                            "read_elapsed": round(time.monotonic() - read_started, 2),
                            "content": text,
                        }
                    except Exception as exc:  # noqa: BLE001 - probe resilience
                        cached = {
                            "read_ok": False,
                            "read_error": f"{type(exc).__name__}:{exc}",
                            "chars": 0,
                            "read_elapsed": round(time.monotonic() - read_started, 2),
                            "content": "",
                        }
                    reads[url] = cached
                entry.update(
                    {
                        "read_ok": cached["read_ok"],
                        "read_error": cached["read_error"],
                        "read_kind": cached.get("read_kind", ""),
                        "chars": cached["chars"],
                        "read_elapsed": cached["read_elapsed"],
                        "read_reused": reused,
                    }
                )
                if cached["read_ok"]:
                    entry.update(_matches(cached["content"], case))
                else:
                    entry.update(
                        {"fact_ok": False, "missing_all": [], "matched_any": []}
                    )
            row["arms"][arm] = entry
            print(
                f"[probe] {case['id']} {arm}: status={entry['status']} "
                f"read={entry.get('read_ok')} fact={entry.get('fact_ok')} "
                f"{entry['elapsed']}s",
                flush=True,
            )
            time.sleep(pace)
        artifact["rows"].append(row)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    summary: dict[str, Any] = {}
    for arm in arms:
        entries = [row["arms"][arm] for row in artifact["rows"]]
        latencies = [entry["elapsed"] for entry in entries]
        summary[arm] = {
            "cases": len(entries),
            "search_ok": sum(1 for entry in entries if entry["status"] == "ok"),
            "read_ok": sum(1 for entry in entries if entry.get("read_ok")),
            "fact_ok": sum(1 for entry in entries if entry.get("fact_ok")),
            "provider_calls": sum(len(entry["providers_attempted"]) for entry in entries),
            "fallbacks": sum(1 for entry in entries if entry.get("fallback_used")),
            "latency_p50": _percentile(latencies, 0.5),
            "latency_p95": _percentile(latencies, 0.95),
            "latency_mean": round(statistics.fmean(latencies), 2) if latencies else None,
        }
    artifact["summary"] = summary
    artifact["completed_at"] = _now()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--arms", default="fallback,ddg_first")
    parser.add_argument("--max-results", type=int, default=6)
    parser.add_argument("--read-timeout", type=float, default=6.0)
    parser.add_argument("--pace", type=float, default=1.0)
    args = parser.parse_args()
    artifact = probe(
        cases_path=args.cases.resolve(),
        output=args.output.resolve(),
        arms=tuple(arm.strip() for arm in args.arms.split(",") if arm.strip()),
        max_results=max(1, min(args.max_results, 12)),
        read_timeout=max(1.0, args.read_timeout),
        pace=max(0.0, args.pace),
    )
    print(json.dumps(artifact["summary"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
