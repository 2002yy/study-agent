"""Recorded pilot bindings must not promote diagnostic reads into answers."""

from copy import deepcopy
from pathlib import Path

import pytest

from src.evals.release_benchmark_plan import load_release_benchmark_plan
from src.evals.release_benchmark_recorded_pilot import (
    BUNDLE_SCHEMA,
    build_frozen_pilot_observation,
)
from src.evals.release_benchmark_registry import load_gold, load_registry
from src.evals.release_benchmark_scoring import parse_recording, score_recordings

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/release_benchmark"
HEAD = "a" * 40
AT = "2026-09-29T01:00:30Z"


def _fixtures():
    plan = load_release_benchmark_plan(FIXTURES / "plan_v1.json")
    registry = load_registry(FIXTURES / "registry_v1.json", ROOT, plan)
    gold = load_gold(FIXTURES / "gold_v1.json", registry)
    return plan, registry, gold


def _source_fields(case):
    source = case.sources[0]
    return {"locator": source.locator, "source_sha256": source.sha256,
            "page": source.page, "region": source.region}


def _text(case):
    return {
        "case_id": case.case_id, "case_content_sha256": case.content_sha256,
        "run_status": "completed", "provider_status": "found",
        "stop_reason": "sources_read", "network_guard": "python_socket_connect_blocked",
        "source_reads": [{**_source_fields(case), "source_id": "web_source_1",
                          "state": "read"}],
    }


def _visual(case):
    return {
        "case_id": case.case_id, "case_content_sha256": case.content_sha256,
        "network_guard": "python_socket_connect_blocked",
        "source_outcomes": [{**_source_fields(case),
                             "source_id": case.sources[0].source_id,
                             "status": "unavailable",
                             "reason": "vision_not_configured"}],
    }


def _bundle(registry):
    pilots = []
    for case in registry.cases:
        if case.mode != "frozen":
            continue
        if case.modality in {"text", "pdf"}:
            result = _text(case)
        elif case.modality == "mixed":
            result = {"case_id": case.case_id, "text_read": _text(case),
                      "visual_read": _visual(case)}
        else:
            result = _visual(case)
        pilots.append({"case_id": case.case_id, "observed_at": AT,
                       "result": result})
    return {"schema_version": BUNDLE_SCHEMA, "code_sha": HEAD,
            "started_at": "2026-09-29T01:00:00Z",
            "ended_at": "2026-09-29T01:01:00Z", "pilots": pilots}


def test_frozen_pilot_records_five_unavailable_cases_and_keeps_live_missing():
    plan, registry, gold = _fixtures()
    observation = build_frozen_pilot_observation(
        plan, registry, gold, code_sha=HEAD, bundle=_bundle(registry),
        transcript_sha256="b" * 64,
    )
    reads = {case["case_id"]: case["source_reads"][0]
             for case in observation["cases"]}
    assert reads["REL-F-TEXT-001"]["source_id"] == "NOAA-SURGE"
    assert reads["REL-F-PDF-001"]["state"] == "read_ok"
    assert reads["REL-F-IMAGE-001"]["state"] == "read_failed"
    assert reads["REL-F-MIXED-001"]["state"] == "read_ok"
    assert all(case["state"] == "unavailable" for case in observation["cases"])
    run = parse_recording(observation, plan, registry, gold, HEAD)
    score = score_recordings(plan, registry, gold, (run,))
    assert score["admitted_release_cases"] == 6
    assert score["missing_observations"] == 1
    assert {case["case_id"] for case in score["cases"]
            if case["state"] == "missing"} == {"REL-L-TEXT-001"}
    assert all(case["release_admitted"] for case in score["cases"])
    assert score["release_gate"] == "NO_GO"


def test_frozen_pilot_rejects_source_drift_and_unqualified_visual_promotion():
    plan, registry, gold = _fixtures()
    original = _bundle(registry)
    drifted = deepcopy(original)
    drifted["pilots"][0]["result"]["source_reads"][0]["source_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="source bytes/location"):
        build_frozen_pilot_observation(
            plan, registry, gold, code_sha=HEAD, bundle=drifted,
            transcript_sha256="b" * 64,
        )
    promoted = deepcopy(original)
    image = next(item for item in promoted["pilots"]
                 if item["case_id"] == "REL-F-IMAGE-001")
    image["result"]["source_outcomes"][0]["status"] = "normalized"
    with pytest.raises(ValueError, match="cannot qualify"):
        build_frozen_pilot_observation(
            plan, registry, gold, code_sha=HEAD, bundle=promoted,
            transcript_sha256="b" * 64,
        )


def test_frozen_pilot_rejects_case_scope_drift():
    plan, registry, gold = _fixtures()
    bundle = _bundle(registry)
    bundle["pilots"].pop()
    with pytest.raises(ValueError, match="case scope"):
        build_frozen_pilot_observation(
            plan, registry, gold, code_sha=HEAD, bundle=bundle,
            transcript_sha256="b" * 64,
        )
