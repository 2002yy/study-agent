"""Deterministic quality metrics for repository structure analysis."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class ResolutionGoldenCase:
    query: str
    expected_status: str
    expected_path: str = ""
    expected_qualified_name: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ImpactGoldenCase:
    query: str
    expected_files: tuple[str, ...] = ()
    expected_tests: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "expected_files": list(self.expected_files),
            "expected_tests": list(self.expected_tests),
        }


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def evaluate_structure_quality(
    index: Any,
    *,
    resolution_cases: Iterable[ResolutionGoldenCase] = (),
    impact_cases: Iterable[ImpactGoldenCase] = (),
) -> dict[str, Any]:
    resolution_rows: list[dict[str, Any]] = []
    resolved_total = 0
    resolved_correct = 0
    ambiguous_total = 0
    ambiguous_correct = 0
    unresolved_total = 0
    unresolved_correct = 0

    for case in resolution_cases:
        result = index.inspect(case.query, top_k=20)
        resolution = dict(result.get("resolution") or {})
        actual_status = str(resolution.get("status") or "unresolved")
        selected = resolution.get("selected")
        selected = selected if isinstance(selected, dict) else {}
        evidence = selected.get("evidence")
        evidence = evidence if isinstance(evidence, dict) else {}
        actual_path = str(evidence.get("path") or "")
        actual_qualified = str(selected.get("qualified_name") or selected.get("name") or "")
        correct = actual_status == case.expected_status
        if case.expected_status == "resolved":
            resolved_total += 1
            if case.expected_path:
                correct = correct and actual_path == case.expected_path
            if case.expected_qualified_name:
                correct = correct and actual_qualified == case.expected_qualified_name
            resolved_correct += int(correct)
        elif case.expected_status == "ambiguous":
            ambiguous_total += 1
            ambiguous_correct += int(correct)
        elif case.expected_status == "unresolved":
            unresolved_total += 1
            unresolved_correct += int(correct)
        resolution_rows.append(
            {
                "query": case.query,
                "expected_status": case.expected_status,
                "actual_status": actual_status,
                "expected_path": case.expected_path,
                "actual_path": actual_path,
                "expected_qualified_name": case.expected_qualified_name,
                "actual_qualified_name": actual_qualified,
                "correct": correct,
            }
        )

    impact_rows: list[dict[str, Any]] = []
    expected_file_total = 0
    matched_file_total = 0
    expected_test_total = 0
    matched_test_total = 0
    for case in impact_cases:
        result = index.impact(case.query, depth=3, max_files=100, max_edges=500)
        actual_files = {
            str(item.get("path") or "")
            for item in result.get("files", [])
            if isinstance(item, dict)
        }
        actual_tests = {
            str(item.get("path") or "")
            for item in result.get("tests", [])
            if isinstance(item, dict)
        }
        expected_files = set(case.expected_files)
        expected_tests = set(case.expected_tests)
        expected_file_total += len(expected_files)
        matched_file_total += len(expected_files & actual_files)
        expected_test_total += len(expected_tests)
        matched_test_total += len(expected_tests & actual_tests)
        impact_rows.append(
            {
                "query": case.query,
                "expected_files": sorted(expected_files),
                "actual_files": sorted(actual_files),
                "expected_tests": sorted(expected_tests),
                "actual_tests": sorted(actual_tests),
                "file_recall": _ratio(len(expected_files & actual_files), len(expected_files)),
                "test_recall": _ratio(len(expected_tests & actual_tests), len(expected_tests)),
            }
        )

    total_resolution = resolved_total + ambiguous_total + unresolved_total
    total_correct = resolved_correct + ambiguous_correct + unresolved_correct
    return {
        "resolution_case_count": total_resolution,
        "impact_case_count": len(impact_rows),
        "resolved_accuracy": _ratio(resolved_correct, resolved_total),
        "ambiguous_recall": _ratio(ambiguous_correct, ambiguous_total),
        "unresolved_recall": _ratio(unresolved_correct, unresolved_total),
        "overall_resolution_accuracy": _ratio(total_correct, total_resolution),
        "impact_file_recall": _ratio(matched_file_total, expected_file_total),
        "test_mapping_recall": _ratio(matched_test_total, expected_test_total),
        "resolution_rows": resolution_rows,
        "impact_rows": impact_rows,
    }
