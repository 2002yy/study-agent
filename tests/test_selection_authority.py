"""§38b selection authority: rules by default, model only when flagged."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.web.research.selection_authority import (
    SELECTION_AUTHORITY_ENV,
    parse_selection_response,
    select_candidates_with_model,
    selection_authority_mode,
)

NODE_TARGET = "https://nodejs.cn/api/modules.html"
HOME = "https://nodejs.org/"


@dataclass
class _Result:
    status: str
    value: object
    reason: str = ""
    audits: tuple = ()


@dataclass
class _FakeGateway:
    result: _Result

    def complete_structured(self, **kwargs):
        _FakeGateway.last_kwargs = kwargs
        return self.result


@dataclass
class _Candidate:
    canonical_url: str
    title: str = "Title"
    snippet: str = "Snippet"


def test_mode_flag_defaults_to_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(SELECTION_AUTHORITY_ENV, raising=False)
    assert selection_authority_mode() == "rules"
    monkeypatch.setenv(SELECTION_AUTHORITY_ENV, "model")
    assert selection_authority_mode() == "model"
    monkeypatch.setenv(SELECTION_AUTHORITY_ENV, "MODEL ")
    assert selection_authority_mode() == "model"
    monkeypatch.setenv(SELECTION_AUTHORITY_ENV, "anything-else")
    assert selection_authority_mode() == "rules"


def test_parser_is_strict() -> None:
    with pytest.raises(ValueError):
        parse_selection_response([])
    with pytest.raises(ValueError):
        parse_selection_response({"urls": "not-a-list"})
    assert parse_selection_response({"urls": [HOME]}) == [HOME]


def test_model_picks_are_filtered_to_candidates_and_bounded() -> None:
    candidates = [_Candidate(HOME), _Candidate(NODE_TARGET)]
    gateway = _FakeGateway(
        _Result(
            status="completed",
            value=[NODE_TARGET, "https://invented.example/", HOME, NODE_TARGET],
        )
    )
    picks, diagnostics = select_candidates_with_model(
        model_gateway=gateway,
        claim_text="Which module systems?",
        candidates=candidates,
        max_picks=2,
        timeout_seconds=5.0,
        logical_call_id="test:1",
    )
    assert picks == [NODE_TARGET, HOME]
    assert diagnostics.input_set == [HOME, NODE_TARGET]
    assert diagnostics.output_urls == [NODE_TARGET, HOME]
    assert diagnostics.output_count == 2
    assert diagnostics.fallback is False
    assert diagnostics.status == "completed"


def test_unavailable_call_returns_empty_with_diagnostics() -> None:
    gateway = _FakeGateway(
        _Result(status="unavailable", value=None, reason="model_call_attempts_exhausted")
    )
    picks, diagnostics = select_candidates_with_model(
        model_gateway=gateway,
        claim_text="q",
        candidates=[_Candidate(HOME)],
        max_picks=2,
        timeout_seconds=5.0,
        logical_call_id="test:2",
    )
    assert picks == []
    assert diagnostics.status == "unavailable"
    assert diagnostics.reason == "model_call_attempts_exhausted"


def test_exception_is_recorded_not_raised() -> None:
    class _Boom:
        def complete_structured(self, **kwargs):
            raise RuntimeError("gateway exploded")

    picks, diagnostics = select_candidates_with_model(
        model_gateway=_Boom(),
        claim_text="q",
        candidates=[_Candidate(HOME)],
        max_picks=2,
        timeout_seconds=5.0,
        logical_call_id="test:3",
    )
    assert picks == []
    assert diagnostics.status == "exception"
    assert diagnostics.reason == "RuntimeError"


def test_input_set_is_bounded() -> None:
    candidates = [_Candidate(f"https://example.com/{index}") for index in range(30)]
    gateway = _FakeGateway(_Result(status="completed", value=[]))
    _, diagnostics = select_candidates_with_model(
        model_gateway=gateway,
        claim_text="q",
        candidates=candidates,
        max_picks=2,
        timeout_seconds=5.0,
        logical_call_id="test:4",
        input_max=5,
    )
    assert diagnostics.input_size == 5
    assert len(diagnostics.input_set) == 5


def test_runtime_default_path_never_calls_the_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.application.active_research_runtime import _select_assessment_window
    from src.web.research.candidate_pool import CandidatePoolItem
    from src.web.research.contracts import EvidenceRequirement, ResearchClaim

    monkeypatch.delenv(SELECTION_AUTHORITY_ENV, raising=False)

    class _ExplodingGateway:
        def complete_structured(self, **kwargs):  # pragma: no cover - must not run
            raise AssertionError("model must not be called on the rules path")

    claim = ResearchClaim(
        id="claim_1",
        question_id="question_1",
        text="Which module systems?",
        kind="factual",
        priority="critical",
        state="pending",
        evidence_requirement=EvidenceRequirement(),
    )
    candidates = tuple(
        CandidatePoolItem(
            id=f"candidate_{index}",
            canonical_url=f"https://example.com/{index}",
            url=f"https://example.com/{index}",
            title="Title",
            snippet="Snippet",
            source="",
            published_at="",
            query_ids=("q1",),
            intents=(),
            providers=(),
            first_seen_rank=index,
        )
        for index in range(3)
    )
    context: dict = {}
    selected = _select_assessment_window(
        candidates,
        claim=claim,
        assignments={},
        max_reads=2,
        excluded_candidate_ids=frozenset(),
        trace=None,
        context=context,
        model_gateway=_ExplodingGateway(),
        run_id="run_1",
        wave_index=1,
        timeout_seconds=5.0,
    )
    assert len(selected) == 2
    assert "selection_authority" not in context.get("claim_engine_metrics", {})
