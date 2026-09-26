"""§37B-selection provenance extractor contract tests."""

from __future__ import annotations

from tools.run_selection_provenance import (
    agreed_likely_targets,
    load_selection_trace,
    summarize,
)

NODE = "https://nodejs.cn/api/modules.html"


def _artifact(trace: dict | None) -> dict:
    metrics: dict = {}
    if trace is not None:
        metrics["selection_trace"] = trace
    return {"cases": [{"case_id": "case-x", "metrics": metrics}]}


def test_load_selection_trace_reports_missing_instrumentation() -> None:
    payload = load_selection_trace(_artifact(None))
    assert payload["observed"] is False
    assert payload["cases"][0]["trace_present"] is False


def test_summarize_counts_reasons_and_named_targets() -> None:
    trace = {
        "entries": [
            {
                "canonical_url": NODE,
                "seen_in_provider": True,
                "materialized": True,
                "deduped_survivor": True,
                "entered_candidate_pool": True,
                "entered_scheduler": True,
                "scheduler_rank": 2,
                "scheduler_decision": "rejected",
                "terminal_reason": "scheduler_not_selected",
                "observed_drops": ["scheduler_not_selected"],
            },
            {
                "canonical_url": "https://example.com/other",
                "seen_in_provider": True,
                "materialized": True,
                "deduped_survivor": True,
                "terminal_reason": "unobserved",
            },
        ]
    }
    summary = summarize(load_selection_trace(_artifact(trace)), [NODE, "https://missing"])
    assert summary["terminal_reason_counts"] == {
        "scheduler_not_selected": 1,
        "unobserved": 1,
    }
    assert summary["targets"][0]["terminal_reason"] == "scheduler_not_selected"
    assert summary["targets"][1] == {
        "canonical_url": "https://missing",
        "observed": False,
        "terminal_reason": "unobserved",
        "row": None,
    }


def test_agreed_targets_are_deduplicated() -> None:
    annotations = {
        "annotations": [
            {"canonical_url": NODE, "candidate_classification": "likely_target"},
            {"canonical_url": NODE, "candidate_classification": "likely_target"},
            {"canonical_url": "https://x", "candidate_classification": "near_hit"},
        ]
    }
    assert agreed_likely_targets(annotations) == [NODE]


def test_agreed_targets_from_two_pass_merge_require_agreement() -> None:
    merged = {
        "merged": [
            {"canonical_url": NODE, "pass_a": "likely_target", "pass_b": "likely_target"},
            {"canonical_url": "https://x", "pass_a": "likely_target", "pass_b": "near_hit"},
            {"canonical_url": "https://y", "pass_a": "irrelevant", "pass_b": "irrelevant"},
        ]
    }
    assert agreed_likely_targets(merged) == [NODE]
