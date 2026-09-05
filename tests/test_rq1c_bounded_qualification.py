from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tools.evaluate_rq1c_bounded_qualification import evaluate
from tools.run_rq1c_bounded_qualification import (
    _answer_stage_model_calls,
    _evidence_rows,
    _load_manifest,
    _observed_read_count,
    _provider_audit,
    _source_rows,
    _unavailable_answer_surface,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "research_quality"
MANIFEST = FIXTURE_DIR / "rq1c_bounded_holdout_manifest.json"
RUBRIC = FIXTURE_DIR / "rq1c_bounded_holdout_rubric.json"
REQUIRED_PROBES = (
    "provider_timeout_retry",
    "user_cancellation",
    "provider_http_429",
    "provider_http_503",
    "unreadable_page",
    "duplicate_republication",
)
TEST_GIT_SHA = "a" * 40


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _rubric() -> dict[str, object]:
    return json.loads(RUBRIC.read_text(encoding="utf-8"))


def _reviewable_answer(case_id: str) -> dict[str, object]:
    text = f"synthetic production answer for evaluator contract: {case_id}"
    answer_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    candidate_sha = hashlib.sha256(f"candidate:{text}".encode("utf-8")).hexdigest()
    return {
        "status": "available",
        "source": "production_chat",
        "text": text,
        "content_sha256": answer_sha,
        "reason": "",
        "turn_id": f"turn-{case_id}",
        "turn_status": "completed",
        "validation": {
            "schema_version": "answer-validation-audit-v1",
            "candidate_answer_sha256": candidate_sha,
            "learner_answer_sha256": answer_sha,
            "phases": {
                "answer_generation": {
                    "attempted": True,
                    "model_calls": 1,
                    "attempts": 1,
                    "outcome": "completed",
                    "error_type": "",
                },
                "answer_claim_binding": {
                    "attempted": True,
                    "model_calls": 1,
                    "attempts": 1,
                    "outcome": "passed",
                    "error_type": "",
                },
            },
        },
    }


def _runtime(case_ids: list[str]) -> dict[str, object]:
    return {
        "schema_version": "rq1c-bounded-qualification-runtime-v1",
        "git_sha": TEST_GIT_SHA,
        "leakage_contract": {
            "runtime_case_keys": ["id", "category", "question"],
            "rubric_loaded_by_runner": False,
            "stores_page_bodies": False,
            "stores_research_query_text": False,
            "captures_production_final_answer": True,
            "second_web_acquisition_during_synthesis": False,
        },
        "cases": [
            {
                "case_id": case_id,
                "runner_error_type": "",
                "budget_contract_violations": [],
                "budget_observed": {
                    "candidate_count": 5,
                    "read_count": 3,
                    "read_attempt_count": 3,
                    "research_model_call_count": 3,
                    "answer_generation_model_call_count": 1,
                    "answer_binding_model_call_count": 1,
                    "model_call_count": 5,
                    "elapsed_seconds": 30.0,
                },
                "answer": _reviewable_answer(case_id),
                "search": {"audits": [{"query_sha256": "a" * 64}]},
            }
            for case_id in case_ids
        ],
    }


def _review(case_ids: list[str], runtime_path: Path) -> dict[str, object]:
    return {
        "schema_version": "rq1c-bounded-independent-review-v1",
        "runtime_artifact_sha256": hashlib.sha256(runtime_path.read_bytes()).hexdigest(),
        "cases": [
            {
                "case_id": case_id,
                "truthfulness": "pass",
                "quality": "pass" if index < 10 else "fail",
                "hard_failures": [],
            }
            for index, case_id in enumerate(case_ids)
        ],
    }


def _protocol(
    runtime_path: Path,
    *,
    failed_probe: str | None = None,
    probe_ids: tuple[str, ...] = REQUIRED_PROBES,
) -> dict[str, object]:
    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    return {
        "schema_version": "rq1c-bounded-protocol-probes-v1",
        "git_sha": runtime["git_sha"],
        "runtime_artifact_sha256": hashlib.sha256(runtime_path.read_bytes()).hexdigest(),
        "leakage_contract": {
            "stores_generated_query_text": False,
            "stores_page_bodies": False,
            "stores_raw_provider_errors": False,
        },
        "probes": [
            {
                "id": probe_id,
                "status": "fail" if probe_id == failed_probe else "pass",
            }
            for probe_id in probe_ids
        ],
    }


def _evaluate_fixture_set(
    tmp_path: Path,
    *,
    runtime: dict[str, object] | None = None,
    failed_probe: str | None = None,
) -> dict[str, object]:
    rubric = _rubric()
    case_ids = [str(case["id"]) for case in rubric["cases"]]  # type: ignore[index]
    runtime_value = runtime or _runtime(case_ids)
    runtime_path = tmp_path / "runtime.json"
    review_path = tmp_path / "review.json"
    protocol_path = tmp_path / "protocol.json"
    output_path = tmp_path / "report.json"
    _write_json(runtime_path, runtime_value)
    _write_json(review_path, _review(case_ids, runtime_path))
    _write_json(protocol_path, _protocol(runtime_path, failed_probe=failed_probe))
    return evaluate(
        runtime_path=runtime_path,
        rubric_path=RUBRIC,
        review_path=review_path,
        protocol_path=protocol_path,
        output_path=output_path,
    )


def test_runtime_manifest_is_exactly_twelve_gold_free_cases() -> None:
    cases = _load_manifest(MANIFEST)

    assert len(cases) == 12
    assert len({case["id"] for case in cases}) == 12
    assert all(set(case) == {"id", "category", "question"} for case in cases)


def test_runtime_manifest_rejects_evaluation_fields(tmp_path: Path) -> None:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    payload["cases"][0]["expected_answer"] = "must never enter the runner"
    path = tmp_path / "leaky_manifest.json"
    _write_json(path, payload)

    with pytest.raises(ValueError, match="only id/category/question"):
        _load_manifest(path)


def test_provider_audit_projects_reason_and_attempts_without_raw_error_type() -> None:
    rows = _provider_audit(
        [
            {
                "query": "private generated query",
                "providers_attempted": ["legacy-fallback"],
                "provider_audit": {
                    "providers_attempted": ["primary"],
                    "provider_outcomes": [
                        {
                            "provider": "primary",
                            "status": "unavailable",
                            "reason": "http_503",
                            "attempts": 2,
                            "result_count": 0,
                            "error_type": "must-not-project",
                        }
                    ],
                },
            }
        ]
    )

    assert rows[0]["providers_attempted"] == ["primary"]
    assert rows[0]["query_sha256"] == hashlib.sha256(
        b"private generated query"
    ).hexdigest()
    assert rows[0]["provider_outcomes"] == [
        {
            "provider": "primary",
            "status": "unavailable",
            "reason": "http_503",
            "attempts": 2,
            "result_count": 0,
        }
    ]


def test_source_projection_reads_nested_production_item_and_assessment() -> None:
    rows = _source_rows(
        [
            {
                "candidate_id": "candidate-1",
                "item": {
                    "title": "Primary source",
                    "url": "https://example.test/source",
                    "source": "example",
                    "published_at": "2026-09-03",
                },
                "assessment": {
                    "source_role": "primary",
                    "source_cluster_id": "cluster-a",
                },
                "read_status": "read",
                "extractions": {
                    "claim-a": {"status": "eligible"},
                    "claim-b": {"status": "rejected"},
                },
            }
        ]
    )

    assert rows == [
        {
            "candidate_id": "candidate-1",
            "title": "Primary source",
            "url": "https://example.test/source",
            "source": "example",
            "published_at": "2026-09-03",
            "read_status": "read",
            "source_role": "primary",
            "cluster_id": "cluster-a",
            "extraction_statuses": ["eligible", "rejected"],
        }
    ]


def test_evidence_projection_uses_actual_brief_fields_not_summary_or_excerpt() -> None:
    rows = _evidence_rows(
        {
            "eligible_evidence": [
                {
                    "evidence_id": "e-1",
                    "claim_id": "c-1",
                    "relation": "direct_support",
                    "strength": 0.9,
                    "source_role": "primary",
                    "source_cluster_id": "cluster-a",
                    "title": "Primary source",
                    "url": "https://example.test/source",
                    "published_at": "2026-09-03",
                    "locator": "section 2",
                    "anchored_spans": ["bounded anchor"],
                    "caveats": ["current as of date"],
                    "excerpt": "legacy field must not be projected",
                }
            ]
        }
    )

    assert rows[0]["source_cluster_id"] == "cluster-a"
    assert rows[0]["locator"] == "section 2"
    assert rows[0]["anchored_spans"] == ["bounded anchor"]
    assert rows[0]["caveats"] == ["current as of date"]
    assert "excerpt" not in rows[0]


def test_read_budget_projection_prefers_production_success_metric() -> None:
    runtime = {
        "read_outcomes": [
            {"status": "success"},
            {"status": "failed"},
            {"status": "failed"},
        ]
    }

    assert _observed_read_count({"read_count": 1}, runtime) == 1
    assert _observed_read_count({}, runtime) == 1


def test_unavailable_answer_surface_is_fail_closed() -> None:
    assert _unavailable_answer_surface() == {
        "status": "unavailable",
        "source": "none",
        "text": "",
        "content_sha256": "",
        "reason": "production_chat_unavailable",
        "turn_id": "",
        "turn_status": "",
        "validation": {},
    }


def test_answer_stage_model_calls_require_both_production_phases() -> None:
    answer = _reviewable_answer("calls")
    validation = answer["validation"]
    assert isinstance(validation, dict)
    assert _answer_stage_model_calls(validation) == (1, 1)

    missing_binding = json.loads(json.dumps(validation))
    del missing_binding["phases"]["answer_claim_binding"]
    assert _answer_stage_model_calls(missing_binding) is None


def test_independent_evaluator_can_reach_go_only_after_all_gates(tmp_path: Path) -> None:
    report = _evaluate_fixture_set(tmp_path)

    assert report["decision"] == "GO"
    assert report["inputs"]["git_sha"] == TEST_GIT_SHA  # type: ignore[index]
    assert report["scores"]["reviewable_answer_cases"] == "12/12"  # type: ignore[index]
    assert report["scores"]["truthfulness"] == "12/12"  # type: ignore[index]
    assert report["scores"]["quality"] == "10/12"  # type: ignore[index]
    assert all(report["checks"].values())  # type: ignore[union-attr]


def test_unavailable_final_answer_surface_forces_no_go(tmp_path: Path) -> None:
    rubric = _rubric()
    case_ids = [str(case["id"]) for case in rubric["cases"]]  # type: ignore[index]
    runtime = _runtime(case_ids)
    runtime["cases"][0]["answer"] = _unavailable_answer_surface()  # type: ignore[index]

    report = _evaluate_fixture_set(tmp_path, runtime=runtime)

    assert report["decision"] == "NO-GO"
    assert report["scores"]["reviewable_answer_cases"] == "11/12"  # type: ignore[index]
    assert report["checks"]["answer_surface"] is False  # type: ignore[index]


def test_missing_or_nonproduction_answer_surface_forces_no_go(tmp_path: Path) -> None:
    rubric = _rubric()
    case_ids = [str(case["id"]) for case in rubric["cases"]]  # type: ignore[index]
    runtime = _runtime(case_ids)
    del runtime["cases"][0]["answer"]  # type: ignore[index]
    runtime["cases"][1]["answer"]["source"] = "qualification_side_generator"  # type: ignore[index]

    report = _evaluate_fixture_set(tmp_path, runtime=runtime)

    assert report["decision"] == "NO-GO"
    assert report["scores"]["reviewable_answer_cases"] == "10/12"  # type: ignore[index]
    assert report["checks"]["answer_surface"] is False  # type: ignore[index]


def test_reviewable_answer_hash_must_bind_exact_answer_text(tmp_path: Path) -> None:
    rubric = _rubric()
    case_ids = [str(case["id"]) for case in rubric["cases"]]  # type: ignore[index]
    runtime = _runtime(case_ids)
    runtime["cases"][0]["answer"]["content_sha256"] = "0" * 64  # type: ignore[index]

    with pytest.raises(ValueError, match="content sha256 mismatch"):
        _evaluate_fixture_set(tmp_path, runtime=runtime)


def test_production_validation_audit_is_required_for_reviewable_answer(tmp_path: Path) -> None:
    rubric = _rubric()
    case_ids = [str(case["id"]) for case in rubric["cases"]]  # type: ignore[index]
    runtime = _runtime(case_ids)
    del runtime["cases"][0]["answer"]["validation"]  # type: ignore[index]

    report = _evaluate_fixture_set(tmp_path, runtime=runtime)

    assert report["decision"] == "NO-GO"
    assert report["scores"]["reviewable_answer_cases"] == "11/12"  # type: ignore[index]
    assert report["checks"]["answer_surface"] is False  # type: ignore[index]


def test_production_validation_learner_hash_must_match_answer(tmp_path: Path) -> None:
    rubric = _rubric()
    case_ids = [str(case["id"]) for case in rubric["cases"]]  # type: ignore[index]
    runtime = _runtime(case_ids)
    runtime["cases"][0]["answer"]["validation"]["learner_answer_sha256"] = "0" * 64  # type: ignore[index]

    with pytest.raises(ValueError, match="learner sha256 mismatch"):
        _evaluate_fixture_set(tmp_path, runtime=runtime)


def test_missing_production_answer_phase_forces_no_go(tmp_path: Path) -> None:
    rubric = _rubric()
    case_ids = [str(case["id"]) for case in rubric["cases"]]  # type: ignore[index]
    runtime = _runtime(case_ids)
    del runtime["cases"][0]["answer"]["validation"]["phases"][  # type: ignore[index]
        "answer_claim_binding"
    ]

    report = _evaluate_fixture_set(tmp_path, runtime=runtime)

    assert report["decision"] == "NO-GO"
    assert report["scores"]["reviewable_answer_cases"] == "11/12"  # type: ignore[index]


def test_runtime_must_declare_production_capture_and_no_second_acquisition(tmp_path: Path) -> None:
    rubric = _rubric()
    case_ids = [str(case["id"]) for case in rubric["cases"]]  # type: ignore[index]
    runtime = _runtime(case_ids)
    runtime["leakage_contract"]["captures_production_final_answer"] = False  # type: ignore[index]

    with pytest.raises(ValueError, match="did not capture production final answers"):
        _evaluate_fixture_set(tmp_path, runtime=runtime)

    runtime = _runtime(case_ids)
    runtime["leakage_contract"]["second_web_acquisition_during_synthesis"] = True  # type: ignore[index]
    with pytest.raises(ValueError, match="second web acquisition"):
        _evaluate_fixture_set(tmp_path, runtime=runtime)


def test_runtime_total_model_call_budget_is_independently_enforced(tmp_path: Path) -> None:
    rubric = _rubric()
    case_ids = [str(case["id"]) for case in rubric["cases"]]  # type: ignore[index]
    runtime = _runtime(case_ids)
    first = runtime["cases"][0]  # type: ignore[index]
    first["budget_observed"]["model_call_count"] = 7

    report = _evaluate_fixture_set(tmp_path, runtime=runtime)

    assert report["decision"] == "NO-GO"
    assert report["checks"]["runtime_budget"] is False  # type: ignore[index]
    assert report["scores"]["budget_violation_cases"] == 1  # type: ignore[index]


def test_unknown_answer_stage_call_count_forces_no_go(tmp_path: Path) -> None:
    rubric = _rubric()
    case_ids = [str(case["id"]) for case in rubric["cases"]]  # type: ignore[index]
    runtime = _runtime(case_ids)
    first = runtime["cases"][0]  # type: ignore[index]
    first["runner_error_type"] = "RuntimeError"
    first["budget_observed"]["model_call_count"] = None
    first["budget_contract_violations"] = ["answer_stage_model_call_count_unavailable"]

    report = _evaluate_fixture_set(tmp_path, runtime=runtime)

    assert report["decision"] == "NO-GO"
    assert report["checks"]["runner_errors"] is False  # type: ignore[index]
    assert report["checks"]["runtime_budget"] is False  # type: ignore[index]


def test_review_must_bind_exact_runtime_artifact(tmp_path: Path) -> None:
    rubric = _rubric()
    case_ids = [str(case["id"]) for case in rubric["cases"]]  # type: ignore[index]
    runtime_path = tmp_path / "runtime.json"
    review_path = tmp_path / "review.json"
    protocol_path = tmp_path / "protocol.json"
    _write_json(runtime_path, _runtime(case_ids))
    review = _review(case_ids, runtime_path)
    review["runtime_artifact_sha256"] = "0" * 64
    _write_json(review_path, review)
    _write_json(protocol_path, _protocol(runtime_path))

    with pytest.raises(ValueError, match="not bound to this runtime artifact"):
        evaluate(
            runtime_path=runtime_path,
            rubric_path=RUBRIC,
            review_path=review_path,
            protocol_path=protocol_path,
            output_path=tmp_path / "report.json",
        )


def test_runtime_git_sha_must_be_exact(tmp_path: Path) -> None:
    rubric = _rubric()
    case_ids = [str(case["id"]) for case in rubric["cases"]]  # type: ignore[index]
    runtime = _runtime(case_ids)
    runtime["git_sha"] = "not-a-git-sha"
    runtime_path = tmp_path / "runtime.json"
    review_path = tmp_path / "review.json"
    protocol_path = tmp_path / "protocol.json"
    _write_json(runtime_path, runtime)
    _write_json(review_path, _review(case_ids, runtime_path))
    protocol = _protocol(runtime_path)
    protocol["git_sha"] = TEST_GIT_SHA
    _write_json(protocol_path, protocol)

    with pytest.raises(ValueError, match="runtime artifact git_sha"):
        evaluate(
            runtime_path=runtime_path,
            rubric_path=RUBRIC,
            review_path=review_path,
            protocol_path=protocol_path,
            output_path=tmp_path / "report.json",
        )


def test_protocol_must_bind_exact_runtime_artifact(tmp_path: Path) -> None:
    rubric = _rubric()
    case_ids = [str(case["id"]) for case in rubric["cases"]]  # type: ignore[index]
    runtime_path = tmp_path / "runtime.json"
    review_path = tmp_path / "review.json"
    protocol_path = tmp_path / "protocol.json"
    _write_json(runtime_path, _runtime(case_ids))
    _write_json(review_path, _review(case_ids, runtime_path))
    protocol = _protocol(runtime_path)
    protocol["runtime_artifact_sha256"] = "0" * 64
    _write_json(protocol_path, protocol)

    with pytest.raises(ValueError, match="protocol probes are not bound"):
        evaluate(
            runtime_path=runtime_path,
            rubric_path=RUBRIC,
            review_path=review_path,
            protocol_path=protocol_path,
            output_path=tmp_path / "report.json",
        )


def test_protocol_git_sha_must_match_runtime(tmp_path: Path) -> None:
    rubric = _rubric()
    case_ids = [str(case["id"]) for case in rubric["cases"]]  # type: ignore[index]
    runtime_path = tmp_path / "runtime.json"
    review_path = tmp_path / "review.json"
    protocol_path = tmp_path / "protocol.json"
    _write_json(runtime_path, _runtime(case_ids))
    _write_json(review_path, _review(case_ids, runtime_path))
    protocol = _protocol(runtime_path)
    protocol["git_sha"] = "b" * 40
    _write_json(protocol_path, protocol)

    with pytest.raises(ValueError, match="protocol/runtime git sha mismatch"):
        evaluate(
            runtime_path=runtime_path,
            rubric_path=RUBRIC,
            review_path=review_path,
            protocol_path=protocol_path,
            output_path=tmp_path / "report.json",
        )


def test_protocol_probe_set_is_exact_and_unique(tmp_path: Path) -> None:
    rubric = _rubric()
    case_ids = [str(case["id"]) for case in rubric["cases"]]  # type: ignore[index]
    runtime_path = tmp_path / "runtime.json"
    review_path = tmp_path / "review.json"
    protocol_path = tmp_path / "protocol.json"
    _write_json(runtime_path, _runtime(case_ids))
    _write_json(review_path, _review(case_ids, runtime_path))

    invalid_sets = (
        REQUIRED_PROBES[:-1],
        (*REQUIRED_PROBES[:-1], REQUIRED_PROBES[0]),
        (*REQUIRED_PROBES, "unexpected_probe"),
    )
    for index, probe_ids in enumerate(invalid_sets):
        _write_json(protocol_path, _protocol(runtime_path, probe_ids=probe_ids))
        with pytest.raises(ValueError, match="protocol probe"):
            evaluate(
                runtime_path=runtime_path,
                rubric_path=RUBRIC,
                review_path=review_path,
                protocol_path=protocol_path,
                output_path=tmp_path / f"report-{index}.json",
            )


def test_runtime_artifact_rejects_plaintext_generated_query(tmp_path: Path) -> None:
    rubric = _rubric()
    case_ids = [str(case["id"]) for case in rubric["cases"]]  # type: ignore[index]
    runtime = _runtime(case_ids)
    audit = runtime["cases"][0]["search"]["audits"][0]  # type: ignore[index]
    audit["query_text"] = "secret generated query"
    runtime_path = tmp_path / "runtime.json"
    review_path = tmp_path / "review.json"
    protocol_path = tmp_path / "protocol.json"
    _write_json(runtime_path, runtime)
    _write_json(review_path, _review(case_ids, runtime_path))
    _write_json(protocol_path, _protocol(runtime_path))

    with pytest.raises(ValueError, match="leaked generated research query text"):
        evaluate(
            runtime_path=runtime_path,
            rubric_path=RUBRIC,
            review_path=review_path,
            protocol_path=protocol_path,
            output_path=tmp_path / "report.json",
        )


def test_runtime_budget_violation_forces_no_go(tmp_path: Path) -> None:
    rubric = _rubric()
    case_ids = [str(case["id"]) for case in rubric["cases"]]  # type: ignore[index]
    runtime = _runtime(case_ids)
    first_case = runtime["cases"][0]  # type: ignore[index]
    first_case["budget_contract_violations"] = ["hard_timeout_seconds>60"]

    report = _evaluate_fixture_set(tmp_path, runtime=runtime)

    assert report["decision"] == "NO-GO"
    assert report["checks"]["runtime_budget"] is False  # type: ignore[index]


def test_failed_protocol_probe_forces_no_go(tmp_path: Path) -> None:
    report = _evaluate_fixture_set(tmp_path, failed_probe="provider_http_503")

    assert report["decision"] == "NO-GO"
    assert report["checks"]["protocol_probes"] is False  # type: ignore[index]
