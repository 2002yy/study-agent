"""Experiment controls, not an automatic semantic judge."""

import json

import pytest

from tools.research_ability_ab import (
    blind_package,
    citation_checks,
    execute,
    plan,
    schedule,
    sha,
    sources_for,
    tasks_for_b,
    validate_cases,
    validate_prior_registry,
    write_new,
)


CASE = {
    "id": "open-1",
    "question": "Compare two versions; retain unknown dates.",
    "rubric": ["Keep both versions and uncertainty."],
}


def completion(**kwargs):
    context = json.loads(kwargs["messages"][1]["content"])
    if "episode" in context:
        return json.dumps(
            {
                "task_id": context["episode"]["task_id"],
                "intent": "NEW_RESEARCH",
                "subject": "two versions",
                "constraints_delta": {},
                "unresolved_questions": [{"id": "rq-date", "question": "Which dates?"}],
                "suggested_next_action": "find sources",
                "proposed_queries": [{"rq_id": "rq-date", "query": "release dates"}],
            }
        )
    return '{"tasks":[{"question":"Which dates?"}]}'


def test_b_ids_are_server_owned_stable_and_not_semantic_acceptance():
    raw = {"tasks": [{"question": "same"}, {"question": "same"}]}
    first = tasks_for_b(raw, "owner")
    assert first == tasks_for_b(raw, "owner")
    assert first[0]["id"] != first[1]["id"]
    assert first != tasks_for_b(raw, "other")


@pytest.mark.parametrize(
    "raw",
    [
        {"tasks": []},
        {"tasks": [{"question": ""}]},
        {"tasks": [{"id": "rq-1", "question": "x"}]},
        [],
    ],
)
def test_b_rejects_transport_errors_without_repairs(raw):
    with pytest.raises(ValueError):
        tasks_for_b(raw, "x")


def test_a_uses_existing_parser_b_does_not_repair_a_identity():
    assert plan(CASE, "A", completion)["tasks"][0]["id"] == "rq-date"

    def dotted(**kwargs):
        return completion(**kwargs).replace("rq-date", "rq-4.2")

    with pytest.raises(ValueError, match="question_id"):
        plan(CASE, "A", dotted)
    assert len(plan(CASE, "B", completion)["tasks"]) == 1


def test_schedule_is_paired_repeated_reproducible_without_case_changes():
    cases = [CASE, {**CASE, "id": "open-2"}]
    rows = schedule(cases, 99)
    assert rows == schedule(cases, 99)
    assert len(rows) == 8
    assert {(r["arm"], r["repeat"]) for r in rows[:]} == {
        ("A", 1),
        ("A", 2),
        ("B", 1),
        ("B", 2),
    }


def test_raw_invalid_output_preserved_no_retry_no_authority():
    calls, sink = [], []

    def invalid(**kwargs):
        calls.append(kwargs)
        return "not json"

    result = execute(
        {"case": CASE, "arm": "A", "repeat": 1},
        invalid,
        phase="planning",
        raw_sink=lambda kind, value: sink.append((kind, value)),
    )
    assert len(calls) == 1
    assert calls[0]["timeout"] <= 5
    assert result["status"] == "blocked"
    assert result["calls"][0]["raw_output"] == "not json"
    assert [kind for kind, _ in sink] == ["request", "response"]
    assert result["publication_authority"] is False


def test_sources_hash_checked_and_reference_existence_not_semantic_support():
    sources = [
        {
            "id": "s1",
            "url": "https://example.org/doc",
            "text": "version 1",
            "sha256": sha("version 1"),
        }
    ]
    assert sources_for({"sources": sources}) == sources
    answer = {
        "claims": [
            {
                "text": "version 2 is better",
                "citations": [{"source_id": "s1", "quote": "version 1"}],
            }
        ],
        "unknowns": [],
        "answer": "candidate",
    }
    checks = citation_checks(answer, sources)
    assert checks["structural_errors"] == []
    assert checks["semantic_support"] == "PENDING_HUMAN_REVIEW"
    sources[0]["sha256"] = "invalid"
    with pytest.raises(ValueError, match="hash"):
        sources_for({"sources": sources})


@pytest.mark.parametrize(
    "citation",
    [
        {"source_id": "absent", "quote": "x"},
        {"source_id": "s1", "quote": ""},
        {"source_id": "s1", "quote": "not in text"},
    ],
)
def test_bad_reference_remains_rejected(citation):
    answer = {
        "claims": [{"text": "fact", "citations": [citation]}],
        "unknowns": [],
        "answer": "x",
    }
    assert citation_checks(answer, [{"id": "s1", "text": "actual"}])[
        "structural_errors"
    ]


def test_evidence_phase_blocks_without_matching_plan_and_never_calls_model():
    case = {
        **CASE,
        "sources": [
            {
                "id": "s1",
                "url": "https://example.org",
                "text": "body",
                "sha256": sha("body"),
            }
        ],
    }
    calls = []
    result = execute(
        {"case": case, "arm": "B", "repeat": 1},
        lambda **kw: calls.append(kw),
        phase="fixed-evidence",
    )
    assert result["error"] == "same_arm_plan_unavailable"
    assert not calls


def test_anonymous_review_excludes_arm_ids_prompts_and_outcomes():
    result = execute(
        {"case": CASE, "arm": "B", "repeat": 1}, completion, phase="planning"
    )
    pack, key = blind_package({"cases": [CASE]}, [result], seed=1)
    assert pack[0]["output"] == ["Which dates?"]
    assert not {"arm", "calls", "status", "repeat"} & pack[0].keys()
    assert "rq-" not in json.dumps(pack)
    assert key[0]["arm"] == "B"
    assert pack[0]["score"] is None


def test_freeze_requires_original_question_rubric_unique_id_and_preserves_artifacts(
    tmp_path,
):
    validate_cases([CASE])
    with pytest.raises(ValueError, match="case_identity"):
        validate_cases([CASE, CASE])
    with pytest.raises(ValueError, match="rubric"):
        validate_cases([{**CASE, "rubric": []}])
    target = tmp_path / "freeze.json"
    write_new(target, CASE)
    with pytest.raises(FileExistsError):
        write_new(target, {})


def test_changed_evidence_or_code_or_model_requires_new_paired_freeze():
    registry = {
        "phase": "planning",
        "manifest_sha256": "m",
        "harness_sha256": "h",
        "effective_config": {"model": "same"},
        "dependency_hashes": {"owner": "same"},
    }
    current = {**registry, "phase": "fixed-evidence"}
    validate_prior_registry(registry, current)
    for key in (
        "manifest_sha256",
        "harness_sha256",
        "effective_config",
        "dependency_hashes",
    ):
        with pytest.raises(ValueError, match="planning_freeze_mismatch"):
            validate_prior_registry(registry, {**current, key: "changed"})
