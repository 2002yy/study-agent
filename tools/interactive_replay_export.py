"""Export saved interactive answers as runnable pages for offline replay.

Reads a runtime database, extracts every complete interactive document from
completed turns, and writes one self-contained HTML file per (component,
revision). No model is called: this only materialises what was already saved.

Usage:
    python tools/interactive_replay_export.py --db runtime.db --out replay-dir
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.interactive_history import find_interactive_versions  # noqa: E402

# The sandbox provides this bridge; replay must provide the same surface so a
# page is not failed for a missing host object it never controls.
BRIDGE_STUB = (
    "<script>window.studyUI={setState:function(){},onRestore:function(){}};</script>"
)


def page_wrapper(html: str) -> str:
    return (
        "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
        "<style>body{margin:16px;font:16px/1.6 system-ui,sans-serif}</style>"
        "</head><body>"
        + BRIDGE_STUB
        + html
        + "</body></html>"
    )


def collect(db_path: Path) -> list[dict]:
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            "select thread_id, id, user_message, assistant_message, created_at "
            "from chat_turns where status = 'completed' and assistant_message is not null "
            "order by created_at"
        ).fetchall()
    finally:
        connection.close()

    seen: set[str] = set()
    cases: list[dict] = []
    for row in rows:
        message = row["assistant_message"] or ""
        for version in find_interactive_versions(
            [{"role": "assistant", "content": message}]
        ):
            digest = hashlib.sha256(version.html.encode("utf-8")).hexdigest()[:16]
            key = f"{version.id}:{version.revision}:{digest}"
            if key in seen:
                continue
            seen.add(key)
            cases.append(
                {
                    "case_id": f"{version.id}-r{version.revision}-{digest}",
                    "thread_id": row["thread_id"],
                    "turn_id": row["id"],
                    "created_at": row["created_at"],
                    "prompt": row["user_message"] or "",
                    "component_id": version.id,
                    "revision": version.revision,
                    "title": version.title,
                    "summary": version.summary,
                    "html_chars": len(version.html),
                    "html": version.html,
                }
            )
    return cases


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    options = parser.parse_args()
    if not options.db.exists():
        print(f"missing database: {options.db}", file=sys.stderr)
        return 2

    cases = collect(options.db)
    options.out.mkdir(parents=True, exist_ok=True)
    index: list[dict] = []
    for case in cases:
        name = f"{case['case_id']}.html"
        (options.out / name).write_text(page_wrapper(case["html"]), encoding="utf-8")
        index.append({key: value for key, value in case.items() if key != "html"} | {"file": name})
    (options.out / "index.json").write_text(
        json.dumps(
            {"schema_version": "m4c-replay-v1", "db": str(options.db), "cases": index},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"exported {len(index)} documents to {options.out}")
    for case in index:
        print(
            f"  {case['case_id']}  {case['component_id']} r{case['revision']}  "
            f"{case['html_chars']} chars  {case['title']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
