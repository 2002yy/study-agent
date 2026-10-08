from __future__ import annotations

import pytest

from src.web.research_recovery import (
    STANDARD_BUDGET, recover_public_research, recovery_summary, select_research_queries,
)
from src.web.tool_evidence import evidence_tool_calls
from src.web.tool_gateway import GeneralWebGateway
from tests.test_research_recovery import Gateway, item


def test_selection_covers_late_questions_before_redundant_early_proposals():
    proposals = [
        {"rq_id": "rq-a", "query": "topic overview"},
        {"rq_id": "rq-a", "query": "topic overview details"},
        {"rq_id": "rq-a", "query": "topic overview other"},
        {"rq_id": "rq-b", "query": "topic cost"},
        {"rq_id": "rq-c", "query": "site:python.org topic reliability"},
    ]
    selected, trace = select_research_queries(proposals, 3, "site:python.org topic", ["python.org"])
    assert {rq for row in selected for rq in row["rq_ids"]} == {"rq-a", "rq-b", "rq-c"}
    assert selected[0]["rq_ids"] == ["rq-c"]
    assert len(trace["deferred"]) == 2
    assert {row["reason"] for row in trace["deferred"]} == {"execution_slot_limit"}
    assert select_research_queries(proposals, 3, "site:python.org topic", ["python.org"]) == (selected, trace)


def test_selection_deduplicates_queries_and_preserves_all_bound_rqs():
    proposals = [{"rq_id": "rq-a", "query": "Topic Cost"},
                 {"rq_id": "rq-b", "query": "topic  cost"},
                 {"rq_id": "rq-c", "query": "site:python.org topic"}]
    selected, trace = select_research_queries(proposals, 3, "site:python.org topic", ["python.org"])
    assert len(selected) == 1 and selected[0]["rq_ids"] == ["rq-a", "rq-b"]
    assert trace["covered_rq_ids"] == ["rq-a", "rq-b", "rq-c"]
    assert trace["deferred"][0]["reason"] == "duplicate_query"


def test_five_proposals_do_not_increase_standard_execution_budget():
    gateway = Gateway([[]] * 5, {})
    proposals = [{"rq_id": f"rq-{i}", "query": f"Python 3.14 facet {i}"} for i in range(5)]
    calls = recover_public_research(gateway, "Python 3.14", budget=STANDARD_BUDGET,
                                   query_plan=proposals)
    summary = recovery_summary(calls)
    assert len(gateway.queries) <= 4 == STANDARD_BUDGET.max_queries
    assert summary["searches"] <= 4 and summary["limits"]["hard_seconds"] == 60
    assert len(summary["query_selection"]["deferred"]) == 2


def trace(requested: str, final: str, *, declared_request: str | None = None):
    result = {"ok": True, "url": final, "content": "Claude Opus 5.5 release details"}
    if declared_request is not None:
        result["requested_url"] = declared_request
    return [
        {"name": "web_search", "arguments": {"query": "opus5.5"},
         "result": {"status": "ok", "results": [item("old-release")]}},
        {"name": "web_read", "arguments": {"url": requested}, "result": result},
    ]


def test_discovered_read_keeps_public_redirect_destination_without_fabricating_search():
    requested = item("old-release")["url"]
    final = "https://www.anthropic.com/news/claude-opus-5-5"
    calls = trace(requested, final)
    assert evidence_tool_calls(calls)[0]["result"]["url"] == final
    assert calls[0]["result"]["results"] == [item("old-release")]


@pytest.mark.parametrize("requested,final,declared", [
    ("https://unrelated.example/source", item("old-release")["url"], None),
    (item("old-release")["url"], "http://127.0.0.1/private", None),
    (item("old-release")["url"], "https://example.org/release", "https://example.org/other"),
    ("", item("old-release")["url"], None),
])
def test_redirect_never_bypasses_discovery_or_public_url_boundary(requested, final, declared):
    assert evidence_tool_calls(trace(requested, final, declared_request=declared)) == []


def test_recovery_adopts_redirect_body_instead_of_exhausting_candidate_budget():
    final = "https://www.anthropic.com/news/claude-opus-5-5"
    gateway = Gateway([[item("old-release")]], {
        "old-release": {"ok": True, "url": final, "content": "Claude Opus 5.5 release details"},
    })
    calls = recover_public_research(gateway, "opus5.5")
    assert recovery_summary(calls)["status"] == "read_backed"
    assert evidence_tool_calls(calls)[0]["result"]["url"] == final
    assert len(gateway.reads) == 1


def test_weak_overlap_body_is_rejected_and_next_candidate_is_read():
    gateway = Gateway([[item("recipe", title="苹果最近有什么新闻"),
                        item("news", title="苹果最近有什么新闻")]],
                      {"recipe": "苹果怎么吃", "news": "苹果最近有什么新闻：产品发布。"})
    calls = recover_public_research(gateway, "苹果最近有什么新闻")
    rejected = next(c for c in calls if c.get("name") == "web_read")
    assert rejected["result"]["answer_eligible"] is False
    assert rejected["result"]["adequacy_reason"] == "unrelated_body"
    assert len(gateway.reads) == 2
    assert [c["arguments"]["url"] for c in evidence_tool_calls(calls)] == [item("news")["url"]]


def test_final_lookup_phase_uses_unspent_slots_after_region_redirect():
    gateway = Gateway([[], [
        {"title": "Claude Opus 5.5 model docs", "url": "https://platform.claude.com/docs/overview"},
        item("release"),
    ]], {"overview": {"ok": True, "url": "https://claude.com/app-unavailable-in-region",
                       "content": "Unavailable in region"},
         "release": "Claude Opus 5.5 release details"})
    calls = recover_public_research(gateway, "opus5.5")
    assert len(gateway.reads) == 2
    assert len(evidence_tool_calls(calls)) == 1
    assert recovery_summary(calls)["limits"]["reads"] == 3


def test_planned_official_domain_is_used_for_non_anthropic_query():
    gateway = Gateway([[], [item("release", title="Python 3.14 release date")]],
                      {"release": "Python 3.14 release date"})
    recover_public_research(gateway, "Python3.14", query_plan=[
        {"rq_id": "rq-release", "query": "Python 3.14 release date"},
        {"rq_id": "rq-release", "query": "site:python.org Python 3.14 release"},
    ])
    assert gateway.queries[1] == "site:python.org Python 3.14"


def test_site_filter_keeps_subdomains_and_rejects_engine_scope_leaks(monkeypatch):
    gateway = GeneralWebGateway()
    monkeypatch.setattr(gateway, "_search_single", lambda *_: {
        "results": [{"title": "official", "url": "https://docs.python.org/3.14/"},
                    {"title": "wrong", "url": "https://python.org.evil.example/3.14/"}],
        "provider_errors": [], "providers_attempted": ["bing_rss"],
    })
    result = gateway.search_exact("site:python.org Python 3.14")
    assert [item["url"] for item in result["results"]] == ["https://docs.python.org/3.14/"]
    assert result["domain_filtered_count"] == 1


def test_domain_filter_does_not_invent_complex_operator_semantics(monkeypatch):
    gateway = GeneralWebGateway()
    payload = {"results": [{"title": "other", "url": "https://example.org/"}],
               "provider_errors": [], "providers_attempted": ["bing_rss"]}
    monkeypatch.setattr(gateway, "_search_single", lambda *_: payload)
    assert gateway.search_exact("site:python.org OR site:example.org Python")["results"] == payload["results"]


def test_out_of_domain_only_results_are_empty_instead_of_official_success(monkeypatch):
    gateway = GeneralWebGateway()
    monkeypatch.setattr(gateway, "_search_single", lambda *_: {
        "results": [{"title": "other", "url": "https://example.org/release"}],
        "provider_errors": [], "providers_attempted": ["bing_rss"],
    })
    result = gateway.search_exact("site:python.org Python 3.14")
    assert result["status"] == "empty"
    assert result["reason"] == "domain_constraint_rejected_results"
