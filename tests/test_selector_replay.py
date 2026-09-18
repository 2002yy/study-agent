"""§38b selector replay: frozen-pool A/B logic without model access."""

from __future__ import annotations

from tools.run_selector_replay import (
    agreed_targets,
    build_pool,
    replay,
    rule_selection,
)

NODE = "https://nodejs.cn/api/modules.html"


def _probe_case() -> dict:
    def result(url: str, *, selected: bool = False, reason: str = "") -> dict:
        return {
            "url": url,
            "title": "Title",
            "snippet": "Snippet",
            "selected_for_read": selected,
            "selection_reason": reason,
        }

    return {
        "case_id": "case-x",
        "question": "Which module systems does Node.js support?",
        "metrics": {
            "search_discovery": {
                "queries": [
                    {"results": [result("https://nodejs.org/", selected=True, reason="fallback_order")]},
                    {"results": [result(NODE), result("https://nodejs.cn/")]},
                ]
            }
        },
    }


def test_build_pool_dedupes_in_observation_order() -> None:
    pool = build_pool(_probe_case())
    assert [entry["url"] for entry in pool] == [
        "https://nodejs.org/",
        NODE,
        "https://nodejs.cn/",
    ]


def test_rule_selection_uses_sources_read_set() -> None:
    case = _probe_case()
    case["sources"] = [
        {"url": NODE, "read_status": "read", "source_role": "primary"},
        {"url": "https://nodejs.org/", "read_status": "failed", "source_role": "primary"},
    ]
    picks, reasons = rule_selection(case)
    assert picks == [NODE]
    assert reasons[NODE] == "source_role:primary"


def test_rule_selection_reads_the_frozen_decisions() -> None:
    picks, reasons = rule_selection(_probe_case())
    assert picks == ["https://nodejs.org/"]
    assert reasons["https://nodejs.org/"] == "fallback_order"


def test_agreed_targets_require_two_pass_agreement() -> None:
    annotations = {
        "merged": [
            {"case_id": "case-x", "canonical_url": NODE, "pass_a": "likely_target", "pass_b": "likely_target"},
            {"case_id": "case-x", "canonical_url": "https://nodejs.org/", "pass_a": "irrelevant", "pass_b": "irrelevant"},
            {"case_id": "other", "canonical_url": NODE, "pass_a": "likely_target", "pass_b": "likely_target"},
        ]
    }
    assert agreed_targets(annotations, "case-x") == [NODE]


def test_replay_compares_rule_and_model_picks() -> None:
    calls = {"count": 0}

    def selector(question: str, pool: list[dict], max_picks: int) -> list[str]:
        del question, max_picks
        calls["count"] += 1
        # Unstable model: hits on the first run, empty on the second.
        if calls["count"] == 1:
            return [entry["url"] for entry in pool if entry["url"] == NODE]
        return []

    cases = replay(
        {"cases": [_probe_case()]},
        {
            "merged": [
                {"case_id": "case-x", "canonical_url": NODE, "pass_a": "likely_target", "pass_b": "likely_target"}
            ]
        },
        selector=selector,
        repeat=2,
    )
    record = cases[0].to_dict()
    assert record["rule_target_hits"] == []
    assert record["model_target_hits"] == [NODE]
    assert record["model_target_rank"] == 1
    assert record["model_runs"] == 2
    assert record["model_hit_runs"] == 1
    assert record["model_empty_runs"] == 1


def test_model_failure_is_recorded_not_fatal() -> None:
    def selector(question: str, pool: list[dict], max_picks: int) -> list[str]:
        del question, pool, max_picks
        raise RuntimeError("model unavailable")

    cases = replay({"cases": [_probe_case()]}, {"merged": []}, selector=selector)
    assert cases[0].model_error.startswith("RuntimeError")
    assert cases[0].model_picks == []
