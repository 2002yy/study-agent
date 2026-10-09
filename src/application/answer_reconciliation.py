"""Bounded single-call answer reconciliation for determinable tool FAILs.

The program owns the numeric field: when the calculator proves a claimed value
wrong it supplies the exact value, the model may rewrite only the affected
explanation, and the program fills the authoritative number back. Only
*determinable* FAILs (a FAIL row with an exact value) admit repair; UNKNOWN and
unverified-formula PASS never do, and there is exactly one bounded attempt.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, localcontext
from fractions import Fraction
import json
from typing import Any, Mapping

REPAIR_INSTRUCTION = (
    "A deterministic calculator found that some numeric results in the current answer are wrong. "
    "For each affected item below, rewrite ONLY the parts of the answer that depend on it so that they "
    "agree with tool_exact_value (use that exact value). Do not change any other statement, citation, "
    "source identity, unit or number. Do not add new claims. Keep the answer otherwise identical. "
    'Return JSON only, exactly {"answer": "<full revised answer>"}.'
)


@dataclass(frozen=True)
class RepairAdmission:
    admitted: bool
    reason: str
    affected: tuple[dict[str, Any], ...] = ()


def exact_decimal(fraction_value: str) -> str:
    """Canonical decimal text of an exact Fraction string (e.g. '325/16' -> '20.3125')."""
    value = Fraction(str(fraction_value))
    with localcontext() as context:
        context.prec = 60
        decimal = Decimal(value.numerator) / Decimal(value.denominator)
    return format(decimal.normalize(), "f")


def _row_expression(kind: str, row: Mapping[str, Any]) -> str:
    if kind == "boundaries":
        left, right = row.get("left"), row.get("right")
        if left and right:
            return f"{left} = {right}"
        return str(row.get("label") or "")
    return str(row.get("expression") or "")


def admit_repair(report: Mapping[str, Any] | None) -> RepairAdmission:
    """Open repair only for FAIL rows that carry an exact, computable value."""
    if not isinstance(report, Mapping):
        return RepairAdmission(False, "no_report")
    affected: list[dict[str, Any]] = []
    for kind in ("calculations", "boundaries"):
        for row in report.get(kind) or ():
            if row.get("status") == "FAIL" and str(row.get("exact_value") or "").strip():
                affected.append(
                    {
                        "kind": kind[:-1],
                        "label": str(row.get("label") or ""),
                        "expression": _row_expression(kind, row),
                        "claimed_value": str(row.get("claimed_value") or ""),
                        "tool_exact_value": exact_decimal(row["exact_value"]),
                    }
                )
    if not affected:
        return RepairAdmission(False, "no_determinable_fail")
    return RepairAdmission(True, "determinable_fail", tuple(affected))


def repair_messages(original_answer: str, affected: tuple[dict[str, Any], ...]) -> list[dict[str, str]]:
    context = {
        "affected": list(affected),
        "current_answer": original_answer[:4000],
        "instruction": REPAIR_INSTRUCTION,
    }
    return [
        {"role": "system", "content": REPAIR_INSTRUCTION},
        {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
    ]


def parse_repair(raw: Any) -> str | None:
    """Accept only exactly {'answer': str}; anything else is no repair."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return None
    if (
        isinstance(raw, Mapping)
        and set(raw) == {"answer"}
        and isinstance(raw.get("answer"), str)
        and raw["answer"].strip()
    ):
        return raw["answer"]
    return None


def apply_numeric_authority(
    output: Mapping[str, Any], report: Mapping[str, Any] | None
) -> tuple[dict[str, Any], tuple[dict[str, str], ...]]:
    """Program-owned numeric authority: overwrite FAILed results with exact values."""
    merged = json.loads(json.dumps(dict(output)))
    filled: list[dict[str, str]] = []
    if not isinstance(report, Mapping):
        return merged, ()
    for kind in ("calculations", "boundaries"):
        rows = list(merged.get(kind) or ())
        report_rows = list(report.get(kind) or ())
        for index, row in enumerate(rows):
            if not isinstance(row, dict) or index >= len(report_rows):
                continue
            source = report_rows[index]
            if source.get("status") == "FAIL" and str(source.get("exact_value") or "").strip():
                value = exact_decimal(source["exact_value"])
                row["result"] = value
                filled_item = {"kind": kind[:-1], "label": str(row.get("label") or ""), "value": value}
                if kind == "boundaries":
                    # The program owns numeric authority: stale probes around the
                    # old, wrong root must be re-straddled so bracketing holds.
                    root = Fraction(str(source["exact_value"]))
                    row["below"] = exact_decimal(str(root - 1))
                    row["above"] = exact_decimal(str(root + 1))
                    filled_item["probe_adjusted"] = "true"
                filled.append(filled_item)
    return merged, tuple(filled)


def answer_mentions_values(answer: str, filled: tuple[dict[str, str], ...]) -> bool:
    """Second check: the revised answer must contain every authoritative value."""
    if not filled:
        return True
    text = answer or ""
    return all(item["value"] in text for item in filled)
