"""Deterministic precision/recall metrics for PR review-context replay cases."""

from __future__ import annotations

from typing import Any, Iterable


def _strings(values: Iterable[Any]) -> set[str]:
    return {str(value).strip() for value in values if str(value).strip()}


def _metrics(predicted: set[str], expected: set[str]) -> dict[str, Any]:
    true_positive = len(predicted & expected)
    false_positive = len(predicted - expected)
    false_negative = len(expected - predicted)
    precision = true_positive / len(predicted) if predicted else (1.0 if not expected else 0.0)
    recall = true_positive / len(expected) if expected else 1.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall > 0
        else 0.0
    )
    return {
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "predicted": sorted(predicted),
        "expected": sorted(expected),
    }


def review_symbol_predictions(context: dict[str, Any]) -> set[str]:
    predictions: set[str] = set()
    for item in context.get("review_items", []):
        if not isinstance(item, dict):
            continue
        mapping = item.get("mapping") if isinstance(item.get("mapping"), dict) else {}
        if mapping.get("status") != "mapped":
            continue
        symbol = mapping.get("symbol") if isinstance(mapping.get("symbol"), dict) else {}
        identity = symbol.get("identity") if isinstance(symbol.get("identity"), dict) else {}
        value = str(identity.get("id") or symbol.get("qualified_name") or "").strip()
        if value:
            predictions.add(value)
    return predictions


def ci_test_predictions(context: dict[str, Any]) -> set[str]:
    predictions: set[str] = set()
    for item in context.get("ci_associations", []):
        if not isinstance(item, dict):
            continue
        association = (
            item.get("association")
            if isinstance(item.get("association"), dict)
            else {}
        )
        predictions.update(_strings(association.get("tests", [])))
    return predictions


def evaluate_pr_review_context(
    context: dict[str, Any],
    expected: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate one replay result without invoking providers or an LLM."""

    review_metrics = _metrics(
        review_symbol_predictions(context),
        _strings(expected.get("review_symbol_ids", [])),
    )
    ci_metrics = _metrics(
        ci_test_predictions(context),
        _strings(expected.get("ci_test_paths", [])),
    )
    macro_precision = round(
        (review_metrics["precision"] + ci_metrics["precision"]) / 2,
        4,
    )
    macro_recall = round(
        (review_metrics["recall"] + ci_metrics["recall"]) / 2,
        4,
    )
    macro_f1 = round((review_metrics["f1"] + ci_metrics["f1"]) / 2, 4)
    return {
        "case_id": str(expected.get("case_id") or ""),
        "repository": str(expected.get("repository") or ""),
        "pull_request": int(expected.get("pull_request") or 0),
        "review_symbol_mapping": review_metrics,
        "failed_ci_test_association": ci_metrics,
        "macro": {
            "precision": macro_precision,
            "recall": macro_recall,
            "f1": macro_f1,
        },
    }
