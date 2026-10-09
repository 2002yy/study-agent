from __future__ import annotations

import threading

import pytest

from src.application.web_lookup_service import WebLookupService
from src.application.chat_service import _tool_context
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.web_lookup_repository import WebLookupRepository
from src.tools.persistent_web_agent import PersistentWebToolAgent
from src.tools.web_agent import WebToolTrace
from src.web.research_recovery import (
    STANDARD_BUDGET,
    model_targets,
    recover_public_research,
    recovery_budget,
    recovery_summary,
)
from src.web.search_query_quality import (
    classify_candidate,
    optimize_search_query,
    order_candidates,
)
from src.web.tool_evidence import evidence_tool_calls


def test_optimize_search_query_removes_generic_but_keeps_entities():
    text, reason = optimize_search_query("比较 Factorio 2.0 列车中断 与 固定时刻表")
    assert "比较" not in text
    assert "Factorio 2.0" in text
    assert reason.startswith("generic_tokens_removed")


def test_optimize_search_query_falls_back_unchanged():
    assert optimize_search_query("空气源热泵")[1] == "unchanged"


def test_order_candidates_entity_and_relevance_beat_raw_order():
    import re

    marker = re.compile(r"Factorio 2\.0", re.IGNORECASE)
    weak = {"assessment": {"url": "https://dict.example/比较"}, "item": {"title": "比较 定义", "snippet": "比较"}}
    strong = {"assessment": {"url": "https://factorio.com/train"}, "item": {"title": "Factorio 2.0 train interrupts", "snippet": "Factorio 2.0"}}
    ordered = order_candidates([weak, strong], relevance_by_url={}, markers=[marker])
    assert ordered[0]["assessment"]["url"] == "https://factorio.com/train"
    a = {"assessment": {"url": "u-a"}, "item": {"title": "", "snippet": ""}}
    b = {"assessment": {"url": "u-b"}, "item": {"title": "", "snippet": ""}}
    ordered2 = order_candidates([b, a], relevance_by_url={"u-a": ["rq-1"]}, markers=[marker])
    assert ordered2[0]["assessment"]["url"] == "u-a"


def test_classify_candidate_three_way():
    assert classify_candidate(related_ids=["rq-1"], judged=True) == "relevant"
    assert classify_candidate(related_ids=[], judged=True) == "off_target"
    assert classify_candidate(related_ids=[], judged=False) == "unknown"


def item(path, *, title="Claude Opus 5.5 reference"):
    return {
        "title": title,
        "url": f"https://www.anthropic.com/{path}",
        "snippet": "candidate only",
    }


class Gateway:
    def __init__(self, searches, bodies, clock=None):
        self.searches = iter(searches)
        self.bodies = bodies
        self.queries = []
        self.reads = []
        self.clock = clock

    def search_exact(self, query, *, max_results):
        self.queries.append(query)
        result = next(self.searches, [])
        if isinstance(result, Exception):
            raise result
        return (
            result
            if isinstance(result, dict)
            else {"status": "ok" if result else "empty", "results": result}
        )

    def read(self, url, *, max_chars, timeout):
        self.reads.append((url, max_chars, timeout))
        body = self.bodies[url.rsplit("/", 1)[-1]]
        if isinstance(body, Exception):
            raise body
        return (
            body
            if isinstance(body, dict)
            else {"ok": True, "url": url, "content": body}
        )


def test_first_read_timeout_recovers_with_alternate_without_replanning():
    gateway = Gateway(
        [[item("timeout"), item("release")]],
        {
            "timeout": TimeoutError("page_timeout"),
            "release": "Claude Opus 5.5 release details.",
        },
    )
    calls = recover_public_research(gateway, "opus5.5")
    assert len(gateway.queries) == 1
    assert len(gateway.reads) == 2
    assert recovery_summary(calls)["status"] == "read_backed"
    assert len(evidence_tool_calls(calls)) == 1


def test_regional_doc_mirrors_do_not_crowd_out_discovered_release_page():
    english = {
        "title": "Claude Opus 5.5",
        "url": "https://platform.claude.com/docs/en/overview",
    }
    chinese = {
        "title": "Claude Opus 5.5",
        "url": "https://platform.claude.com/docs/zh/overview",
    }
    gateway = Gateway(
        [[english, chinese, item("release")]],
        {
            "overview": {
                "ok": True,
                "url": "https://claude.com/app-unavailable-in-region",
                "content": "App unavailable in region",
            },
            "release": "Claude Opus 5.5 release documentation.",
        },
    )
    calls = recover_public_research(gateway, "opus5.5")
    assert [url for url, _, _ in gateway.reads] == [
        english["url"],
        item("release")["url"],
    ]
    assert recovery_summary(calls)["status"] == "read_backed"
    assert recovery_summary(calls)["reads"] == 2
    assert len(evidence_tool_calls(calls)) == 1
    scheduler = recovery_summary(calls)["candidate_scheduler"]
    assert scheduler["unique_canonical_docs"] == 2
    assert scheduler["unique_source_families"] == 2
    assert scheduler["host_state"]["platform.claude.com"]["cooldown"] is True


def test_homepage_and_unrelated_body_do_not_finalize_before_authority_refinement():
    gateway = Gateway(
        [[item(""), item("wrong")], [item("release")]],
        {
            "wrong": "Welcome to our video app",
            "release": "Claude Opus 5.5 release details.",
        },
    )
    calls = recover_public_research(gateway, "opus5.5")
    assert len(gateway.queries) == 2
    assert "site:anthropic.com" in gateway.queries[1]
    assert "site:platform.claude.com" in gateway.queries[1]
    assert not any(url.endswith(".com/") for url, _, _ in gateway.reads)
    assert [row["result"]["content"] for row in evidence_tool_calls(calls)] == [
        "Claude Opus 5.5 release details."
    ]
    assert "wrong" not in WebToolTrace(calls=tuple(calls)).context_block()


def test_multi_aspect_opus_golden_rejects_dictionary_and_reads_alternate_sources():
    gateway = Gateway(
        [[item("dictionary"), item("release")], [item("benchmark")]],
        {
            "dictionary": "Dictionary fixture: the meaning of retry.",
            "release": "Fixture: Claude Opus 5.5 release body.",
            "benchmark": "Fixture: Claude Opus 5.5 performance comparison body.",
        },
    )
    query = "opus5.5是什么？性能如何？对比？"
    trace = WebToolTrace(calls=tuple(recover_public_research(gateway, query)))
    data = trace.to_dict()
    assert data["recovery"]["query"] == query
    assert data["recovery"]["mode"] == "standard"
    assert data["recovery"]["reads"] == 3
    assert data["recovery"]["question_coverage"] == "not_semantically_evaluated"
    assert len(data["used_sources"]) == 2
    assert all(not row["url"].endswith("dictionary") for row in data["used_sources"])
    assert "Dictionary fixture" not in trace.context_block()
    assert gateway.queries[0] == query
    assert gateway.queries[1] == "Claude opus 5.5 official"


def test_model_query_rewrite_keeps_both_comparison_subjects():
    gateway = Gateway([[], [], [], []], {})
    query = "opus5.5对比Gemini3.1性能如何？"
    calls = recover_public_research(gateway, query)
    assert recovery_summary(calls)["query"] == query
    assert "opus 5.5" in gateway.queries[1]
    assert "Gemini 3.1" in gateway.queries[1]
    assert "性能如何" not in gateway.queries[1]


def test_short_chinese_topic_does_not_adopt_a_one_character_dictionary_entry():
    gateway = Gateway(
        [[item("dictionary", title="赵的意思")], [item("person", title="赵翠")]],
        {
            "dictionary": "赵：dictionary fixture for a surname.",
            "person": "赵翠：fixture entry containing the complete requested name.",
        },
    )
    trace = WebToolTrace(calls=tuple(recover_public_research(gateway, "赵翠")))
    assert len(gateway.reads) == 2
    assert [row["url"] for row in trace.to_dict()["used_sources"]] == [item("person")["url"]]
    assert "dictionary fixture" not in trace.context_block()
    rejected = next(call for call in trace.calls if call["name"] == "web_read")
    assert rejected["result"]["adequacy_reason"] == "literal_topic_absent"


def test_standard_reserves_two_reads_and_two_authority_queries():
    searches = [[item("a"), item("b")], [item("c")], [item("d")], [item("e")]]
    bodies = {key: f"Unrelated unique body {key}" for key in "abcde"}
    gateway = Gateway(searches, bodies)
    calls = recover_public_research(gateway, "比较opus5.5和GPT6.1")
    final = recovery_summary(calls)
    assert final["mode"] == "standard"
    assert final["reads"] == 5
    assert final["recovery_reads"] == 2
    assert final["authority_queries"] == 2
    assert final["query_rewrites"] == 2
    assert final["status"] == "budget_exhausted"
    assert evidence_tool_calls(calls) == []
    assert all(limit == 6000 for _, limit, _ in gateway.reads)


def test_comparison_does_not_stop_after_only_one_model_is_read():
    searches = [
        [item("one"), item("two")],
        [item("three", title="GPT 6.1 documentation")],
    ]
    gateway = Gateway(
        searches,
        {
            "one": "Opus 5.5 feature A",
            "two": "Opus 5.5 feature B",
            "three": "GPT 6.1 feature C",
        },
    )
    calls = recover_public_research(gateway, "比较Opus5.5与GPT6.1")
    final = recovery_summary(calls)
    assert final["reads"] == 3
    assert final["target_coverage"] == {"covered": 2, "required": 2}
    assert final["question_coverage"] == "not_semantically_evaluated"


def test_repeat_candidates_stop_as_bounded_saturation_not_nonexistence():
    gateway = Gateway([[item("old")], [item("old")]], {"old": "Claude Opus 4.5"})
    calls = recover_public_research(gateway, "opus5.5")
    assert len(gateway.reads) == 1
    assert recovery_summary(calls)["status"] == "candidate_exhausted"
    assert recovery_summary(calls)["stop_reason"] == "CANDIDATE_EXHAUSTED"
    assert evidence_tool_calls(calls) == []
    assert "已尝试读取" in WebToolTrace(calls=tuple(calls)).to_dict()["error"]


def test_character_budget_includes_rejected_bodies_and_enforces_last_read_limit():
    gateway = Gateway(
        [[item("a"), item("b")], [item("c")], [item("d")], [item("e")]],
        {key: key * 9000 for key in "abcde"},
    )
    calls = recover_public_research(gateway, "比较opus5.5", budget=STANDARD_BUDGET)
    assert recovery_summary(calls)["used_chars"] == 24000
    assert recovery_summary(calls)["status"] == "budget_exhausted"
    assert len(gateway.reads) == 4
    assert all(
        len(row["result"].get("content", "")) <= row["arguments"]["max_chars"]
        for row in calls
        if row["name"] == "web_read"
    )


def test_provider_failures_are_not_misreported_as_evidence_saturation():
    gateway = Gateway(
        [TimeoutError("search_timeout"), TimeoutError("search_timeout")], {}
    )
    calls = recover_public_research(gateway, "opus5.5")
    assert recovery_summary(calls)["status"] == "provider_exhausted"
    assert recovery_summary(calls)["stop_reason"] == "PROVIDER_EXHAUSTED"


def test_disabled_providers_are_a_hard_failure_without_retry():
    gateway = Gateway(
        [{"status": "unavailable", "reason": "no_search_provider_enabled"}], {}
    )
    calls = recover_public_research(gateway, "opus5.5")
    assert len(gateway.queries) == 1
    assert recovery_summary(calls)["status"] == "hard_tool_failure"


def test_deadline_preserves_finalization_reserve_and_rejects_late_search_body():
    clock = [0.0]

    class DelayedGateway(Gateway):
        def search_exact(self, query, **kwargs):
            result = super().search_exact(query, **kwargs)
            clock[0] = 49
            return result

    gateway = DelayedGateway([[item("late")]], {})
    calls = recover_public_research(
        gateway, "比较opus5.5", budget=STANDARD_BUDGET, monotonic=lambda: clock[0]
    )
    assert recovery_summary(calls)["reason"] == "finalization_reserve_preserved"
    assert recovery_summary(calls)["stop_reason"] == "DEADLINE_EXHAUSTED"
    assert gateway.reads == []
    assert evidence_tool_calls(calls) == []


def test_cancel_during_blocked_network_returns_without_late_trace_mutation():
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()

    class BlockedGateway:
        def search_exact(self, *_args, **_kwargs):
            entered.set()
            release.wait(timeout=2)
            finished.set()
            return {"status": "ok", "results": [item("late")]}

    try:
        calls = recover_public_research(
            BlockedGateway(), "opus5.5", should_cancel=entered.is_set
        )
        snapshot = repr(calls)
        assert recovery_summary(calls)["status"] == "cancelled"
    finally:
        release.set()
    assert finished.wait(timeout=2)
    assert repr(calls) == snapshot
    assert evidence_tool_calls(calls) == []


@pytest.mark.parametrize(
    "query,mode",
    [
        ("opus5.5", "lookup"),
        ("研究opus5.5", "lookup"),
        ("比较opus5.5和GPT6.1", "standard"),
    ],
)
def test_mode_follows_complexity_not_research_word(query, mode):
    assert recovery_budget(query).mode == mode
    assert model_targets(query)[0] == ("opus", "5.5")


def test_success_does_not_use_reserved_reads_or_all_query_budget():
    gateway = Gateway([[item("release")]], {"release": "Claude Opus 5.5 details."})
    calls = recover_public_research(gateway, "opus5.5")
    assert recovery_summary(calls)["recovery_reads"] == 0
    assert recovery_summary(calls)["searches"] == 1


def test_discovery_binding_and_legacy_github_evidence_remain_fail_closed():
    calls = [
        {
            "name": "web_read",
            "arguments": {"url": "https://www.anthropic.com/missing"},
            "result": {
                "ok": True,
                "url": "https://www.anthropic.com/missing",
                "content": "Opus 5.5",
            },
        }
    ]
    assert evidence_tool_calls(calls) == []
    github = {
        "name": "github_pr",
        "arguments": {},
        "result": {"ok": True, "url": "https://github.com/a/b/pull/1"},
    }
    assert evidence_tool_calls([github]) == [github]


def test_recovery_diagnostics_and_evidence_survive_real_repository_restore(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("WEB_DEEP_RESEARCH_ENABLED", "0")
    gateway = Gateway(
        [[item("wrong")], [item("release")]],
        {"wrong": "unrelated body", "release": "Claude Opus 5.5 release details"},
    )
    repository = WebLookupRepository(RuntimeDatabase(tmp_path / "recovery.db"))
    service = WebLookupService(repository, gateway)
    trace = PersistentWebToolAgent(
        gateway=gateway,
        research_service=service,
        run_loop=lambda *_a, **_k: pytest.fail("model planner must not run"),
    ).resolve(
        "请联网研究：opus5.5",
        research_intent=True,
        owner_thread_id="thread",
        owner_turn_id="turn",
    )
    restored = service.get(trace.run_id)
    assert (
        restored.research_context["tool_trace"]["recovery"]
        == trace.to_dict()["recovery"]
    )
    assert len(restored.selected_sources) == 1
    assert restored.selected_sources[0]["item"]["url"].endswith("/release")
    assert "unrelated body" not in restored.source_block
    assert trace.used is True


def test_opus_real_trajectory_is_replayed_through_agent_and_durable_runs(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("WEB_DEEP_RESEARCH_ENABLED", "0")
    gateway = Gateway(
        [[item("")], [item("release")]] * 5,
        {"release": "Claude Opus 5.5 release documentation."},
    )
    service = WebLookupService(
        WebLookupRepository(RuntimeDatabase(tmp_path / "golden.db")), gateway
    )
    agent = PersistentWebToolAgent(
        gateway=gateway,
        research_service=service,
        run_loop=lambda *_a, **_k: pytest.fail("unnecessary model planner"),
    )
    history = []
    sequence = [
        "请联网研究：opus5.5",
        "是最新的a÷模型。你联网没有找到内容吗？不太可能吧",
        "claude啊？你不知道吗？",
        "？意思刚刚你没有搜？",
        "快去",
    ]
    for index, text in enumerate(sequence):
        trace = agent.resolve(
            text,
            conversation_context=_tool_context(history),
            research_intent=index == 0,
            owner_thread_id="golden",
            owner_turn_id=f"t{index}",
        )
        assert trace.used
        assert "opus5.5" in gateway.queries[-2].casefold()
        assert "site:anthropic.com" in gateway.queries[-1]
        assert (
            service.get(trace.run_id)
            .selected_sources[0]["item"]["url"]
            .endswith("/release")
        )
        assert trace.to_dict()["recovery"]["mode"] == "lookup"
        history.extend(
            [
                {"role": "user", "content": text},
                {
                    "role": "assistant",
                    "content": "Unable to confirm; should I search again?",
                },
            ]
        )
    assert all(query != "快去" and "快手" not in query for query in gateway.queries)
