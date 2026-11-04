"""Stage-1 report: what the interactive-history rewrite does to real sessions.

Reads a saved runtime database, rebuilds the history each turn would send, and
compares the model input before and after compression. No model is called: this
only answers "how much is removed, what is kept, what is dropped".

Usage:
    python tools/interactive_history_report.py --db runtime.db [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.interactive_history import (  # noqa: E402
    compress_interactive_history,
    find_interactive_versions,
)
from src.mode_manager import RuntimeModes  # noqa: E402
from src.context_builder import chat_history_limit  # noqa: E402


def load_threads(db_path: Path) -> dict[str, list[dict[str, Any]]]:
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            "select thread_id, id, user_message, assistant_message, created_at "
            "from chat_turns where assistant_message is not null "
            "order by thread_id, created_at"
        ).fetchall()
    finally:
        connection.close()
    threads: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        threads.setdefault(row["thread_id"], []).append(
            {
                "turn_id": row["id"],
                "user": row["user_message"] or "",
                "assistant": row["assistant_message"] or "",
            }
        )
    return threads


def history_for(turns: list[dict[str, Any]], index: int, limit: int) -> list[dict]:
    messages: list[dict[str, Any]] = []
    for turn in turns[:index]:
        messages.append({"role": "user", "content": turn["user"]})
        messages.append({"role": "assistant", "content": turn["assistant"]})
    return messages[-limit:]


def compare_turn(turns: list[dict[str, Any]], index: int, limit: int) -> dict[str, Any]:
    history = history_for(turns, index, limit)
    user_input = turns[index]["user"]
    result = compress_interactive_history(history, user_input=user_input)
    report = dict(result.report)
    report["turn_id"] = turns[index]["turn_id"]
    report["position"] = index + 1
    report["history_messages"] = len(history)

    # The rewrite must leave user text and the chosen revision byte-identical.
    original_user = [m["content"] for m in history if m["role"] == "user"]
    kept_user = [m["content"] for m in result.messages if m["role"] == "user"]
    report["user_messages_identical"] = original_user == kept_user

    target = report.get("target_id")
    revision = report.get("target_revision")
    kept_source = None
    for version in find_interactive_versions(history):
        if version.id == target and version.revision == revision:
            kept_source = history[version.message_index]["content"][
                version.start : version.end
            ]
            break
    report["current_source_present"] = bool(kept_source) and any(
        kept_source in message["content"] for message in result.messages
    )
    return report


def build_report(db_path: Path) -> dict[str, Any]:
    limit = chat_history_limit(RuntimeModes())
    threads = load_threads(db_path)
    cases: list[dict[str, Any]] = []
    for thread_id, turns in threads.items():
        for index in range(1, len(turns)):
            case = compare_turn(turns, index, limit)
            case["thread_id"] = thread_id
            cases.append(case)

    interactive = [case for case in cases if case["status"] == "compressed"]
    before = sum(case["chars_before"] for case in interactive)
    after = sum(case["chars_after"] for case in interactive)
    return {
        "schema_version": "interactive-history-report-v1",
        "db": str(db_path),
        "history_limit": limit,
        "turns_read": sum(len(turns) for turns in threads.values()),
        "threads": len(threads),
        "cases": cases,
        "compressed_cases": len(interactive),
        "chars_before": before,
        "chars_after": after,
        "chars_removed": before - after,
        "reduction_ratio": round((before - after) / before, 4) if before else 0.0,
        "heuristic_tokens_before": sum(
            case["heuristic_tokens_before"] for case in interactive
        ),
        "heuristic_tokens_after": sum(
            case["heuristic_tokens_after"] for case in interactive
        ),
        "all_user_messages_identical": all(
            case["user_messages_identical"] for case in cases
        ),
        "all_current_sources_present": all(
            case["current_source_present"] for case in interactive
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--json", type=Path, default=None)
    options = parser.parse_args()
    if not options.db.exists():
        print(f"missing database: {options.db}", file=sys.stderr)
        return 2

    report = build_report(options.db)
    if options.json:
        options.json.parent.mkdir(parents=True, exist_ok=True)
        options.json.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    for case in report["cases"]:
        stubbed = ",".join(
            str(item["revision"]) for item in case.get("stubbed_revisions", [])
        )
        print(
            f"{case['thread_id'][:24]} turn {case['position']} "
            f"[{case['status']}:{case['reason']}] "
            f"target={case.get('target_id')}@{case.get('target_revision')} "
            f"stubbed=[{stubbed}] "
            f"chars {case['chars_before']}->{case['chars_after']} "
            f"user_intact={case['user_messages_identical']} "
            f"source_intact={case['current_source_present']}"
        )
    print(
        f"TOTAL compressed={report['compressed_cases']}/{len(report['cases'])} "
        f"chars {report['chars_before']}->{report['chars_after']} "
        f"({report['reduction_ratio']:.1%}) "
        f"heuristic_tokens {report['heuristic_tokens_before']}->"
        f"{report['heuristic_tokens_after']}"
    )
    print(
        f"CHECK user_messages_identical={report['all_user_messages_identical']} "
        f"current_sources_present={report['all_current_sources_present']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
