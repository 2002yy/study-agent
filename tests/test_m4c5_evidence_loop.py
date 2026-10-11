"""M4-C5 positive and negative controls: truth, anchors, gaps and total cost."""
from __future__ import annotations

import json

import pytest

from src.web.research_assertion_extractor import (
    extraction_messages, source_snapshots, validate_proposals,
)
from src.web.research_assertion_verifier import bind_and_verify
from src.web.research_notebook import ResearchNotebook
from src.web.research_tool_agent import AgentBudget, run_tool_agent
from tests.test_research_tool_agent import FakeGateway


POSTGRES = (
    "PostgreSQL 使用多版本并发控制：读事务读取旧版本快照，因此读操作不会阻塞写操作。"
    "主要代价是需要清理旧行版本，清理滞后会造成表膨胀、存储开销增加。"
) * 3
MINECRAFT = (
    "在 Minecraft 中，漏斗会从上方容器取出物品并向指定容器传输。"
    "比较器可以读取容器装填状态，但比较器不会自行决定漏斗的物品排序。"
    "如需按物品类型分类，必须额外使用过滤结构来控制流向。"
) * 3


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    import src.web.research_tool_agent as agent

    monkeypatch.setattr(agent, "host_resolves_public", lambda host: True)


def test_exact_span_required_and_model_cannot_forge_sources():
    notebook = ResearchNotebook()
    notebook.record("https://example.org/a", "https://example.org/final", POSTGRES)
    sources = source_snapshots(notebook.bodies)
    messages = extraction_messages("阻塞代价", {"g": ("阻塞",)}, sources)
    assert sources[0]["source_id"] in messages[-1]["content"]
    records, rejected = validate_proposals(json.dumps({"claims": [
        {"goal": "g", "source_id": sources[0]["source_id"],
         "claim": "读操作不会阻塞写操作", "quote": "读操作不会阻塞写操作"},
        {"goal": "g", "source_id": "invented",
         "claim": "这里没有可信来源", "quote": "读操作不会阻塞写操作"},
        {"goal": "g", "source_id": sources[0]["source_id"],
         "claim": "错误引用来自不存在的片段", "quote": "这段文字并不存在"},
    ]}, ensure_ascii=False), sources, {"g": ("阻塞",)})
    assert len(records) == 1 and len(rejected) == 2
    assert records[0]["content_hash"] == sources[0]["content_hash"]
    assert sources[0]["text"][records[0]["span_start"]:records[0]["span_end"]] == records[0]["quote"]


def test_independent_verification_support_conflict_abstain_and_unavailable():
    notebook = ResearchNotebook()
    notebook.record("https://example.org/a", "https://example.org/a", POSTGRES)
    sources = source_snapshots(notebook.bodies)
    claim = {"goal": "g", "source_id": sources[0]["source_id"],
             "claim": "读不会阻塞写", "quote": "读操作不会阻塞写操作"}
    records, _ = validate_proposals(
        json.dumps({"claims": [claim]}, ensure_ascii=False), sources, {"g": ()})
    assert len(records) == 1
    vote = lambda status: json.dumps({"verdicts": [
        {"claim_id": "c1", "status": status}]})
    assert bind_and_verify(vote("supported"), records, sources)[0]["status"] == "supported"
    assert bind_and_verify(vote("insufficient"), records, sources)[0]["status"] == "insufficient"
    assert bind_and_verify(vote("conflict"), records, sources)[0]["status"] == "conflict"
    assert bind_and_verify("{}", records, sources)[0]["status"] == "abstain"
    assert bind_and_verify(vote("supported"), records, [])[0]["status"] == "unavailable"
    tampered = [dict(records[0], span_start=0)]
    assert bind_and_verify(vote("supported"), tampered, sources)[0]["status"] == "unavailable"


def _run(body, *, statuses, question, actions, max_rounds=5, search_results=None):
    gateway = FakeGateway(results=search_results)
    gateway.read = lambda url, max_chars=6000, timeout=8: {
        "ok": True, "url": url, "content": body[url] if isinstance(body, dict) else body}
    model_tasks = []
    model_prompts = []

    def completion(**kwargs):
        task = kwargs["task_name"]
        model_tasks.append(task)
        data = json.loads(kwargs["messages"][-1]["content"])
        model_prompts.append(data)
        if task == "research_assertion_extract":
            source = data["sources"][0]
            labels = data["goals"]
            claims = []
            for i, label in enumerate(labels[:len(statuses)]):
                if "PostgreSQL" in question and i == 0:
                    claim, quote = (
                        "多版本快照允许读写并发", "读操作不会阻塞写操作")
                elif "PostgreSQL" in question:
                    claim, quote = (
                        "旧行版本清理滞后导致表膨胀和存储成本",
                        "清理滞后会造成表膨胀、存储开销增加")
                else:
                    claim, quote = (
                        "比较器只读取容器状态，不自行决定物品排序",
                        "比较器可以读取容器装填状态，但比较器不会自行决定漏斗的物品排序")
                claims.append({
                    "goal": label, "source_id": source["source_id"],
                    "claim": claim, "quote": quote,
                })
            return json.dumps({"claims": claims}, ensure_ascii=False)
        if task == "research_assertion_verify":
            rows = data["assertions"]
            return json.dumps({"verdicts": [
                {"claim_id": row["claim_id"], "status": statuses[i]}
                for i, row in enumerate(rows)]})
        assert task == "research_tool_agent"
        action = actions.pop(0)
        if action == "gap_search":
            assert data["action_state"]["gap_queries"]
            action = {"tool": "search",
                      "query": data["action_state"]["gap_queries"][0]["query"]}
        return json.dumps(action, ensure_ascii=False)

    trace = run_tool_agent(
        gateway=gateway, completion=completion, question=question,
        budget=AgentBudget(max_rounds=max_rounds, max_searches=3,
                           max_reads=3, hard_seconds=90),
        initial_urls=("https://example.org/a",), evidence_loop=True,
        entry_selection=False,
    )
    return trace, model_tasks, model_prompts


def test_postgresql_positive_loop_proves_actual_claim_and_does_not_publish():
    trace, tasks, prompts = _run(
        POSTGRES, statuses=["supported", "supported"],
        question="PostgreSQL 如何避免读写阻塞，主要代价是什么？",
        actions=[{"tool": "read_page", "url": "https://example.org/a"},
                 {"tool": "finish"}], max_rounds=2,
    )
    assert tasks.count("research_assertion_extract") == 1
    assert tasks.count("research_assertion_verify") == 1
    assert trace["cost"]["model_calls"] == len(tasks) == 4
    assert trace["coverage_audit"]["complete"]
    assert trace["publication_authority"] is False
    assert all(row["status"] == "supported"
               for row in trace["coverage_audit"]["sub_goals"].values())
    assert all(row["verified_by"] == "independent_semantic"
               for row in trace["assertion_verdicts"])
    assert prompts[-1]["research_notebook"]["semantic_batch_used"]


def test_minecraft_keyword_page_not_supported_without_semantic_verdict():
    trace, tasks, _ = _run(
        MINECRAFT, statuses=["insufficient"],
        question="Minecraft 漏斗如何传输与排序物品？",
        actions=[{"tool": "read_page", "url": "https://example.org/a"},
                 {"tool": "finish"}], max_rounds=2,
    )
    assert trace["coverage_audit"]["complete"] is False
    assert all(item["status"] != "supported" for items in trace["goal_evidence"].values()
               for item in items)
    assert "research_assertion_verify" in tasks


def test_later_article_is_pending_not_automatically_verified():
    trace, tasks, prompts = _run(
        {"https://example.org/a": POSTGRES,
         "https://example.org/b": "主要代价是旧行版本清理和表膨胀。" * 5},
        statuses=["supported"],
        question="PostgreSQL 快照为什么不阻塞写，主要代价是什么？",
        actions=[{"tool": "read_page", "url": "https://example.org/a"},
                 "gap_search",
                 {"tool": "read_page", "url": "https://example.org/b"},
                 {"tool": "finish"}],
        max_rounds=4, search_results=[{"title": "cost", "url": "https://example.org/b",
                                       "snippet": "vacuum"}],
    )
    assert tasks.count("research_assertion_verify") == 1
    assert trace["post_verification_reads"] == ["https://example.org/b"]
    assert not trace["coverage_audit"]["complete"]
    assert any("pending_new_read" == row.get("verification_state")
               for items in trace["goal_evidence"].values() for row in items)
    assert any(prompt.get("action_state", {}).get("gap_queries") for prompt in prompts)


def test_legacy_keyword_path_is_never_authoritative():
    gateway = FakeGateway()
    gateway.read = lambda url, max_chars=6000, timeout=8: {
        "ok": True, "url": url, "content": POSTGRES}
    seq = iter([{"tool": "read_page", "url": "https://example.org/a"},
                {"tool": "finish"}])
    trace = run_tool_agent(
        gateway=gateway, completion=lambda **kwargs: json.dumps(next(seq)),
        question="PostgreSQL 如何避免阻塞，主要代价是什么？",
        budget=AgentBudget(max_rounds=2), initial_urls=("https://example.org/a",),
        evidence_loop=False,
    )
    assert not any(state["status"] == "supported"
                   for state in trace["coverage_audit"]["sub_goals"].values())
    assert not trace["extraction_used"]
    assert trace["publication_authority"] is False


def test_keyword_coverage_alone_can_never_mark_an_unverified_run_complete():
    gateway = FakeGateway()
    gateway.read = lambda url, max_chars=6000, timeout=8: {
        "ok": True, "url": url, "content": "PostgreSQL " * 100}
    actions = iter([
        {"tool": "read_page", "url": "https://example.org/a"},
        {"tool": "finish"},
    ])
    trace = run_tool_agent(
        gateway=gateway, completion=lambda **kwargs: json.dumps(next(actions)),
        question="PostgreSQL", budget=AgentBudget(max_rounds=2),
        initial_urls=("https://example.org/a",), evidence_loop=False,
    )
    assert not trace["coverage_audit"]["complete"]
    assert trace["coverage_audit"]["semantic_required"]


def test_global_model_call_ceiling_includes_research_and_verification():
    gateway = FakeGateway()
    serial = 0

    def completion(**kwargs):
        nonlocal serial
        serial += 1
        return json.dumps({"tool": "search", "query": f"query {serial}"})

    trace = run_tool_agent(
        gateway=gateway, completion=completion,
        question="unanswered topic", evidence_loop=True,
        budget=AgentBudget(max_rounds=40, max_searches=40,
                           max_reads=2, hard_seconds=180),
    )
    assert trace["cost"]["model_calls"] <= 22
    assert serial <= 22
    assert not trace["coverage_audit"]["complete"]
