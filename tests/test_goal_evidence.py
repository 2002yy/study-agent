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
