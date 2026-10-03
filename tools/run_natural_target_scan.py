"""§43C natural selection-lift samplecollection: scan natural runs for pools
that already contain a known target page.

Nothing about selector behaviour changes here: this tool only reads natural
runtime artifacts (the same case runner used everywhere else), rebuilds each
case's candidate pool from its own recorded search discovery, checks whether a
known target page is present, and freezes every *distinct* natural
target-containing pool for the later paired A/B replay.

Known targets are the agreed Node annotations plus the authoritative pages for
the Docker, PostgreSQL and uv cases; they are ground truth for presence only -
this tool never claims the runtime should have recalled them.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.run_selector_replay import build_pool  # noqa: E402

SCHEMA_VERSION = "natural-target-scan-v1"

KNOWN_TARGETS: dict[str, tuple[str, ...]] = {
    "rq1c-historical-current-node-modules": (
        "https://nodejs.cn/api/modules.html",
        "https://node.org.cn/api/modules.html",
    ),
    "rq1c-current-policy-container-registry": (
        "https://docs.docker.com/docker-hub/usage/pulls/",
    ),
    "rq1c-current-support-postgresql": (
        "https://www.postgresql.org/support/versioning/",
    ),
    "rq1c-simple-license-uv": (
        "https://github.com/astral-sh/uv/blob/main/LICENSE-MIT",
    ),
}


def scan_artifact(artifact: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return one natural-pool entry per case whose pool contains a target."""

    rows: list[dict[str, Any]] = []
    for case in artifact.get("cases") or []:
        if not isinstance(case, Mapping):
            continue
        case_id = str(case.get("case_id") or case.get("id") or "")
        known = KNOWN_TARGETS.get(case_id)
        if not known:
            continue
        pool = build_pool(case)
        present = [url for url in known if any(url == entry["url"] for entry in pool)]
        if not present:
            continue
        rows.append(
            {
                "case_id": case_id,
                "question": str(case.get("question") or ""),
                "pool": pool,
                "targets": present,
                "pool_source": "natural",
            }
        )
    return rows


@dataclass
class NaturalScan:
    pools: list[dict[str, Any]] = field(default_factory=list)
    scanned: int = 0
    target_present_cases: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "diagnostic_only": True,
            "qualification_evidence": False,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "scanned_artifacts": self.scanned,
            "natural_pools": len(self.pools),
            "pools": self.pools,
        }


def run_scan(*, artifacts: Iterable[Path], output_path: Path) -> dict[str, Any]:
    scan = NaturalScan()
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for path in artifacts:
        if not path.exists():
            continue
        try:
            artifact = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        scan.scanned += 1
        for row in scan_artifact(artifact):
            key = (row["case_id"], tuple(entry["url"] for entry in row["pool"]))
            if key in seen:
                continue
            seen.add(key)
            row["source_artifact"] = path.name
            scan.pools.append(row)
    payload = scan.to_dict()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    payload = run_scan(artifacts=args.artifacts, output_path=args.output.resolve())
    print(
        json.dumps(
            {
                "scanned_artifacts": payload["scanned_artifacts"],
                "natural_pools": payload["natural_pools"],
                "pools": [
                    {"case": row["case_id"], "targets": row["targets"]}
                    for row in payload["pools"]
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
