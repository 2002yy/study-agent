"""§144.17 Multimodal Reader v1 qualification (Q1-Q6)."""

from __future__ import annotations

import json

import pytest

from tools.run_multimodal_qualification import (
    DEFAULT_OUTPUT,
    READ_SITE_E2E_REFERENCE,
    SCHEMA_VERSION,
    run_qualification,
)

pytestmark = pytest.mark.skipif(
    not DEFAULT_OUTPUT.exists(), reason="multimodal qualification artifact is absent"
)


def _scenario(artifact: dict, scenario_id: str) -> dict:
    for item in artifact["scenarios"]:
        if item["id"] == scenario_id:
            return item
    raise AssertionError(f"missing scenario {scenario_id}")


def test_artifact_records_all_six_scenarios_and_passes() -> None:
    artifact = json.loads(DEFAULT_OUTPUT.read_text(encoding="utf-8"))

    assert artifact["schema_version"] == SCHEMA_VERSION
    assert artifact["verdict"] == "PASS"
    assert [item["id"] for item in artifact["scenarios"]] == [
        "Q1_default_inert",
        "Q2_enabled_declared",
        "Q3_semantic_value",
        "Q4_fail_closed",
        "Q5_provenance",
        "Q6_budget",
    ]
    assert artifact["read_site_e2e_reference"] == READ_SITE_E2E_REFERENCE


def test_q1_default_inert_does_nothing() -> None:
    scenario = _scenario(run_qualification(), "Q1_default_inert")

    assert scenario["verdict"] == "PASS"
    assert scenario["fetched"] is False
    assert scenario["vision_called"] is False
    assert scenario["units"] == 0
    assert scenario["vision_calls"] == 0


def test_q2_enabled_declared_produces_one_unit() -> None:
    scenario = _scenario(run_qualification(), "Q2_enabled_declared")

    assert scenario["verdict"] == "PASS"
    assert scenario["fetched"] is True
    assert scenario["vision_called"] is True
    assert scenario["units"] == 1
    assert scenario["vision_calls"] == 1


def test_q3_the_unit_changes_rq_a_and_flows_into_rq_c_and_rq_d() -> None:
    scenario = _scenario(run_qualification(), "Q3_semantic_value")

    before = scenario["rq_a_c_d_before"]
    after = scenario["rq_a_c_d_after"]
    conflict = scenario["rq_c_with_contradiction"]

    # "the call succeeded" is not the claim: adequacy must actually change.
    assert before["adequacy"] in {"insufficient", "partial"}
    assert after["adequacy"] == "adequate"
    assert after["claim_state"] == "satisfied"
    assert before["coverage_recommendation"] == "continue_candidate"
    assert after["coverage_recommendation"] == "stop_candidate"
    # and the same visual evidence participates in the conflict model
    assert conflict["conflict_status"] == "preferred_side"
    assert conflict["conflict_preferred_side"] == "support"
    assert scenario["verdict"] == "PASS"


def test_q4_failures_stay_unavailable() -> None:
    scenario = _scenario(run_qualification(), "Q4_fail_closed")

    assert scenario["ssrf"]["fetcher_reason"] == "image_url_not_public"
    assert scenario["ssrf"]["outcome_reason"] == "image_url_not_public"
    assert scenario["ssrf"]["units"] == 0
    assert scenario["ssrf"]["vision_calls"] == 0
    assert scenario["provider_failure"]["outcome_reason"] == "vision_description_failed"
    assert scenario["provider_failure"]["units"] == 0
    assert scenario["verdict"] == "PASS"


def test_q5_provenance_is_traceable() -> None:
    scenario = _scenario(run_qualification(), "Q5_provenance")
    unit = scenario["unit"]

    assert unit["page"] == 4
    assert unit["region"] == "bbox:10,10,200,120"
    assert unit["source"] == "https://cdn.example.com/figure4.png"
    assert unit["provenance"].startswith(unit["source"])
    assert unit["source_type"] == "chart"
    audit = scenario["audit"][0]
    assert audit["purpose"] == "image_description"
    assert audit["status"] == "normalized"
    assert audit["data_categories"] == ["image_content"]
    assert scenario["verdict"] == "PASS"


def test_q6_vision_uses_the_shared_clock_without_touching_reads() -> None:
    scenario = _scenario(run_qualification(), "Q6_budget")

    assert scenario["max_vision_calls_with_time_left"] == 1
    assert scenario["max_vision_calls_near_deadline"] == 0
    assert scenario["vision_calls_used"] == 1
    assert scenario["reads_used_before"] == scenario["reads_used_after"]
    assert scenario["verdict"] == "PASS"
