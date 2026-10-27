"""QP-1B contracts for the model planning instruction.

These lock the three things the instruction change is meant to guarantee, without
calling a model: entity anchoring, task focus, and a conditional official-domain
query. The schema, decision parsing, RQ binding and the semantic call budget are
deliberately untouched, and are asserted here so a later edit cannot widen them.
"""

from __future__ import annotations

import json
import time

import pytest

from src.web.semantic_recovery import (
    _TURN_INSTRUCTION,
    ResearchEpisode,
    ResearchSemanticSession,
)

RQS = [
    {"id": "rq-mechanic", "question": "虚构叙事当期增益是什么"},
    {"id": "rq-compare", "question": "黄泉队与流萤队自动战斗对比"},
]


def _episode() -> ResearchEpisode:
    return ResearchEpisode(
        "task-qp",
        "thread-qp",
        "《星铁》虚构叙事中，黄泉队、流萤队、Archer 队哪个更适合自动战斗？",
        RQS,
    )


def _decision() -> dict:
    return {
        "task_id": "task-qp",
        "intent": "NEW_RESEARCH",
        "subject": "崩坏：星穹铁道 虚构叙事 自动战斗配队",
        "constraints_delta": {},
        "unresolved_questions": RQS,
        "suggested_next_action": "compare the three teams for auto-battle",
        "proposed_queries": [
            {"rq_id": "rq-mechanic", "query": "崩坏星穹铁道 虚构叙事 当期增益"},
            {"rq_id": "rq-compare", "query": "黄泉队 流萤队 Archer 自动战斗 配队"},
        ],
    }


def test_instruction_requires_entity_anchors_and_task_focus() -> None:
    assert "entity anchors" in _TURN_INSTRUCTION
    for anchor in ("work", "character", "model", "product", "version"):
        assert anchor in _TURN_INSTRUCTION
    for focus in ("build", "comparison", "auto-battle", "release notes"):
        assert focus in _TURN_INSTRUCTION
    assert "a query that drops them" in _TURN_INSTRUCTION


def test_instruction_makes_the_official_domain_query_conditional() -> None:
    assert "site:OFFICIAL_DOMAIN only when" in _TURN_INSTRUCTION
    assert "owned by that publisher" in _TURN_INSTRUCTION
    assert "community and " in _TURN_INSTRUCTION
    # The unconditional requirement is what steered community questions to
    # official sites that cannot answer them.
    assert "include one site:OFFICIAL_DOMAIN query" not in _TURN_INSTRUCTION


def test_instruction_keeps_the_existing_query_budget() -> None:
    assert "Plan 2 or 3 short queries" in _TURN_INSTRUCTION
    assert "2-8 meaningful terms" in _TURN_INSTRUCTION


def test_interpret_sends_the_new_instruction_and_keeps_the_schema(monkeypatch) -> None:
    captured: dict[str, str] = {}

    def completion(*, messages, timeout, task_name):
        captured[task_name] = messages[0]["content"]
        return json.dumps(_decision(), ensure_ascii=False)

    session = ResearchSemanticSession(
        completion,
        deadline=time.monotonic() + 5,
        should_cancel=lambda: False,
    )

    decision = session.interpret(_episode(), "哪个更适合自动战斗？")

    assert decision.proposed_queries
    system = captured["research_turn_interpretation"]
    assert "entity anchors" in system
    assert "site:OFFICIAL_DOMAIN only when" in system
    assert "include one site:OFFICIAL_DOMAIN query" not in system
    # The output contract is unchanged: same fields, still parsed the same way.
    assert '"proposed_queries"' in system
    assert '"unresolved_questions"' in system
    assert '"constraints_delta"' in system


def test_semantic_call_budget_is_unchanged(monkeypatch) -> None:
    def completion(*, messages, timeout, task_name):
        return json.dumps(_decision(), ensure_ascii=False)

    session = ResearchSemanticSession(
        completion,
        deadline=time.monotonic() + 5,
        should_cancel=lambda: False,
    )
    session.request("stage_a", "instruction", {})
    session.request("stage_b", "instruction", {})
    session.request("stage_c", "instruction", {})

    with pytest.raises(ValueError, match="semantic_call_limit"):
        session.request("stage_d", "instruction", {})
