"""Recognize reviewed identities and checksums in the immutable RP-1 archive.

All scan plugins still run. No file, directory, key-name pattern, or generic hash
is excluded. A changed value/path/type/line/digest remains a finding.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import re
from pathlib import Path
from typing import Any

MANIFEST = "docs/evidence/rp1/2026-10-09/manifest.json"
REVIEWED_HEADS = {
    "research": "40e0e311eb9653282ae12b36d4835a3bfa68616b",
    "ui": "1a3d01bdd9bbddd6ca455bcade558754aecabc22",
    "planning_entry": "3c687b5f4eeb49ba6c5c42d18fb42668e7054057",
    "answer_shadow": "0cdcfe070853d7f09cae3527c57390d2819db276",
}


def filter_report(report: dict[str, Any], root: Path) -> tuple[dict[str, Any], int]:
    result = deepcopy(report)
    findings = result.get("results")
    if not isinstance(findings, dict):
        raise ValueError("invalid secrets report")
    artifact_removed = _filter_artifact_checksums(findings, root)
    manifest_key = next(
        (key for key in findings if key.replace("\\", "/") == MANIFEST), MANIFEST
    )
    rows = findings.get(manifest_key)
    if rows is None:
        return result, artifact_removed
    if not isinstance(rows, list):
        raise ValueError("invalid manifest findings")
    text = (root / MANIFEST).read_text(encoding="utf-8")
    manifest = json.loads(text)
    # Pin all four identities together, rather than accepting arbitrary hex.
    if manifest.get("source_heads") != REVIEWED_HEADS:
        return result, artifact_removed
    lines = text.splitlines()
    accepted: set[tuple[int, str]] = set()
    for key, value in REVIEWED_HEADS.items():
        expected = f'"{key}": "{value}"'
        matches = [
            index
            for index, line in enumerate(lines, 1)
            if line.strip().rstrip(",") == expected
        ]
        if len(matches) != 1:
            return result, artifact_removed
        accepted.add((matches[0], hashlib.sha1(value.encode()).hexdigest()))
    retained = []
    removed = 0
    for row in rows:
        identity = (row.get("line_number"), row.get("hashed_secret"))
        if (
            row.get("type") == "Hex High Entropy String"
            and row.get("filename", "").replace("\\", "/") == MANIFEST
            and identity in accepted
        ):
            accepted.remove(identity)
            removed += 1
        else:
            retained.append(row)
    if retained:
        findings[manifest_key] = retained
    else:
        findings.pop(manifest_key)
    return result, removed + artifact_removed


def _filter_artifact_checksums(findings: dict[str, Any], root: Path) -> int:
    baseline_path = root / "config/rp1_reviewed_hash_findings.json"
    if not baseline_path.is_file():
        return 0
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    manifest_path = root / MANIFEST
    if (
        hashlib.sha256(manifest_path.read_text(encoding="utf-8").encode()).hexdigest()
        != baseline["manifest_sha256"]
    ):
        return 0
    allowed: set[tuple[str, int, str, str]] = set()
    files: dict[str, bytes] = {}
    for item in baseline["reviewed_findings"]:
        filename = item["filename"]
        # The reviewed list is archive-specific. Never follow paths outside it.
        parts = Path(filename).parts
        if not filename.startswith("docs/evidence/rp1/2026-10-09/") or ".." in parts:
            raise ValueError("reviewed finding outside the immutable archive")
        if filename not in files:
            files[filename] = (root / filename).read_bytes()
        content = files[filename]
        if hashlib.sha256(content).hexdigest() != item["file_sha256"]:
            continue
        lines = content.decode("utf-8-sig").splitlines()
        line_number = item["line_number"]
        if not isinstance(line_number, int) or not 1 <= line_number <= len(lines):
            continue
        match = re.fullmatch(
            r'\s*"([^"\n]+)"\s*:\s*"([0-9a-fA-F]{64})"\s*,?\s*', lines[line_number - 1]
        )
        if not match or match.group(1) != item["json_key"]:
            continue
        if hashlib.sha1(match.group(2).encode()).hexdigest() != item["hashed_secret"]:
            continue
        allowed.add((filename, line_number, item["hashed_secret"], item["type"]))
    removed = 0
    for filename in list(findings):
        retained = []
        for row in findings[filename]:
            identity = (
                filename.replace("\\", "/"),
                row.get("line_number"),
                row.get("hashed_secret"),
                row.get("type"),
            )
            if (
                row.get("filename", "").replace("\\", "/") == identity[0]
                and identity in allowed
            ):
                allowed.remove(identity)
                removed += 1
            else:
                retained.append(row)
        if retained:
            findings[filename] = retained
        else:
            findings.pop(filename)
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report, removed = filter_report(
        json.loads(args.report.read_text(encoding="utf-8")),
        Path(__file__).resolve().parents[1],
    )
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        f"Reviewed RP-1 Git identities recognized: {removed}; all other findings retained"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
