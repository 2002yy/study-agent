"""Fixture-free checks for chat's read-backed publication boundary."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from src.application import chat_service
from src.application.chat_research_publication import (
    THINKING_DISABLED_EXTRA_BODY,
    _answer_attempt_budget,
    _answer_generation_extra_body,
    _question_excerpts,
    _research_intent,
    _route_generation_calls,
    answer_validation_active,
    inline_research_validation_plan,
)


def test_legacy_imports_still_point_to_extracted_policy_functions():
    assert chat_service._answer_attempt_budget is _answer_attempt_budget
    assert chat_service._question_excerpts is _question_excerpts
    assert chat_service.inline_research_validation_plan is inline_research_validation_plan


def test_blocked_generation_has_zero_hidden_reasoning_and_no_extra_attempt():
    prepared = SimpleNamespace(
        answer_validation={"allowed_attempts": 0, "evidence_rows": [{"id": "e"}]},
        rag={}, route={},
    )
    assert _answer_attempt_budget(prepared) == 0
    assert _answer_generation_extra_body(prepared) == THINKING_DISABLED_EXTRA_BODY


def test_pass_generation_preserves_default_policy_and_semantic_budget():
    prepared = SimpleNamespace(
        answer_validation={"allowed_attempts": 2, "evidence_rows": [{"id": "e"}]},
        rag={"web_tools": {"semantics": {"model_calls": 4}}},
        route={"answer_generation_calls": 1},
    )
    assert _answer_attempt_budget(prepared) == 1
    with patch.dict("os.environ", {"RESEARCH_ANSWER_BOUNDED_POLICY": "off"}):
        assert _answer_generation_extra_body(prepared) is None
    with patch.dict("os.environ", {"RESEARCH_ANSWER_BOUNDED_POLICY": "on"}):
        assert _answer_generation_extra_body(prepared) == THINKING_DISABLED_EXTRA_BODY


def test_page_excerpts_find_relevant_body_without_claiming_it_is_verified():
    body = "INTRODUCTION " * 40 + "The verified release date is 2026-11-17."
    spans = _question_excerpts(body, "verified release date")
    assert any("verified release date" in excerpt for excerpt in spans)
    assert len(spans) <= 3
    assert _research_intent({"task_contract": {"task_intent": "research"}})
    assert not _research_intent({"task_contract": {"task_intent": "chat"}})
    assert _route_generation_calls({"answer_generation_calls": "1200"}) == 1000
    assert _route_generation_calls({"answer_generation_calls": "broken"}) == 0


def test_user_denied_web_policy_bypasses_publication_gate():
    prepared = SimpleNamespace(
        route={"external_data_policy": {"web_allowed": False}},
        answer_validation={"evidence_rows": [{"id": "e"}]},
    )
    assert not answer_validation_active(prepared)
