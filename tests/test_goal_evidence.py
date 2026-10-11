"""M4-C4 / C2: goal-level evidence verification (keyword hits are never SUPPORTED)."""
from __future__ import annotations

import json

from src.web.link_discovery import verify_goal_evidence
from src.web.research_tool_agent import AgentBudget, run_tool_agent
from tests.test_research_tool_agent import FakeGateway

MECHANISM = (
    "多版本并发控制通过保留旧版本行来实现一致性：因为每个事务读取自己的快照，"
    "读操作不会阻塞写操作。代价是旧版本需要清理，否则会造成表膨胀。"
) * 2
KEYWORDS_ONLY = "漏斗 投掷器 传输 比较器 排序 漏斗" * 3   # a page that only shares words


_FILLER = "这是一段与目标无关的背景说明文字。" * 20      # longer than the verifier window


def test_relation_word_in_another_paragraph_is_not_support():
    """A relation word far from the goal terms must not certify the goal."""
    text = "快照 阻塞 一致性 的讨论。" + _FILLER + "因为天气很好，所以出门了。"
    assert len(text) > 300          # longer than the verifier's window, so the marker is out of it
    status, evidence = verify_goal_evidence(("快照", "阻塞", "一致性"), text)
    assert status == "explored", evidence


def test_conflicting_source_is_marked_conflict():
    text = "有说法认为快照会阻塞，但这种说法是错误的：因为多版本并发控制恰恰避免了阻塞。" * 4
    assert len(text) >= 120
    status, evidence = verify_goal_evidence(("快照", "阻塞"), text)
    assert status == "conflict" and evidence["conflict"], evidence


def test_two_insufficient_sources_do_not_add_up():
    first, _ = verify_goal_evidence(("快照", "阻塞", "代价"), "快照意味着一致性。" * 10)
    second, _ = verify_goal_evidence(("快照", "阻塞", "代价"), "阻塞 代价 的问题。" * 10)
    assert (first, second) == ("explored", "explored")


def test_supported_excerpt_is_locatable_in_the_body():
    status, evidence = verify_goal_evidence(("快照", "阻塞", "代价"), MECHANISM)
    assert status == "supported"
    assert evidence["excerpt"] and evidence["excerpt"] in MECHANISM.replace("\n", " ") or \
        evidence["excerpt"] in MECHANISM


def test_keyword_only_body_is_explored_not_supported():
    status, evidence = verify_goal_evidence(("漏斗", "投掷器", "排序"), KEYWORDS_ONLY)
    assert status == "explored"
    assert evidence["relation"] == ""


def test_mechanism_body_with_relation_marker_is_supported():
    status, evidence = verify_goal_evidence(
        ("快照", "阻塞", "代价"), MECHANISM)
    assert status == "supported"
    assert evidence["relation"] and evidence["excerpt"]


def test_unrelated_body_is_missing():
    status, _evidence = verify_goal_evidence(("真空", "膨胀"), "这是一段与目标毫无关系的文字。" * 5)
    assert status == "missing"


def test_partial_terms_stay_explored_even_with_a_marker():
    # only one of three terms present -> not a majority -> not supported
    status, _evidence = verify_goal_evidence(
        ("快照", "vacuum", "膨胀"), "因为需要快照，所以一致性得到保证。" * 3)
    assert status == "explored"


def _completion(actions, seen):
    seq = list(actions)

    def run(**kwargs):
        seen.append(json.loads(kwargs["messages"][-1]["content"]))
        return json.dumps(seq.pop(0))

    return run


def test_agent_records_evidence_per_goal_and_keeps_records_apart():
    gateway = FakeGateway()
    gateway.read = lambda url, max_chars=6000, timeout=8: {
        "ok": True, "url": url, "content": MECHANISM}
    trace = run_tool_agent(
        gateway=gateway, question="PostgreSQL 的快照如何避免阻塞？它有什么代价？",
        completion=_completion([{"tool": "read_page", "url": "https://example.org/a"},
                                {"tool": "finish"}], []),
        budget=AgentBudget(max_rounds=2, max_searches=2, max_reads=2, hard_seconds=30.0),
        initial_urls=("https://example.org/a",),
    )
    records = trace["goal_evidence"]
    assert records, trace["coverage_audit"]
    for label, items in records.items():
        assert items and all(item["url"] and item["host"] for item in items)
        assert all(item["status"] in {"explored", "supported"} for item in items)
        # each goal keeps its own record; nothing is merged into a shared claim
        assert label in trace["coverage_audit"]["sub_goals"]
