"""The candidate rule can NEVER grant support; only the claim verifier can (see
tests/test_evidence_loop.py). These tests pin the narrowed contract."""
from __future__ import annotations

import json

from src.web.link_discovery import classify_goal_candidate
from src.web.research_tool_agent import AgentBudget, run_tool_agent
from tests.test_research_tool_agent import FakeGateway

MECHANISM = (
    "多版本并发控制通过保留旧版本行来实现一致性：因为每个事务读取自己的快照，"
    "读操作不会阻塞写操作。代价是旧版本需要清理，否则会造成表膨胀。"
) * 2
KEYWORDS_ONLY = "漏斗 投掷器 传输 比较器 排序 漏斗" * 3


def test_candidate_rule_never_returns_support():
    for terms, text in ((("快照", "阻塞", "代价"), MECHANISM),
                        (("漏斗", "投掷器", "排序"), KEYWORDS_ONLY)):
        status, _evidence = classify_goal_candidate(terms, text)
        assert status in {"missing", "explored"}, status


def test_unrelated_body_is_missing():
    status, _evidence = classify_goal_candidate(("真空", "膨胀"), "这是一段与目标毫无关系的文字。" * 5)
    assert status == "missing"


def test_partial_terms_stay_explored():
    status, _evidence = classify_goal_candidate(
        ("快照", "vacuum", "膨胀"), "因为需要快照，所以一致性得到保证。" * 3)
    assert status == "explored"


def test_conflicting_wording_is_only_a_candidate_signal():
    text = "有说法认为快照会阻塞，但这种说法是错误的：因为多版本并发控制恰恰避免了阻塞。" * 4
    status, evidence = classify_goal_candidate(("快照", "阻塞"), text)
    assert status == "explored"                     # a flag, never a verdict
    assert evidence.get("conflict")


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
        # the keyword rule only ever produces candidates now
        assert all(item["status"] == "explored" for item in items)
        assert label in trace["coverage_audit"]["sub_goals"]
