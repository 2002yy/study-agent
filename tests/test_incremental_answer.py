"""Incremental Answer-1A: provisional replies during a real Deep run.

The production service factory, the production planner and a real SQLite
database are used; only the external transports and the model provider are
scripted.  No paid call is made.

What must hold:

* every accepted supplement gets its own reply, and none is silently dropped
  when several arrive in one round;
* a sourced judgment is bound to a supplement only when its citations were
  really read for a question that supplement created;
* a judgment that cannot be attributed stays research-level;
* the terminal run closes every reply and never leaks one into the run's
  research source block.
"""

from __future__ import annotations

import json

from src.web.research.deep_planner import ModelDeepPlanner
from src.web.research.steering_replies import (
    LIFECYCLE_CLOSED,
    STAGE_ANALYSIS,
    STAGE_EVIDENCE,
    find_reply,
    reply_id_for_steering,
    research_reply_id,
)

from tests.test_deep_planner_production import (  # noqa: F401 - shared fixtures
    POLICY,
    ScriptedGateway,
    _production_service,
    _result,
)


def _understanding(steering_id: str, focus: str) -> dict:
    return {
        "steering_id": steering_id,
        "changed_focus": focus,
        "reason_to_check": "自动化能力取决于接口与批量处理，需要重新核对",
        "questions_to_verify": ["脚本接口支持哪些批量操作"],
    }


def _citation(payload: dict, question_contains: str) -> dict | None:
    for source in payload.get("sources") or []:
        if question_contains in str(source.get("question") or ""):
            return {"source_id": source["source_id"], "quote": str(source["excerpt"])[:40]}
    return None


def test_supplements_get_replies_and_attributed_judgment_stays_honest(tmp_path, monkeypatch):
    monkeypatch.setenv("WEB_RESEARCH_STEERING_BUDGET_POLICY", json.dumps(POLICY))
    gateway = ScriptedGateway({"photoshop": [_result("https://example.org/automation", "自动化接口")]})
    service, _ = _production_service(tmp_path, monkeypatch, gateway)
    assert isinstance(service.planner, ModelDeepPlanner)

    revise_payloads: list[dict] = []

    def completion(instruction: str, payload: dict) -> str:
        if "sub_questions" in instruction:
            return json.dumps({"sub_questions": ["photoshop 自动化接口"]})
        revise_payloads.append(payload)
        supplied = [entry["id"] for entry in payload.get("steering") or []]
        if len(revise_payloads) == 1:
            return json.dumps({
                "done": False,
                "additional": [],
                "compute": None,
                # One understanding per supplied supplement: none may be dropped.
                "steering_understandings": [
                    _understanding(entry_id, f"评估重点变化 {index}")
                    for index, entry_id in enumerate(supplied)
                ],
                # Read before the supplements entered the plan: related material,
                # never their finding.
                "interim_analysis": {"text": "根据已读材料，初步看接口可自动化处理。",
                                     "citations": [c for c in [_citation(payload, "")] if c]},
            })
        citation = _citation(payload, "新增研究目标")
        return json.dumps({
            "done": True,
            "additional": [],
            "compute": None,
            "steering_understandings": [],
            "interim_analysis": (
                {"text": "根据补充后读取的材料，初步看批量处理可行。", "citations": [citation]}
                if citation else None
            ),
        })

    service.planner._completion = completion
    run = service.create(
        "比较 Photoshop 和开源替代品，重点考虑自动化编辑",
        owner_thread_id="thread-1",
        owner_turn_id="turn-1",
        research_mode="deep",
    )

    supplements = [
        "再考虑 Agent 自动编辑",
        "并补查接口与图层控制",
        "并补查批量导出流程",
        "并补查结果验证方式",
    ]
    original_search = gateway.search
    injected = False

    def search(query, *, max_items=10):
        nonlocal injected
        if not injected:
            injected = True
            for index, content in enumerate(supplements):
                service.steer(run.id, content=content, request_id=f"req-{index}")
        return original_search(query, max_items=max_items)

    gateway.search = search
    completed = service.execute(run.id)
    context = completed.research_context
    replies = context.get("steering_replies") or []

    # Every accepted supplement has its own reply; nothing is silently dropped.
    assert len(context["deep"]["steering"]) == 4
    assert len([item for item in replies if item["scope"] == "steering"]) == 4
    assert all(item["lifecycle"] == LIFECYCLE_CLOSED for item in replies)
    analyzed = [item for item in replies if item.get("analysis_state") == "ready"]
    assert len(analyzed) >= 4, [item.get("reply_id") for item in replies]

    # A judgment whose citations came from before the supplement is research-level,
    # never attached to the newest supplement.
    research_reply = find_reply(replies, research_reply_id(run.id))
    assert research_reply is not None
    assert research_reply["stage"] == STAGE_EVIDENCE
    assert research_reply["scope"] == "research"

    # The supplement-scoped judgment only exists when the material was read for a
    # question that supplement created.
    scoped = [
        item for item in replies
        if item["scope"] == "steering" and item["stage"] == STAGE_EVIDENCE
    ]
    for item in scoped:
        assert item["citations"]
        assert any(
            "新增研究目标" in str(citation.get("question") or "")
            for citation in item["citations"]
        )
        assert item["content_version"] > 1

    # No reply text leaks into the research source block that feeds the answer.
    for item in replies:
        assert str(item.get("text") or "") not in (completed.source_block or "")


def test_one_supplement_without_model_understanding_stays_visible(tmp_path, monkeypatch):
    monkeypatch.setenv("WEB_RESEARCH_STEERING_BUDGET_POLICY", json.dumps(POLICY))
    gateway = ScriptedGateway({"photoshop": [_result("https://example.org/automation", "自动化接口")]})
    service, _ = _production_service(tmp_path, monkeypatch, gateway)

    def completion(instruction: str, payload: dict) -> str:
        if "sub_questions" in instruction:
            return json.dumps({"sub_questions": ["photoshop 自动化接口"]})
        # The model never explains the supplement.
        return json.dumps({"done": True, "additional": [], "compute": None,
                           "steering_understandings": [], "interim_analysis": None})

    service.planner._completion = completion
    run = service.create(
        "比较 Photoshop 和开源替代品，重点考虑自动化编辑",
        owner_thread_id="thread-1", owner_turn_id="turn-1", research_mode="deep",
    )
    original_search = gateway.search
    injected = False

    def search(query, *, max_items=10):
        nonlocal injected
        if not injected:
            injected = True
            service.steer(run.id, content="再考虑 Agent 自动编辑", request_id="req-1")
        return original_search(query, max_items=max_items)

    gateway.search = search
    completed = service.execute(run.id)
    replies = completed.research_context["steering_replies"]
    entry_id = completed.research_context["deep"]["steering"][0]["id"]
    reply = find_reply(replies, reply_id_for_steering(run.id, entry_id))
    # Not covered is reported, never hidden.
    assert reply is not None
    assert reply["analysis_state"] == "not_generated"
    assert "未生成模型分析" in reply["text"]
    assert reply["stage"] != STAGE_ANALYSIS
