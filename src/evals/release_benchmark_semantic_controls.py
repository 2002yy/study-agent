"""One definition of "what a specific semantic judgment looks like".

§161 (DeepSeek probe calibration) and §162 (independent reviewer qualification)
must not each own a private copy of the control semantics, or the two gates
would silently drift apart. This module is the single computation core: the
frozen control expectations plus the per-control evaluation. Each consumer adds
only its own provenance / authority layer on top.

Nothing here grants authority, reads artifacts, or calls a model.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

AXES: tuple[str, str, str] = (
    "question_coverage",
    "evidence_grounding",
    "citation_support",
)
CLEAN_AXES: tuple[str, str, str] = ("covered", "supported", "supported")

# Which axis each single-point control is supposed to move.
TARGET_AXIS: Mapping[str, str] = {
    "wrong_citation": "citation_support",
    "missing_aspect": "question_coverage",
    "unsupported_claim": "evidence_grounding",
}


@dataclass(frozen=True)
class ControlExpectation:
    """The frozen expectation for one single-point negative control."""

    variant: str
    expected_axes: tuple[str, str, str]
    required_issue: str
    allowed_issues: frozenset[str]


CONTROL_EXPECTATIONS: Mapping[str, ControlExpectation] = {
    "wrong_citation": ControlExpectation(
        variant="wrong_citation",
        expected_axes=("covered", "supported", "gap"),
        required_issue="wrong_citation",
        allowed_issues=frozenset({"wrong_citation"}),
    ),
    "missing_aspect": ControlExpectation(
        variant="missing_aspect",
        expected_axes=("partial", "supported", "supported"),
        required_issue="coverage_gap",
        allowed_issues=frozenset({"coverage_gap"}),
    ),
    "unsupported_claim": ControlExpectation(
        variant="unsupported_claim",
        expected_axes=("covered", "gap", "gap"),
        required_issue="unsupported_claim",
        allowed_issues=frozenset({"unsupported_claim", "wrong_citation"}),
    ),
}


def control_expectation(variant: str) -> ControlExpectation:
    try:
        return CONTROL_EXPECTATIONS[variant]
    except KeyError as exc:
        raise ValueError(f"unknown semantic control variant: {variant!r}") from exc


def observed_axes(judgment: Mapping[str, Any]) -> tuple[str, str, str]:
    return (str(judgment[AXES[0]]), str(judgment[AXES[1]]), str(judgment[AXES[2]]))


def issue_counts(judgment: Mapping[str, Any]) -> Counter[str]:
    return Counter(issue["issue_type"] for issue in judgment["issues"])


@dataclass(frozen=True)
class ControlVerdict:
    """Per-control facts. Neither flag is a permission."""

    variant: str
    target_detected: bool
    specific: bool
    expected_axes: Mapping[str, str]
    observed_axes: Mapping[str, str]
    issue_types: Mapping[str, int]

    def to_dict(self) -> dict[str, object]:
        return {
            "variant": self.variant,
            "target_detected": self.target_detected,
            "specific": self.specific,
            "expected_axes": dict(self.expected_axes),
            "observed_axes": dict(self.observed_axes),
            "issue_types": dict(self.issue_types),
        }


def evaluate_control(
    variant: str,
    *,
    dimension_consistent: bool,
    judgment: Mapping[str, Any],
) -> ControlVerdict:
    """Score one control on the two independent axes: detection and specificity."""
    expectation = control_expectation(variant)
    counts = issue_counts(judgment)
    observed = observed_axes(judgment)
    target_index = AXES.index(TARGET_AXIS[variant])
    target_detected = (
        dimension_consistent is True
        and observed[target_index] == expectation.expected_axes[target_index]
        and counts[expectation.required_issue] >= 1
    )
    specific = (
        target_detected
        and observed == expectation.expected_axes
        and counts[expectation.required_issue] == 1
        and set(counts) <= expectation.allowed_issues
        and all(count == 1 for count in counts.values())
    )
    return ControlVerdict(
        variant=variant,
        target_detected=target_detected,
        specific=specific,
        expected_axes=dict(zip(AXES, expectation.expected_axes, strict=True)),
        observed_axes=dict(zip(AXES, observed, strict=True)),
        issue_types=dict(sorted(counts.items())),
    )


def evaluate_clean_answer(
    *,
    dimension_consistent: bool,
    judgment: Mapping[str, Any],
) -> bool:
    """A real, uncorrupted answer must come back clean and issue-free."""
    return (
        dimension_consistent is True
        and observed_axes(judgment) == CLEAN_AXES
        and judgment["issues"] == []
    )


@dataclass(frozen=True)
class ConfusionCounts:
    """Two independent confusion pairs over the same control set.

    ``true_positive`` / ``false_negative`` describe target detection.
    ``true_negative`` / ``false_positive`` describe specificity: a control that
    is not judged exactly right counts as a false positive even if its target
    was also missed, because the two gates are measured separately and must not
    be averaged into one score.
    """

    true_positive: int
    false_negative: int
    true_negative: int
    false_positive: int

    @property
    def target_total(self) -> int:
        return self.true_positive + self.false_negative

    @property
    def specificity_total(self) -> int:
        return self.true_negative + self.false_positive

    def to_dict(self) -> dict[str, int]:
        return {
            "true_positive": self.true_positive,
            "false_negative": self.false_negative,
            "true_negative": self.true_negative,
            "false_positive": self.false_positive,
        }


def confusion_from(verdicts: Sequence[ControlVerdict]) -> ConfusionCounts:
    return ConfusionCounts(
        true_positive=sum(1 for row in verdicts if row.target_detected),
        false_negative=sum(1 for row in verdicts if not row.target_detected),
        true_negative=sum(1 for row in verdicts if row.specific),
        false_positive=sum(1 for row in verdicts if not row.specific),
    )


def target_gate_passes(confusion: ConfusionCounts) -> bool:
    return confusion.target_total > 0 and confusion.false_negative == 0


def specificity_gate_passes(confusion: ConfusionCounts) -> bool:
    return confusion.specificity_total > 0 and confusion.false_positive == 0
