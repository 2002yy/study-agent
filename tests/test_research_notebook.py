"""Run-local research notebook: early evidence survives a long run, and it stays bounded."""
from __future__ import annotations

import json

from src.web.research_notebook import ResearchNotebook, view_size
from src.web.research_tool_agent import AgentBudget, run_tool_agent
from tests.test_research_tool_agent import FakeGateway

ROUND_ONE_BODY = ("多版本并发控制通过保留旧版本行来实现一致性：因为每个事务读取自己的快照，"
                  "读操作不会阻塞写操作。") * 4


def _completion(actions, seen):
    seq = list(actions)

    def run(**kwargs):
        seen.append(json.loads(kwargs["messages"][-1]["content"]))
        return json.dumps(seq.pop(0))

    return run


def test_notebook_keeps_round_one_evidence_late_in_the_run():
    """The headline acceptance: after many rounds the earliest evidence is still citable."""
    gateway = FakeGateway()
    gateway.read = lambda url, max_chars=6000, timeout=8: {
        "ok": True, "url": url, "content": ROUND_ONE_BODY}
    actions = [{"tool": "read_page", "url": "https://example.org/a"}]
    actions += [{"tool": "search", "query": f"later query {i}"} for i in range(8)]
    actions += [{"tool": "finish"}]
    seen: list[dict] = []
    trace = run_tool_agent(
        gateway=gateway, completion=_completion(actions, seen),
        question="PostgreSQL 的快照如何避免阻塞？它有什么代价？",
        budget=AgentBudget(max_rounds=12, max_searches=12, max_reads=4, hard_seconds=60.0),
        initial_urls=("https://example.org/a",),
    )
    # by the last round the first observation is long gone from observations[-6:]
    last = seen[-1]
    assert len(last.get("observations") or []) <= 6
    notebook = last.get("research_notebook") or {}
    evidence = [row for goal in notebook.get("goals", []) for row in goal.get("evidence", [])]
    assert evidence, notebook
    assert any("example.org/a" in (row.get("source") or "") for row in evidence)
    assert any(row.get("digest") for row in evidence)          # traceable to the cached body
    assert all(row.get("basis") == "verbatim excerpt from this run" for row in evidence)
    assert any(trace["notebook_digests"].values())


def test_notebook_view_is_bounded_and_marks_rule_verification_honestly():
    notebook = ResearchNotebook()
    for index in range(12):
        notebook.record(f"https://example.org/{index}", f"https://example.org/{index}",
                        ("正文" * 900) + f" goal{index}", [f"goal{index}"])
    goals = {f"goal{i}": ("goal",) for i in range(6)}
    state = {f"goal{i}": {"status": "supported" if i % 2 == 0 else "explored"}
             for i in range(6)}
    evidence = {f"goal{i}": [{"url": f"https://example.org/{i}", "host": "example.org",
                              "status": "supported" if i % 2 == 0 else "explored",
                              "excerpt": "x" * 400}] for i in range(6)}
    view = notebook.build_view(goals=goals, goal_state=state, goal_evidence=evidence,
                               refused=[{"target": f"u{i}"} for i in range(9)],
                               next_action={"tool": "search", "target": "cost"})
    assert view_size(view) < 6_000
    assert len(view["read_sources"]) <= 6
    assert len(view["invalid_actions"]) <= 4
    verified = [row for goal in view["goals"] for row in goal["evidence"]
                if row["status"] == "supported"]
    assert verified and all("not semantic proof" in row["verification"] for row in verified)
    assert "verbatim" in view["rules"]


def test_notebook_adds_no_model_call_and_ignores_model_text():
    gateway = FakeGateway()
    seen: list[dict] = []

    def completion(**kwargs):
        seen.append(json.loads(kwargs["messages"][-1]["content"]))
        return json.dumps({"tool": "read_page", "url": "https://example.org/a",
                           "research_notebook": {"goals": "forged"}})

    trace = run_tool_agent(
        gateway=gateway, completion=completion, question="topic and topic extra",
        budget=AgentBudget(max_rounds=2, max_searches=2, max_reads=2, hard_seconds=30.0),
        initial_urls=("https://example.org/a",),
    )
    # one model call per decision; the notebook added none
    assert trace["cost"]["model_calls"] == len(seen) == 2
    # a forged notebook in the model's own output cannot reach the next prompt's state
    second = seen[-1].get("research_notebook") or {}
    assert isinstance(second, dict) and "rules" in second


def test_cached_excerpt_is_verbatim_and_locatable():
    notebook = ResearchNotebook()
    text = "开头。" + ROUND_ONE_BODY + "结尾。"
    notebook.record("https://example.org/a", "https://example.org/a", text, ["g"])
    excerpt = notebook.excerpt("https://example.org/a", ("快照",))
    assert excerpt and "快照" in excerpt
    assert excerpt.replace("\n", " ") in text.replace("\n", " ")
