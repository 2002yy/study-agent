"""Deterministic tests for the support formation audit tooling."""

from __future__ import annotations

import json
from pathlib import Path

from tools.run_support_formation_audit import (
    SCHEMA_VERSION,
    _excerpt,
    anchor_hints,
    audit,
    load_audit_rows,
)


def _artifact(tmp_path: Path, *, relation: str = "lead") -> Path:
    payload = {
        "git_sha": "a" * 40,
        "cases": [
            {
                "case_id": "case-x",
                "gate": {"status": "block"},
                "brief": {
                    "eligible_evidence": [
                        {
                            "claim_id": "claim-1",
                            "url": "https://example.test/doc",
                            "relation": relation,
                            "strength": 0.1,
                            "locator": "支持版本为 18、17、16",
                            "anchored_spans": ["支持版本为 18、17、16"],
                            "caveats": ["does not state EOL dates"],
                            "source_role": "primary",
                            "title": "Official docs",
                        },
                        {
                            "claim_id": "claim-1",
                            "url": "https://example.test/doc",
                            "relation": "lead",
                            "strength": 0.2,
                            "locator": "",
                            "anchored_spans": [],
                            "caveats": [],
                            "source_role": "aggregator",
                            "title": "Mirror",
                        },
                    ]
                },
            }
        ],
    }
    path = tmp_path / "artifact.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_audit_rows_preserve_stored_verdicts(tmp_path: Path) -> None:
    rows = load_audit_rows(_artifact(tmp_path))

    assert len(rows) == 2
    assert rows[0]["relation"] == "lead"
    assert rows[0]["caveats"] == ["does not state EOL dates"]
    assert rows[0]["anchored_spans"] == ["支持版本为 18、17、16"]
    assert rows[1]["anchored_spans"] == []


def test_anchor_hints_detect_present_and_absent_anchors() -> None:
    row = {
        "locator": "支持版本为 18、17、16",
        "anchored_spans": ["支持版本为 18、17、16"],
    }

    present = anchor_hints(row, "前言。支持版本为 18、17、16。后记")
    assert present["anchor_hits"] == 1
    assert present["locator_hit"] is True
    assert present["hint"] == "page_contains_recorded_anchors"
    assert present["anchor_numbers_missing_from_page"] == []

    absent = anchor_hints(row, "这是一个与版本支持无关的页面")
    assert absent["anchor_hits"] == 0
    assert absent["hint"] == "recorded_anchors_absent_from_page"


def test_anchor_hints_flag_numbers_missing_from_the_page() -> None:
    row = {"locator": "", "anchored_spans": ["pull rate 100 and 200 requests"]}

    hints = anchor_hints(row, "pull rate 100 requests")

    assert hints["anchor_numbers"] == ["100", "200"]
    assert hints["anchor_numbers_missing_from_page"] == ["200"]
    # An anchor mismatch and a number mismatch are both only hints for review.
    assert hints["hint"] == "recorded_anchors_absent_from_page"


def test_excerpt_centres_on_the_first_anchor_hit() -> None:
    content = ("x" * 500) + "支持版本为 18、17、16" + ("y" * 500)

    excerpt = _excerpt(content, ["支持版本为 18、17、16"])

    assert "支持版本为 18、17、16" in excerpt
    assert len(excerpt) <= 1200


def test_excerpt_falls_back_to_the_head_when_no_anchor_matches() -> None:
    content = "z" * 3000

    excerpt = _excerpt(content, ["missing anchor text"])

    assert excerpt == content[:1200]


def test_audit_without_fetch_keeps_classification_empty(tmp_path: Path) -> None:
    artifact_path = _artifact(tmp_path)
    output = tmp_path / "audit.json"

    result = audit(
        artifact_paths=[artifact_path],
        output_path=output,
        max_rows=10,
        fetch=False,
    )

    assert result["schema_version"] == SCHEMA_VERSION
    assert result["diagnostic_only"] is True
    assert result["qualification_evidence"] is False
    assert result["row_count"] == 2
    assert result["relation_counts"] == {"lead": 2}
    assert all(row["human_classification"] == "" for row in result["rows"])
    assert "human reviewer" in result["method_note"]
    assert output.exists()


def test_missing_artifact_is_skipped_not_faked(tmp_path: Path) -> None:
    result = audit(
        artifact_paths=[tmp_path / "does-not-exist.json"],
        output_path=tmp_path / "audit.json",
        max_rows=10,
        fetch=False,
    )

    assert result["row_count"] == 0
    assert result["rows"] == []
