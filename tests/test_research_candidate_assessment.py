from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import Any

import pytest

import src.web.research.active_semantics as active_semantics_module
from src.web.research.active_semantics import RuntimeCandidateAssessor

from src.web.research.candidate_assessment import (
    CANDIDATE_ASSESSMENT_SCHEMA_VERSION,
    CANDIDATE_ASSESSMENT_WIRE_SCHEMA_VERSION,
    CompactAssessmentCodeError,
    CompactAssessmentGainSignalCodeError,
    CompactAssessmentGainSignalDuplicateError,
    CompactAssessmentRelevanceCodeError,
    CompactAssessmentSourceRoleCodeError,
    build_candidate_assessment_request,
    parse_compact_candidate_assessment_response,
    parse_candidate_assessment_response,
)
from src.web.research.candidate_pool import CandidatePoolItem
from src.web.research.contracts import EvidenceRequirement, ResearchClaim
from src.web.research.gap_planner import GapSearchIntent
from src.web.research.model_gateway import ResearchModelGateway
from src.web.research.source_cluster import CandidateClusterAssignment


def _candidate(candidate_id: str) -> CandidatePoolItem:
    url = f"https://{candidate_id}.example/item"
    return CandidatePoolItem(
        id=candidate_id,
        canonical_url=url,
        url=url,
        title=f"Title {candidate_id}",
        snippet="bounded snippet",
        source="Publisher",
        published_at="2026-08-20",
        query_ids=("query",),
        intents=(GapSearchIntent.PRIMARY,),
        providers=("searxng",),
        first_seen_rank=1,
    )


def _claim() -> ResearchClaim:
    return ResearchClaim(
        id="claim-1",
        question_id="question-1",
        text="Official current policy",
        kind="factual",
        priority="critical",
        state="searching",
        evidence_requirement=EvidenceRequirement(
            source_roles=("primary", "independent_secondary"),
            min_independent_sources=1,
            requires_primary_source=True,
            requires_successful_read=True,
            requires_dated_evidence=True,
        ),
    )


def _payload(candidate_ids: tuple[str, ...]) -> dict:
    return {
        "schema_version": CANDIDATE_ASSESSMENT_SCHEMA_VERSION,
        "assessments": [
            {
                "candidate_id": candidate_id,
                "relevance": "answer_relevant",
                "relevance_confidence": 0.8,
                "source_role": "primary",
                "source_role_confidence": 0.9,
                "expected_gain_signals": ["new_primary"],
            }
            for candidate_id in candidate_ids
        ],
    }


def _assignment(candidate_id: str) -> CandidateClusterAssignment:
    return CandidateClusterAssignment(
        candidate_id=candidate_id,
        cluster_id=f"cluster-{candidate_id}",
        independence_key=f"publisher:{candidate_id}",
        basis="publisher",
        source_role="primary",
    )


def test_request_is_bounded_and_contains_no_raw_page_body() -> None:
    request = build_candidate_assessment_request((_candidate("a"),), claim=_claim())
    payload = request.to_dict()
    assert payload["schema_version"] == CANDIDATE_ASSESSMENT_SCHEMA_VERSION
    assert set(payload["candidates"][0]) == {
        "candidate_id",
        "title",
        "snippet",
        "canonical_url",
        "published_at",
        "query_intents",
    }
    assert "body" not in payload["candidates"][0]


def test_parser_attaches_server_owned_cluster_freshness_and_cost() -> None:
    candidates = (_candidate("a"), _candidate("b"))
    request = build_candidate_assessment_request(candidates, claim=_claim())
    parsed = parse_candidate_assessment_response(
        _payload(("a", "b")),
        request=request,
        cluster_assignments={"a": _assignment("a"), "b": _assignment("b")},
        freshness_scores={"a": 0.75},
        read_costs={"a": 2.5},
    )
    assert parsed["a"].cluster_id == "cluster-a"
    assert parsed["a"].freshness_score == 0.75
    assert parsed["a"].estimated_read_cost == 2.5
    assert parsed["b"].freshness_score == 0.0


def test_compact_parser_restores_server_owned_candidate_identity() -> None:
    candidates = (_candidate("a"), _candidate("b"))
    request = build_candidate_assessment_request(candidates, claim=_claim())

    parsed = parse_compact_candidate_assessment_response(
        {
            "v": CANDIDATE_ASSESSMENT_WIRE_SCHEMA_VERSION,
            "a": [
                {
                    "i": 0,
                    "r": 0,
                    "rc": 0.8,
                    "s": 1,
                    "sc": 0.9,
                    "g": [0],
                },
                {
                    "i": 1,
                    "r": 1,
                    "rc": 0.7,
                    "s": 0,
                    "sc": 0.6,
                    "g": [3],
                },
            ],
        },
        request=request,
        cluster_assignments={"a": _assignment("a"), "b": _assignment("b")},
    )

    assert tuple(parsed) == ("a", "b")
    assert parsed["a"].candidate_id == "a"
    assert parsed["a"].relevance == "answer_relevant"
    assert parsed["a"].expected_gain_signals == ("new_primary",)
    assert parsed["b"].cluster_id == "cluster-b"


def test_compact_parser_normalizes_one_based_candidate_indexes() -> None:
    candidates = (_candidate("a"), _candidate("b"))
    request = build_candidate_assessment_request(candidates, claim=_claim())

    parsed = parse_compact_candidate_assessment_response(
        {
            "v": CANDIDATE_ASSESSMENT_WIRE_SCHEMA_VERSION,
            "a": [
                {
                    "i": 1,
                    "r": 0,
                    "rc": 0.8,
                    "s": 1,
                    "sc": 0.9,
                    "g": [0],
                },
                {
                    "i": 2,
                    "r": 1,
                    "rc": 0.7,
                    "s": 0,
                    "sc": 0.6,
                    "g": [3],
                },
            ],
        },
        request=request,
        cluster_assignments={"a": _assignment("a"), "b": _assignment("b")},
    )

    assert tuple(parsed) == ("a", "b")
    assert parsed["a"].candidate_id == "a"
    assert parsed["b"].candidate_id == "b"


@pytest.mark.parametrize(
    ("field", "value", "error_type"),
    [
        ("r", 99, CompactAssessmentRelevanceCodeError),
        ("s", 99, CompactAssessmentSourceRoleCodeError),
        ("g", [99], CompactAssessmentGainSignalCodeError),
    ],
)
def test_compact_parser_classifies_code_failure_domain(
    field: str,
    value: object,
    error_type: type[CompactAssessmentCodeError],
) -> None:
    candidate = _candidate("a")
    request = build_candidate_assessment_request((candidate,), claim=_claim())
    row = {"i": 0, "r": 0, "rc": 0.8, "s": 1, "sc": 0.9, "g": [0]}
    row[field] = value

    with pytest.raises(error_type):
        parse_compact_candidate_assessment_response(
            {"v": CANDIDATE_ASSESSMENT_WIRE_SCHEMA_VERSION, "a": [row]},
            request=request,
            cluster_assignments={"a": _assignment("a")},
        )


def test_compact_parser_deduplicates_legal_gain_signals_in_order() -> None:
    candidate = _candidate("a")
    request = build_candidate_assessment_request((candidate,), claim=_claim())
    parsed = parse_compact_candidate_assessment_response(
        {
            "v": CANDIDATE_ASSESSMENT_WIRE_SCHEMA_VERSION,
            "a": [
                {
                    "i": 0,
                    "r": 0,
                    "rc": 0.8,
                    "s": 1,
                    "sc": 0.9,
                    "g": [0, 0, 1, 0],
                }
            ],
        },
        request=request,
        cluster_assignments={"a": _assignment("a")},
    )

    assert parsed["a"].expected_gain_signals == (
        "new_primary",
        "new_independent_cluster",
    )


def test_compact_code_subclasses_preserve_fail_closed_base_contract() -> None:
    assert issubclass(CompactAssessmentRelevanceCodeError, CompactAssessmentCodeError)
    assert issubclass(CompactAssessmentSourceRoleCodeError, CompactAssessmentCodeError)
    assert issubclass(CompactAssessmentGainSignalCodeError, CompactAssessmentCodeError)
    assert issubclass(CompactAssessmentGainSignalDuplicateError, CompactAssessmentCodeError)


@pytest.mark.parametrize("indexes", [(1, 0), (0, 0), (0, 2), (0,)])
def test_compact_parser_fails_closed_on_order_or_coverage(indexes: tuple[int, ...]) -> None:
    candidates = (_candidate("a"), _candidate("b"))
    request = build_candidate_assessment_request(candidates, claim=_claim())
    rows = [
        {
            "i": index,
            "r": 1,
            "rc": 0.8,
            "s": 1,
            "sc": 0.9,
            "g": [3],
        }
        for index in indexes
    ]

    with pytest.raises(ValueError):
        parse_compact_candidate_assessment_response(
            {"v": CANDIDATE_ASSESSMENT_WIRE_SCHEMA_VERSION, "a": rows},
            request=request,
            cluster_assignments={"a": _assignment("a"), "b": _assignment("b")},
        )


@pytest.mark.parametrize(
    "mutation",
    ["missing", "extra", "confidence", "cluster", "infinite_cost"],
)
def test_parser_fails_closed_on_untrusted_or_incomplete_output(mutation: str) -> None:
    candidates = (_candidate("a"), _candidate("b"))
    request = build_candidate_assessment_request(candidates, claim=_claim())
    payload = deepcopy(_payload(("a", "b")))
    if mutation == "missing":
        payload["assessments"].pop()
    elif mutation == "extra":
        payload["assessments"][0]["explanation"] = "unbounded"
    elif mutation == "confidence":
        payload["assessments"][0]["relevance_confidence"] = 2.0
    elif mutation == "cluster":
        payload["assessments"][0]["cluster_id"] = "model-invented"
    else:
        pass
    with pytest.raises(ValueError):
        parse_candidate_assessment_response(
            payload,
            request=request,
            cluster_assignments={"a": _assignment("a"), "b": _assignment("b")},
            read_costs={"a": float("inf")} if mutation == "infinite_cost" else None,
        )


class _AssessmentClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.chat = SimpleNamespace(completions=self)
        self.calls: list[dict[str, Any]] = []
        self.fail = fail

    def with_options(self, **kwargs: Any) -> "_AssessmentClient":
        assert kwargs == {"max_retries": 0}
        return self

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.fail:
            raise TimeoutError("slow assessment")
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content='{"v":"ca2","a":[{"i":0,"r":0,"rc":0.8,"s":1,"sc":0.9,"g":[0]}]}'),
                    finish_reason="stop",
                )
            ],
            usage=None,
        )


def _assess(assessor: RuntimeCandidateAssessor, *, attempt_start: int = 1):
    return assessor.assess(
        run_id="run",
        claim=_claim(),
        candidates=(_candidate("a"),),
        assignments={"a": _assignment("a")},
        reference_date="2026-09-05",
        attempt_start=attempt_start,
    )


def test_runtime_assessor_spends_one_physical_attempt_per_invocation() -> None:
    client = _AssessmentClient(fail=True)
    assessor = RuntimeCandidateAssessor(
        ResearchModelGateway(
            client=client,
            model_name="shared",
            max_attempts=2,
            timeout_seconds=20,
        )
    )

    first = _assess(assessor)
    second = _assess(assessor, attempt_start=2)

    assert first.status == second.status == "unavailable"
    assert [audit.attempt for audit in first.audits] == [1]
    assert [audit.attempt for audit in second.audits] == [2]
    assert len(client.calls) == 2
    assert all(call["timeout"] == 15.0 for call in client.calls)
    assert all(call["max_tokens"] == 200 for call in client.calls)


def test_runtime_assessor_accepts_explicit_diagnostic_timeout_cap() -> None:
    client = _AssessmentClient()
    assessor = RuntimeCandidateAssessor(
        ResearchModelGateway(
            client=client,
            model_name="shared",
            max_attempts=2,
            timeout_seconds=120,
        ),
        timeout_cap_seconds=120.0,
    )

    assessor.assess(
        run_id="diagnostic-timeout-cap",
        claim=_claim(),
        candidates=(_candidate("a"),),
        assignments={"a": _assignment("a")},
        reference_date="2026-09-05",
        timeout_seconds=90.0,
    )

    assert client.calls[0]["timeout"] == 90.0


def test_runtime_assessor_caps_two_candidate_window_at_220_tokens() -> None:
    client = _AssessmentClient()
    assessor = RuntimeCandidateAssessor(
        ResearchModelGateway(
            provider_profile="openai",
            client=client,
            model_name="shared",
            max_attempts=2,
            timeout_seconds=20,
        )
    )

    assessor.assess(
        run_id="run-two-candidate-cap",
        claim=_claim(),
        candidates=(_candidate("a"), _candidate("b")),
        assignments={
            "a": _assignment("a"),
            "b": _assignment("b"),
        },
        reference_date="2026-09-05",
        timeout_seconds=15.0,
    )

    assert client.calls[0]["max_tokens"] == 220
    rows_schema = client.calls[0]["response_format"]["json_schema"]["schema"][
        "properties"
    ]["a"]
    assert rows_schema["minItems"] == 2
    assert rows_schema["maxItems"] == 2


def test_dedicated_assessor_endpoint_routes_only_assessment_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dedicated = _AssessmentClient()
    created: list[dict[str, Any]] = []

    def fake_openai(**kwargs: Any) -> _AssessmentClient:
        created.append(kwargs)
        return dedicated

    monkeypatch.setenv("RESEARCH_CANDIDATE_ASSESSOR_BASE_URL", "http://127.0.0.1:8001/v1")
    monkeypatch.setenv("RESEARCH_CANDIDATE_ASSESSOR_MODEL_NAME", "fast-assessor")
    monkeypatch.setenv("RESEARCH_CANDIDATE_ASSESSOR_API_KEY", "local")
    monkeypatch.setattr(active_semantics_module, "OpenAI", fake_openai)
    shared = _AssessmentClient(fail=True)
    assessor = RuntimeCandidateAssessor(
        ResearchModelGateway(
            provider_profile="openai",
            client=shared,
            model_name="shared",
            max_attempts=2,
            timeout_seconds=20,
        )
    )

    result = _assess(assessor)

    assert result.status == "completed"
    assert created == [
        {
            "api_key": "local",
            "base_url": "http://127.0.0.1:8001/v1",
            "max_retries": 0,
        }
    ]
    assert dedicated.calls[0]["model"] == "fast-assessor"
    assert dedicated.calls[0]["timeout"] == 15.0
    assert dedicated.calls[0]["max_tokens"] == 200
    response_format = dedicated.calls[0]["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True
    schema = response_format["json_schema"]["schema"]
    assert set(schema["required"]) == {"v", "a"}
    assert schema["properties"]["v"]["enum"] == [
        CANDIDATE_ASSESSMENT_WIRE_SCHEMA_VERSION
    ]
    assessment_schema = schema["properties"]["a"]["items"]
    assert schema["properties"]["a"]["minItems"] == 1
    assert schema["properties"]["a"]["maxItems"] == 1
    assert assessment_schema["additionalProperties"] is False
    assert set(assessment_schema["required"]) == {
        "i",
        "r",
        "rc",
        "s",
        "sc",
        "g",
    }
    assert assessment_schema["properties"]["r"]["type"] == "integer"
    assert assessment_schema["properties"]["r"]["enum"] == [0, 1, 2, 3]
    assert assessment_schema["properties"]["s"]["enum"] == [0, 1, 2, 3, 4, 5]
    assert assessment_schema["properties"]["g"]["items"]["type"] == "integer"
    assert shared.calls == []


def test_partial_dedicated_assessor_configuration_fails_fast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RESEARCH_CANDIDATE_ASSESSOR_BASE_URL", "http://127.0.0.1:8001/v1")
    monkeypatch.delenv("RESEARCH_CANDIDATE_ASSESSOR_MODEL_NAME", raising=False)
    monkeypatch.delenv("RESEARCH_CANDIDATE_ASSESSOR_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="dedicated candidate assessor requires"):
        RuntimeCandidateAssessor(
            ResearchModelGateway(
                client=_AssessmentClient(),
                model_name="shared",
                max_attempts=2,
                timeout_seconds=20,
            )
        )
