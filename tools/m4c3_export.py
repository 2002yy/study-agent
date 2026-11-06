"""Export unwrapped saved model HTML for offline product-sandbox replay."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from tools.interactive_replay_export import collect
from tools.m4c3_prepare import TASKS


def export_raw(db: Path | list[Path], out: Path, task_map: dict[str, str]) -> int:
    if any(task not in TASKS for task in task_map.values()):
        raise ValueError("task map contains an unknown frozen task")
    databases = [db] if isinstance(db, Path) else db
    cases = []
    seen = set()
    for source in databases:
        for case in collect(source):
            digest = hashlib.sha256(case["html"].encode("utf-8")).hexdigest()
            identity = (digest, tuple(case.get("capabilities", [])))
            if identity not in seen:
                cases.append(case | {"source_db": str(source.resolve())})
                seen.add(identity)
    # A fresh directory is mandatory: do not overwrite an earlier evidence run.
    out.mkdir(parents=True, exist_ok=False)
    index = []
    for number, case in enumerate(cases, 1):
        raw = case["html"].encode("utf-8")
        name = f"document-{number:04d}.html"
        (out / name).write_bytes(raw)
        index.append(
            {
                "case_id": f"document-{number:04d}",
                "file": name,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "source_kind": "saved_model",
                "task_id": task_map.get(case["component_id"]),
                "task_mapping": "explicit_component_map"
                if case["component_id"] in task_map
                else "unmapped",
                "component_id": case["component_id"],
                "revision": case["revision"],
                "capabilities": case.get("capabilities", []),
                "turn_id": case["turn_id"],
                "source_db": case["source_db"],
            }
        )
    (out / "index.json").write_text(
        json.dumps(
            {"schema_version": "m4c3-raw-v1", "cases": index},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return len(index)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path, action="append")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument(
        "--task-map", type=Path, help="Reviewed component-id to frozen-task-id JSON"
    )
    args = parser.parse_args()
    task_map = (
        json.loads(args.task_map.read_text(encoding="utf-8-sig"))
        if args.task_map
        else {}
    )
    print(
        f"Exported {export_raw(args.db, args.out, task_map)} raw documents; no model calls"
    )


if __name__ == "__main__":
    # Run as python -m tools.m4c3_export from the repository root.
    main()
