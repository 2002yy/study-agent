"""§43C natural scan + AB pool-file contracts."""

from __future__ import annotations

import json
from pathlib import Path

from tools.run_natural_target_scan import KNOWN_TARGETS, scan_artifact


def _artifact(pool_urls: list[str]) -> dict:
    return {
        "cases": [
            {
                "case_id": "rq1c-historical-current-node-modules",
                "question": "Which module systems?",
                "metrics": {
                    "search_discovery": {
                        "queries": [
                            {
                                "results": [
                                    {"url": url, "title": url, "snippet": ""}
                                    for url in pool_urls
                                ]
                            }
                        ]
                    }
                },
            }
        ]
    }


def test_scan_finds_target_containing_pool() -> None:
    target = KNOWN_TARGETS["rq1c-historical-current-node-modules"][0]
    rows = scan_artifact(_artifact(["https://example.com/a", target]))
    assert len(rows) == 1
    assert rows[0]["targets"] == [target]
    assert rows[0]["pool_source"] == "natural"


def test_scan_skips_pools_without_targets() -> None:
    assert scan_artifact(_artifact(["https://example.com/a"])) == []


def test_natural_scan_dedupes_identical_pools(tmp_path: Path) -> None:
    from tools.run_natural_target_scan import run_scan

    target = KNOWN_TARGETS["rq1c-historical-current-node-modules"][0]
    artifact = tmp_path / "a.json"
    artifact.write_text(json.dumps(_artifact([target])), encoding="utf-8")
    duplicate = tmp_path / "b.json"
    duplicate.write_text(json.dumps(_artifact([target])), encoding="utf-8")
    payload = run_scan(artifacts=[artifact, duplicate], output_path=tmp_path / "out.json")
    assert payload["scanned_artifacts"] == 2
    assert payload["natural_pools"] == 1


def test_ab_pools_file_runs_without_probe(tmp_path: Path) -> None:
    from tools.run_selector_ab import run_ab

    pools_file = tmp_path / "pools.json"
    pools_file.write_text(
        json.dumps(
            {
                "pools": [
                    {
                        "case_id": "case_x",
                        "question": "q",
                        "pool": [
                            {"url": "https://example.com/a", "title": "a"},
                            {"url": "https://example.com/b", "title": "b"},
                            {"url": "https://example.com/target", "title": "target"},
                        ],
                        "targets": ["https://example.com/target"],
                        "pool_source": "natural",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    class _Diagnostics:
        selection_source = "model"
        unusable_reason = ""

    def caller(items, *, claim_text, assignments, max_picks):
        target = next(item for item in items if item.canonical_url.endswith("target"))
        return (target,), _Diagnostics()

    artifact = run_ab(
        pools_file=pools_file,
        output_path=tmp_path / "out.json",
        read_targets=False,
        selector_caller=caller,
        reader=lambda url: {"ok": True, "content": "x"},
    )
    row = artifact["pools"][0]
    assert row["pool_source"] == "natural"
    assert row["pool_class"] == "A_recovery"
    assert row["outcome"] == "win"
    assert row["replacement_loss"] is False
    summary = artifact["summary"]
    assert summary["replacement_losses"] == 0
    assert summary["pool_classes"] == {"A_recovery": 1, "B_preservation": 0}


def test_ab_counts_replacement_loss_when_legacy_hits_and_hybrid_misses(
    tmp_path: Path,
) -> None:
    from tools.run_selector_ab import run_ab

    pools_file = tmp_path / "pools.json"
    pools_file.write_text(
        json.dumps(
            {
                "pools": [
                    {
                        "case_id": "case_y",
                        "question": "q",
                        "pool": [{"url": "https://example.com/target", "title": "t"}],
                        "targets": ["https://example.com/target"],
                        "pool_source": "natural",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    class _Diagnostics:
        selection_source = "model"
        unusable_reason = ""

    def caller(items, *, claim_text, assignments, max_picks):
        return (), _Diagnostics()

    artifact = run_ab(
        pools_file=pools_file,
        output_path=tmp_path / "out.json",
        read_targets=False,
        selector_caller=caller,
        reader=lambda url: {"ok": True, "content": "x"},
    )
    assert artifact["summary"]["losses"] == 1
    assert artifact["summary"]["replacement_losses"] == 1
