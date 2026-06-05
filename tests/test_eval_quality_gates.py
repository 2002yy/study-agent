from __future__ import annotations

from pathlib import Path

import pytest

from src.evals import (
    evaluate_answer_grounding_case,
    evaluate_memory_safety_case,
    evaluate_tool_routing_case,
    evaluate_url_safety_case,
    evaluate_workflow_event_case,
    load_eval_cases,
)


FIXTURE_DIR = Path("tests/fixtures/evals")


@pytest.mark.parametrize("case", load_eval_cases(FIXTURE_DIR / "answer_grounding.json"))
def test_answer_grounding_eval_cases_pass(case):
    result = evaluate_answer_grounding_case(case)

    assert result.passed, result.failures


@pytest.mark.parametrize("case", load_eval_cases(FIXTURE_DIR / "tool_routing.json"))
def test_tool_routing_eval_cases_pass(case):
    result = evaluate_tool_routing_case(case)

    assert result.passed, result.failures


@pytest.mark.parametrize("case", load_eval_cases(FIXTURE_DIR / "workflow_events.json"))
def test_workflow_event_eval_cases_pass(case):
    result = evaluate_workflow_event_case(case)

    assert result.passed, result.failures


@pytest.mark.parametrize("case", load_eval_cases(FIXTURE_DIR / "memory_safety.json"))
def test_memory_safety_eval_cases_pass(case):
    result = evaluate_memory_safety_case(case)

    assert result.passed, result.failures


@pytest.mark.parametrize("case", load_eval_cases(FIXTURE_DIR / "url_safety.json"))
def test_url_safety_eval_cases_pass(case):
    result = evaluate_url_safety_case(case)

    assert result.passed, result.failures


def test_answer_grounding_eval_reports_missing_citation():
    result = evaluate_answer_grounding_case(
        {
            "id": "missing_citation",
            "answer": "requests Session can reuse connections.",
            "required_citations": ["[1]"],
        }
    )

    assert result.passed is False
    assert result.failures == ("missing citation: [1]",)


def test_workflow_event_eval_rejects_invalid_transition():
    result = evaluate_workflow_event_case(
        {
            "id": "invalid_transition",
            "events": [
                {
                    "step_id": "llm",
                    "event_type": "completed",
                    "status": "succeeded",
                    "elapsed_ms": 1,
                }
            ],
        }
    )

    assert result.passed is False
    assert "invalid transition: pending -> succeeded" in result.failures
