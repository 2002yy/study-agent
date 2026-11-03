"""Survey saved sessions for real interactive documents, without model calls.

Walks a validation root, reads every completed assistant turn that still has a
SQLite runtime database, and reports the interactive documents it finds. The
survey is deliberately read-only and deduplicates identical documents by
content hash, so copied sessions do not inflate the sample count.

Usage:
    python tools/interactive_replay_survey.py --root D:\\study-agent-validation --out survey.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.interactive_history import find_interactive_versions  # noqa: E402

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from interactive_replay_export import page_wrapper  # noqa: E402

SKIP_PARTS = {".mypy_cache", "__pycache__", "node_modules", ".git"}

DOMAIN_HINTS = [
    ("J01", ("CacheEntry", "缓存", "引用", "对象1", "对象2")),
    ("P01", ("弹簧", "相位", "简谐", "sin(phase)")),
    ("A01", ("二分", "查找")),
    ("A02", ("Dijkstra", "最短路径", "最短路")),
    ("D01", ("转账", "事务", "回滚")),
    ("D02", ("丢失更新", "交错", "串行化", "库存 10")),
    ("C01", ("信号量", "许可", "semaphore")),
    ("M01", ("一次函数", "y=2x", "y = 2x")),
    ("M02", ("二次函数", "顶点", "零点")),
    ("S01", ("混淆矩阵", "精确率", "召回率")),
    ("N01", ("TCP", "握手", "SYN")),
]


def guess_domain(title: str, prompt: str) -> str:
    text = f"{title}\n{prompt}"
    for domain, hints in DOMAIN_HINTS:
        if any(hint in text for hint in hints):
            return domain
    if "库存" in text or "锁定" in text:
        return "inventory"
    return "other"


def survey_file(path: Path) -> list[dict]:
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return []
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "select name from sqlite_master where type = 'table'"
            ).fetchall()
        }
        if "chat_turns" not in tables:
            return []
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "select thread_id, id, user_message, assistant_message, created_at "
            "from chat_turns where status = 'completed' and assistant_message is not null"
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        connection.close()

    found: list[dict] = []
    for row in rows:
        message = row["assistant_message"] or ""
        for version in find_interactive_versions(
            [{"role": "assistant", "content": message}]
        ):
            digest = hashlib.sha256(version.html.encode("utf-8")).hexdigest()
            found.append(
                {
                    "db": str(path),
                    "thread_id": row["thread_id"],
                    "turn_id": row["id"],
                    "created_at": row["created_at"],
                    "prompt": (row["user_message"] or "")[:400],
                    "component_id": version.id,
                    "revision": version.revision,
                    "title": version.title,
                    "summary": version.summary,
                    "html_chars": len(version.html),
                    "html": version.html,
                    "sha256": digest,
                }
            )
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--export-dir", type=Path, default=None)
    options = parser.parse_args()
    if not options.root.exists():
        print(f"missing root: {options.root}", file=sys.stderr)
        return 2

    if options.export_dir is not None:
        options.export_dir.mkdir(parents=True, exist_ok=True)

    databases = [
        path
        for path in options.root.rglob("*.db")
        if not SKIP_PARTS.intersection(path.parts)
    ]
    documents: list[dict] = []
    index_cases: list[dict] = []
    duplicates = 0
    seen: set[str] = set()
    for path in databases:
        for document in survey_file(path):
            key = document["sha256"]
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            document["domain"] = guess_domain(document["title"], document["prompt"])
            html = document.pop("html", "")
            if options.export_dir is not None and html:
                name = f"{key[:16]}.html"
                (options.export_dir / name).write_text(
                    page_wrapper(html), encoding="utf-8"
                )
                document["file"] = name
                index_cases.append(
                    {
                        "case_id": f"{document['component_id']}-r{document['revision']}-{key[:16]}",
                        "thread_id": document["thread_id"],
                        "turn_id": document["turn_id"],
                        "created_at": document["created_at"],
                        "prompt": document["prompt"],
                        "component_id": document["component_id"],
                        "revision": document["revision"],
                        "title": document["title"],
                        "summary": document["summary"],
                        "html_chars": document["html_chars"],
                        "sha256": key,
                        "domain": document["domain"],
                        "db": document["db"],
                        "file": name,
                    }
                )
            documents.append(document)

    if options.export_dir is not None:
        (options.export_dir / "index.json").write_text(
            json.dumps(
                {
                    "schema_version": "m4c-replay-v1",
                    "root": str(options.root),
                    "cases": index_cases,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    by_domain = Counter(document["domain"] for document in documents)
    by_component = Counter(document["component_id"] for document in documents)
    report = {
        "schema_version": "m4c-real-doc-survey-v1",
        "root": str(options.root),
        "databases_scanned": len(databases),
        "documents": documents,
        "duplicates_skipped": duplicates,
        "by_domain": dict(sorted(by_domain.items())),
        "by_component": dict(sorted(by_component.items())),
    }
    options.out.parent.mkdir(parents=True, exist_ok=True)
    options.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"scanned {len(databases)} databases, found {len(documents)} unique documents "
        f"({duplicates} duplicates skipped)"
    )
    for domain, count in sorted(by_domain.items()):
        print(f"  {domain}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
