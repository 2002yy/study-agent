from __future__ import annotations

from copy import deepcopy
import hashlib
import json

import pytest

from tools.filter_verified_evidence_hashes import (
    MANIFEST,
    REVIEWED_HEADS,
    filter_report,
)


@pytest.fixture
def scanned(tmp_path):
    path = tmp_path / MANIFEST
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"source_heads": REVIEWED_HEADS}, indent=2), encoding="utf-8"
    )
    rows = []
    for key, value in REVIEWED_HEADS.items():
        line = next(
            i
            for i, text in enumerate(path.read_text().splitlines(), 1)
            if f'"{key}"' in text
        )
        rows.append(
            {
                "filename": MANIFEST,
                "line_number": line,
                "hashed_secret": hashlib.sha1(value.encode()).hexdigest(),
                "type": "Hex High Entropy String",
            }
        )
    return tmp_path, {"results": {MANIFEST: rows}}


def test_only_the_four_reviewed_manifest_identities_are_recognized(scanned):
    root, report = scanned
    original = deepcopy(report)
    result, removed = filter_report(report, root)
    assert removed == 4 and result["results"] == {}
    assert report == original


@pytest.mark.parametrize(
    "field,value",
    [
        ("filename", "src/config.py"),
        ("line_number", 999),
        ("hashed_secret", "unreviewed-secret"),
        ("type", "Secret Keyword"),
    ],
)
def test_changed_finding_identity_is_still_blocking(scanned, field, value):
    root, report = scanned
    report["results"][MANIFEST][0][field] = value
    result, removed = filter_report(report, root)
    assert removed == 3
    assert len(result["results"][MANIFEST]) == 1


def test_other_manifest_secrets_and_other_files_are_retained(scanned):
    root, report = scanned
    secret = {
        "filename": MANIFEST,
        "line_number": 1,
        "hashed_secret": "actual-api-key",
        "type": "Hex High Entropy String",
    }
    report["results"][MANIFEST].append(secret)
    report["results"]["src/config.py"] = [deepcopy(report["results"][MANIFEST][0])]
    result, removed = filter_report(report, root)
    assert removed == 4
    assert result["results"][MANIFEST] == [secret]
    assert result["results"]["src/config.py"] == report["results"]["src/config.py"]


def test_changed_source_head_disables_the_entire_recognition(scanned):
    root, report = scanned
    changed = dict(REVIEWED_HEADS, research="f" * 40)
    (root / MANIFEST).write_text(
        json.dumps({"source_heads": changed}), encoding="utf-8"
    )
    result, removed = filter_report(report, root)
    assert removed == 0 and result == report


def test_duplicate_source_line_is_not_recognized(scanned):
    root, report = scanned
    path = root / MANIFEST
    text = path.read_text()
    line = next(line for line in text.splitlines() if '"research"' in line)
    path.write_text(text.replace(line, line + "\n" + line), encoding="utf-8")
    result, removed = filter_report(report, root)
    assert removed == 0 and result == report


def test_missing_manifest_findings_does_not_require_the_archive(tmp_path):
    report = {"results": {"src/config.py": [{"type": "Secret Keyword"}]}}
    assert filter_report(report, tmp_path) == (report, 0)


def test_malformed_scanner_report_fails_closed(tmp_path):
    with pytest.raises(ValueError, match="invalid secrets report"):
        filter_report({}, tmp_path)


@pytest.fixture
def artifact_scan(scanned):
    root, report = scanned
    filename = "docs/evidence/rp1/2026-10-09/row.json"
    content = json.dumps({"original_sha256": "a1" * 32}, indent=2) + "\n"
    (root / filename).write_text(content, encoding="utf-8")
    row = {
        "filename": filename,
        "line_number": 2,
        "hashed_secret": hashlib.sha1(("a1" * 32).encode()).hexdigest(),
        "type": "Hex High Entropy String",
    }
    baseline = {
        "manifest_sha256": hashlib.sha256(
            (root / MANIFEST).read_text(encoding="utf-8").encode()
        ).hexdigest(),
        "reviewed_findings": [
            dict(
                row,
                file_sha256=hashlib.sha256((root / filename).read_bytes()).hexdigest(),
                json_key="original_sha256",
            )
        ],
    }
    (root / "config").mkdir()
    (root / "config/rp1_reviewed_hash_findings.json").write_text(
        json.dumps(baseline), encoding="utf-8"
    )
    report["results"][filename] = [row]
    return root, report, filename


def test_reviewed_archive_checksum_is_verified_against_frozen_bytes(artifact_scan):
    root, report, _ = artifact_scan
    result, removed = filter_report(report, root)
    assert removed == 5 and result["results"] == {}


@pytest.mark.parametrize(
    "field,value",
    [
        ("filename", "src/config.py"),
        ("line_number", 3),
        ("hashed_secret", "new-secret"),
        ("type", "AWS Access Key"),
    ],
)
def test_changed_artifact_finding_still_blocks(artifact_scan, field, value):
    root, report, filename = artifact_scan
    report["results"][filename][0][field] = value
    result, removed = filter_report(report, root)
    assert removed == 4 and len(result["results"][filename]) == 1


def test_changed_artifact_bytes_disable_checksum_recognition(artifact_scan):
    root, report, filename = artifact_scan
    with (root / filename).open("a", encoding="utf-8") as stream:
        stream.write(" ")
    result, removed = filter_report(report, root)
    assert removed == 4 and len(result["results"][filename]) == 1


def test_changed_archive_manifest_disables_checksum_recognition(artifact_scan):
    root, report, filename = artifact_scan
    with (root / MANIFEST).open("a", encoding="utf-8") as stream:
        stream.write(" ")
    result, removed = filter_report(report, root)
    assert removed == 4 and len(result["results"][filename]) == 1


def test_windows_report_paths_are_supported_without_widening_scope(artifact_scan):
    root, report, _ = artifact_scan
    report["results"] = {
        key.replace("/", "\\"): [
            dict(row, filename=row["filename"].replace("/", "\\")) for row in rows
        ]
        for key, rows in report["results"].items()
    }
    result, removed = filter_report(report, root)
    assert removed == 5 and result["results"] == {}


def _metadata_rows(root, filename):
    import re

    rows = []
    for line_number, line in enumerate(
        (root / filename).read_text(encoding="utf-8").splitlines(), 1
    ):
        match = re.fullmatch(
            r'\s*"[^"\n]+"\s*:\s*"([0-9a-f]{40}|[0-9a-f]{64})"\s*,?\s*', line
        )
        if match:
            rows.append(
                {
                    "filename": filename,
                    "line_number": line_number,
                    "hashed_secret": hashlib.sha1(match.group(1).encode()).hexdigest(),
                    "type": "Hex High Entropy String",
                }
            )
    return rows


def test_only_recomputed_baseline_metadata_is_recognized(artifact_scan):
    root, report, _ = artifact_scan
    filename = "config/rp1_reviewed_hash_findings.json"
    data = json.loads((root / filename).read_text(encoding="utf-8"))
    (root / filename).write_text(json.dumps(data, indent=2), encoding="utf-8")
    report["results"][filename] = _metadata_rows(root, filename)
    result, removed = filter_report(report, root)
    assert removed == 8 and result["results"] == {}


def test_other_secret_in_baseline_file_is_still_blocking(artifact_scan):
    root, report, _ = artifact_scan
    filename = "config/rp1_reviewed_hash_findings.json"
    data = json.loads((root / filename).read_text(encoding="utf-8"))
    data["api_key"] = "b4" * 20
    (root / filename).write_text(json.dumps(data, indent=2), encoding="utf-8")
    report["results"][filename] = _metadata_rows(root, filename)
    result, removed = filter_report(report, root)
    assert removed == 8 and len(result["results"][filename]) == 1


def test_tool_constants_recognize_only_the_four_pinned_git_identities(artifact_scan):
    root, report, _ = artifact_scan
    filename = "tools/filter_verified_evidence_hashes.py"
    (root / "tools").mkdir()
    values = dict(REVIEWED_HEADS, api_key="c3" * 20)
    (root / filename).write_text(json.dumps(values, indent=2), encoding="utf-8")
    report["results"][filename] = _metadata_rows(root, filename)
    result, removed = filter_report(report, root)
    assert removed == 9 and len(result["results"][filename]) == 1
