"""Offline M4-C diagnostics from the text and candidate trace of one recorded run.

No re-fetch, URL admission, support verdict, or production authority is granted.
Missing observations remain unknown; transport success is not answer support.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


def audit_trace(
    trace: dict[str, Any], targets: list[str] | None = None
) -> dict[str, Any]:
    events = trace.get("candidate_trace") or []
    calls = trace.get("calls") or []
    trace_observed = "candidate_trace" in trace
    read_events = [row for row in events if row.get("tool") == "read_page"]
    shown = {url for row in events for url in row.get("shown", [])}
    call_urls = {
        call["action"]["url"] for call in calls if call.get("action", {}).get("url")
    }
    result_urls = {
        url
        for call in calls
        for url in (call.get("result") or {}).get("urls", [])
        if url
    }
    urls = sorted(
        shown
        | call_urls
        | result_urls
        | {row["url"] for row in read_events}
        | set(targets or [])
    )
    chains = trace.get("source_chain") or []
    candidates = []
    for url in urls:
        rows = [row for row in read_events if row["url"] == url]
        confirmed = (
            True
            if any(url in event.get("newly_confirmed", []) for event in events)
            else None
        )
        # An explicit read gate observation is stronger than merely being shown.
        for row in rows:
            if "confirmed" in row:
                confirmed = bool(row["confirmed"])
        reads_succeeded = sum(row.get("succeeded") is True for row in rows)
        final_urls = {url} | {
            row["read_url"] for row in chains if row.get("entry_url") == url
        }
        bodies = []
        for body in trace.get("bodies", []):
            if body.get("url") not in final_urls or not body.get("ok"):
                continue
            text = body.get("text")
            bodies.append(
                {
                    "url": body["url"],
                    "chars": body.get("chars"),
                    "same_run_full_text": isinstance(text, str),
                    "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()
                    if isinstance(text, str)
                    else None,
                    "q1_state": None,
                    "q1_markers": [],
                }
            )
        failures = [
            row.get("failure_reason") for row in rows if row.get("failure_reason")
        ]
        if reads_succeeded:
            gap = "body_support_unreviewed"
        elif confirmed is False:
            gap = "confirmation_rejected"
        elif any(row.get("eligible") is False for row in rows):
            gap = "eligibility_rejected"
        elif any(row.get("attempted") is True for row in rows):
            gap = "read_failed"
        elif rows:
            gap = "read_not_attempted"
        elif "candidate_trace" not in trace:
            gap = "candidate_visibility_unobserved"
        elif url in shown:
            gap = "shown_without_read_action"
        else:
            gap = "not_shown_raw_and_filtered_unknown"
        candidates.append(
            {
                "url": url,
                "raw": None,
                "filtered": None,
                "shown": (url in shown) if "candidate_trace" in trace else None,
                "confirmed": confirmed,
                "eligible_observations": [row.get("eligible") for row in rows],
                "read_actions": len(rows)
                if trace_observed
                else sum(
                    call.get("action", {}).get("tool") == "read_page"
                    and call.get("action", {}).get("url") == url
                    for call in calls
                ),
                "attempted": sum(row.get("attempted") is True for row in rows)
                if trace_observed
                else None,
                "succeeded": reads_succeeded if trace_observed else None,
                "failure_reasons": failures,
                "observed_gap": gap,
                "bodies": bodies,
            }
        )
    # Different query strings can still return the identical candidate set.
    signatures = Counter(
        tuple(sorted(set(row.get("shown", []))))
        for row in events
        if row.get("tool") == "search" and row.get("shown")
    )
    return {
        "schema": "m4c-tool-agent-candidate-audit-v1",
        "diagnostic_only": True,
        "publication_authority": False,
        "candidate_trace_observed": "candidate_trace" in trace,
        "stop_reason": trace.get("stop_reason"),
        "cost": {
            key: trace.get(key)
            for key in ("rounds", "searches", "reads", "elapsed_seconds")
        },
        "repeated_search_result_sets": sum(count - 1 for count in signatures.values()),
        "candidates": candidates,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument("--target", action="append", default=[])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    raw = args.trace.read_bytes()
    report = audit_trace(json.loads(raw), args.target)
    report["input"] = {
        "path": str(args.trace.resolve()),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    if args.out.resolve() == args.trace.resolve():
        parser.error("output must not overwrite the source trace")
    args.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
