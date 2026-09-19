"""§43B selector A/B: injection, classification and summary contracts."""

from __future__ import annotations

from tools.run_selector_ab import classify


def test_classification_covers_wins_ties_losses() -> None:
    assert classify(legacy_hit=False, hybrid_hit=True) == "win"
    assert classify(legacy_hit=True, hybrid_hit=True) == "tie"
    assert classify(legacy_hit=True, hybrid_hit=False) == "loss"
    assert classify(legacy_hit=False, hybrid_hit=False) == "tie"


def test_injected_targets_are_the_known_authoritative_pages() -> None:
    from tools.run_selector_ab import INJECTED_TARGETS

    assert INJECTED_TARGETS["rq1c-current-policy-container-registry"]["url"] == (
        "https://docs.docker.com/docker-hub/usage/pulls/"
    )
    assert INJECTED_TARGETS["rq1c-current-support-postgresql"]["url"] == (
        "https://www.postgresql.org/support/versioning/"
    )
    assert INJECTED_TARGETS["rq1c-simple-license-uv"]["url"].startswith(
        "https://github.com/astral-sh/uv"
    )


def test_run_ab_is_paired_on_the_same_pool_with_injected_fallback() -> None:
    from tools.run_selector_ab import run_ab

    probe = {
        "cases": [
            {
                "case_id": "rq1c-current-policy-container-registry",
                "question": "What pull-rate limits apply?",
                "metrics": {
                    "search_discovery": {
                        "queries": [
                            {
                                "results": [
                                    {"url": "https://www.docker.com/", "title": "Docker"},
                                    {"url": "https://example.com/a", "title": "A"},
                                ]
                            }
                        ]
                    }
                },
            }
        ]
    }
    annotations: dict = {"merged": []}
    tmp_probe = __import__("pathlib").Path(
        r"C:\Users\Zhang\AppData\Local\Temp\opencode\ab_probe.json"
    )
    tmp_ann = __import__("pathlib").Path(
        r"C:\Users\Zhang\AppData\Local\Temp\opencode\ab_ann.json"
    )
    tmp_out = __import__("pathlib").Path(
        r"C:\Users\Zhang\AppData\Local\Temp\opencode\ab_out.json"
    )
    import json

    tmp_probe.write_text(json.dumps(probe), encoding="utf-8")
    tmp_ann.write_text(json.dumps(annotations), encoding="utf-8")

    class _Diagnostics:
        selection_source = "model"
        unusable_reason = ""

    def caller(items, *, claim_text, assignments, max_picks):
        target = next(item for item in items if "docs.docker.com" in item.canonical_url)
        return (target,), _Diagnostics()

    def reader(url):
        return {"ok": True, "content": "pull rate limits"}

    artifact = run_ab(
        probe_path=tmp_probe,
        annotations_path=tmp_ann,
        output_path=tmp_out,
        read_targets=True,
        selector_caller=caller,
        reader=reader,
    )
    row = artifact["pools"][0]
    assert row["pool_source"] == "injected"
    assert row["targets"] == ["https://docs.docker.com/docker-hub/usage/pulls/"]
    assert row["legacy_hit"] is False
    assert row["hybrid_hit"] is True
    assert row["outcome"] == "win"
    assert row["target_read_hybrid"] == "ok"
    summary = artifact["summary"]
    assert summary["wins"] == 1
    assert summary["losses"] == 0
    assert summary["selector_caused_losses"] == 0
    assert summary["incremental_target_reads"] == 1
    assert summary["orchestration_model_calls"] == 1
