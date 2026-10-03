from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from src.web.research.claim_planner import (
    RUNTIME_CLAIM_PLAN_SCHEMA_VERSION,
    _parse_claim_plan,
)
from tools.rq1c_qualification_guardrails import _planner_observability


def _claim(anchor: str, *, kind: str = "factual", profile: str = "current_fact") -> dict:
    return {
        "question_anchor": anchor,
        "kind": kind,
        "policy_profile": profile,
    }


def _plan(critical: dict, supporting: list[dict]) -> dict:
    return {
        "schema_version": RUNTIME_CLAIM_PLAN_SCHEMA_VERSION,
        "critical_claim": critical,
        "supporting_claims": supporting,
    }


def test_planner_observability_projects_only_safe_attempt_metadata() -> None:
    run = SimpleNamespace(
        research_context={
            "claim_engine_runtime": {
                "model_calls": [
                    {
                        "purpose": "research_claim_planning",
                        "attempt": 1,
                        "status": "attempt_failed",
                        "error_type": "ValueError",
                        "finish_reason": "stop",
                        "input_tokens": 512,
                        "output_tokens": 93,
                        "total_tokens": 605,
                        "elapsed_seconds": 4.125,
                        "response_text": "must never escape",
                        "prompt": "must never escape",
                    },
                    {
                        "purpose": "candidate_assessment",
                        "attempt": 1,
                        "status": "completed",
                    },
                ]
            }
        }
    )

    projection = _planner_observability(run)

    assert projection == {
        "attempt_count": 1,
        "attempts": [
            {
                "attempt": 1,
                "status": "attempt_failed",
                "error_type": "ValueError",
                "finish_reason": "stop",
                "input_tokens": 512,
                "output_tokens": 93,
                "total_tokens": 605,
                "elapsed_seconds": 4.125,
            }
        ],
        "stores_raw_model_text": False,
    }
    encoded = json.dumps(projection)
    assert "must never escape" not in encoded
    assert "response_text" not in encoded
    assert "prompt" not in encoded


def test_planner_observability_handles_missing_runtime() -> None:
    assert _planner_observability(None) == {
        "attempt_count": 0,
        "attempts": [],
        "stores_raw_model_text": False,
    }


def test_duplicate_optional_supporting_anchor_is_discarded() -> None:
    question = "What is the current Bank Rate?"
    raw = _plan(
        _claim(question, profile="quantitative_claim"),
        [_claim(question, profile="quantitative_claim")],
    )

    proposals = _parse_claim_plan(raw, question=question)

    assert len(proposals) == 1
    assert proposals[0].priority == "critical"
    assert proposals[0].surface == question


def test_nonverbatim_optional_supporting_anchor_is_discarded() -> None:
    question = "Which PostgreSQL releases are currently supported?"
    raw = _plan(
        _claim(question),
        [_claim("PostgreSQL end-of-life policy")],
    )

    proposals = _parse_claim_plan(raw, question=question)

    assert len(proposals) == 1
    assert proposals[0].surface == question


def test_critical_anchor_remains_fail_closed() -> None:
    question = "Which PostgreSQL releases are currently supported?"
    raw = _plan(_claim("PostgreSQL support table"), [])

    with pytest.raises(ValueError, match="copied from user question"):
        _parse_claim_plan(raw, question=question)


def test_distinct_valid_supporting_claim_is_retained() -> None:
    question = "Compare Python 3.13 and Python 3.14 support."
    raw = _plan(
        _claim("Python 3.13"),
        [_claim("Python 3.14")],
    )

    proposals = _parse_claim_plan(raw, question=question)

    assert [proposal.surface for proposal in proposals] == ["Python 3.13", "Python 3.14"]
    assert [proposal.priority for proposal in proposals] == ["critical", "major"]


def test_valid_supporting_anchor_does_not_bypass_policy_validation() -> None:
    question = "Compare Python 3.13 and Python 3.14 support."
    raw = _plan(
        _claim("Python 3.13"),
        [_claim("Python 3.14", profile="causal_analysis")],
    )

    with pytest.raises(ValueError):
        _parse_claim_plan(raw, question=question)
