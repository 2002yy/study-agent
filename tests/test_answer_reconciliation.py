"""Slice 1c: bounded reconciliation admission, numeric authority and second check."""

from __future__ import annotations

from src.application.answer_reconciliation import (
    admit_repair,
    answer_mentions_values,
    apply_numeric_authority,
    exact_decimal,
    parse_repair,
    repair_messages,
)


def _report(**overrides):
    base = {
        "calculations": [],
        "boundaries": [
            {
                "label": "threshold",
                "status": "FAIL",
                "reason": "boundary_mismatch",
                "exact_value": "325/16",
                "claimed_value": "17.1875",
            }
        ],
    }
    base.update(overrides)
    return base


def test_exact_decimal_converts_fractions() -> None:
    assert exact_decimal("325/16") == "20.3125"
    assert exact_decimal("154/5") == "30.8"
    assert exact_decimal("47") == "47"


def test_admit_only_determinable_fail() -> None:
    admission = admit_repair(_report())
    assert admission.admitted and admission.affected[0]["tool_exact_value"] == "20.3125"
    assert admit_repair({"calculations": [], "boundaries": []}).admitted is False
    assert admit_repair({"boundaries": [{"status": "UNKNOWN", "exact_value": "1/2"}]}).admitted is False
    assert admit_repair({"boundaries": [{"status": "FAIL", "exact_value": ""}]}).admitted is False
    assert admit_repair(None).reason == "no_report"


def test_apply_numeric_authority_overwrites_only_fail() -> None:
    output = {
        "calculations": [{"label": "c", "expression": "20+0.9*x", "result": "30.8"}],
        "boundaries": [{"label": "threshold", "left": "20+0.90*x", "right": "2.50*(x-5)", "result": "17.1875"}],
        "answer": "text",
    }
    report = {
        "calculations": [{"status": "PASS", "exact_value": "154/5"}],
        "boundaries": [{"status": "FAIL", "exact_value": "325/16"}],
    }
    merged, filled = apply_numeric_authority(output, report)
    assert merged["calculations"][0]["result"] == "30.8"  # PASS untouched
    assert merged["boundaries"][0]["result"] == "20.3125"  # FAIL overwritten
    assert merged["answer"] == "text"
    assert filled[0]["value"] == "20.3125"


def test_parse_repair_is_strict() -> None:
    assert parse_repair('{"answer": "fixed"}') == "fixed"
    assert parse_repair({"answer": "fixed"}) == "fixed"
    assert parse_repair({"answer": "fixed", "extra": 1}) is None
    assert parse_repair({"answer": ""}) is None
    assert parse_repair("not json") is None


def test_answer_mentions_values() -> None:
    filled = ({"kind": "boundary", "label": "t", "value": "20.3125"},)
    assert answer_mentions_values("the threshold is 20.3125 million", filled)
    assert not answer_mentions_values("the threshold is 17.1875 million", filled)
    assert answer_mentions_values("anything", ())


def test_repair_messages_carry_tool_value() -> None:
    admission = admit_repair(_report())
    messages = repair_messages("old", admission.affected)
    assert messages[0]["role"] == "system"
    assert "20.3125" in messages[1]["content"]
