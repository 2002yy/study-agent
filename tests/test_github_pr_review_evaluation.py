from __future__ import annotations

import json
from pathlib import Path

from src.web.github_pr_review_evaluation import evaluate_pr_review_context

_FIXTURE = Path(__file__).parent / "fixtures" / "github_replay" / "manifest.json"


def _cases() -> list[dict]:
    payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    return [
        {
            "case_id": case["case_id"],
            "repository": case["repository"],
            "pull_request": case["pull_request"],
            "review_symbol_ids": case["labels"]["review_symbol_ids"],
            "ci_test_paths": case["labels"]["ci_test_paths"],
        }
        for case in payload["cases"]
    ]


def test_review_context_metrics_report_exact_precision_and_recall():
    expected = _cases()[0]
    context = {
        "review_items": [
            {
                "mapping": {
                    "status": "mapped",
                    "symbol": {
                        "identity": {"id": "symbol-resolve-turn-task-contract"},
                        "qualified_name": "resolve_turn_task_contract",
                    },
                }
            },
            {
                "mapping": {
                    "status": "ambiguous",
                    "candidates": [
                        {"qualified_name": "classify_task_contract"},
                    ],
                }
            },
        ],
        "ci_associations": [
            {
                "association": {
                    "status": "associated",
                    "tests": [
                        "tests/test_task_contract.py",
                        "tests/test_external_data_policy.py",
                    ],
                }
            }
        ],
    }

    metrics = evaluate_pr_review_context(context, expected)

    assert metrics["review_symbol_mapping"]["precision"] == 1.0
    assert metrics["review_symbol_mapping"]["recall"] == 1.0
    assert metrics["failed_ci_test_association"]["precision"] == 1.0
    assert metrics["failed_ci_test_association"]["recall"] == 1.0
    assert metrics["macro"] == {"precision": 1.0, "recall": 1.0, "f1": 1.0}


def test_review_context_metrics_penalize_false_positive_and_missing_test():
    expected = _cases()[0]
    context = {
        "review_items": [
            {
                "mapping": {
                    "status": "mapped",
                    "symbol": {
                        "identity": {"id": "symbol-resolve-turn-task-contract"},
                    },
                }
            },
            {
                "mapping": {
                    "status": "mapped",
                    "symbol": {"identity": {"id": "symbol-false-positive"}},
                }
            },
        ],
        "ci_associations": [
            {
                "association": {
                    "status": "associated",
                    "tests": ["tests/test_task_contract.py"],
                }
            }
        ],
    }

    metrics = evaluate_pr_review_context(context, expected)

    assert metrics["review_symbol_mapping"]["precision"] == 0.5
    assert metrics["review_symbol_mapping"]["recall"] == 1.0
    assert metrics["failed_ci_test_association"]["precision"] == 1.0
    assert metrics["failed_ci_test_association"]["recall"] == 0.5
    assert metrics["macro"]["precision"] == 0.75
    assert metrics["macro"]["recall"] == 0.75


def test_empty_expected_review_set_does_not_reward_fabricated_mapping():
    expected = _cases()[1]
    clean = evaluate_pr_review_context(
        {
            "review_items": [],
            "ci_associations": [
                {
                    "association": {
                        "tests": ["tests/test_github_change_impact.py"],
                    }
                }
            ],
        },
        expected,
    )
    fabricated = evaluate_pr_review_context(
        {
            "review_items": [
                {
                    "mapping": {
                        "status": "mapped",
                        "symbol": {"identity": {"id": "fabricated-symbol"}},
                    }
                }
            ],
            "ci_associations": [
                {
                    "association": {
                        "tests": ["tests/test_github_change_impact.py"],
                    }
                }
            ],
        },
        expected,
    )

    assert clean["review_symbol_mapping"]["precision"] == 1.0
    assert fabricated["review_symbol_mapping"]["precision"] == 0.0
    assert fabricated["review_symbol_mapping"]["false_positive"] == 1
