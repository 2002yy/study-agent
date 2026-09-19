"""§42 selector production contract: model preference, legacy availability.

The contract: exactly one model call per window; usable is mechanical (schema,
pool membership, no forbidden URL, no duplicates, 1..K); anything else reruns
the deterministic legacy window on the SAME original pool. The model can raise
quality but can never reduce availability.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.web.research.selection_authority import (
    SELECTION_AUTHORITY_ENV,
    SelectionAuthorityDiagnostics,
    parse_selection_response,
    select_candidates_with_model,
    selection_authority_mode,
)

TARGET = "https://nodejs.cn/api/modules.html"
HOME = "https://nodejs.org/"


@dataclass
class _Result:
    status: str
    value: object
    reason: str = ""
    audits: tuple = ()


@dataclass
class _Audit:
    error_type: str = ""


@dataclass
class _FakeGateway:
    result: _Result

    def complete_structured(self, **kwargs):
        _FakeGateway.last_kwargs = kwargs
        _FakeGateway.calls = getattr(_FakeGateway, "calls", 0) + 1
        return self.result


@dataclass
class _Candidate:
    canonical_url: str
    title: str = "Title"
    snippet: str = "Snippet"

def _candidates() -> list[_Candidate]:
    return [_Candidate(HOME), _Candidate(TARGET)]


def _select(gateway: _FakeGateway, **overrides) -> tuple[list[str], SelectionAuthorityDiagnostics]:
    params = {
        "model_gateway": gateway,
        "claim_text": "Which module systems?",
        "candidates": _candidates(),
        "max_picks": 2,
        "timeout_seconds": 5.0,
        "logical_call_id": "test:1",
        "model_name": "deepseek-flash",
    }
    params.update(overrides)
    return select_candidates_with_model(**params)


def test_mode_flag_defaults_to_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(SELECTION_AUTHORITY_ENV, raising=False)
    assert selection_authority_mode() == "rules"
    monkeypatch.setenv(SELECTION_AUTHORITY_ENV, "model")
    assert selection_authority_mode() == "model"


def test_parser_requires_string_urls() -> None:
    with pytest.raises(ValueError):
        parse_selection_response({"urls": [1, 2]})
    with pytest.raises(ValueError):
        parse_selection_response(["not-a-string", 5])
    assert parse_selection_response({"urls": [HOME]}) == [HOME]


def test_parser_accepts_an_unambiguous_top_level_url_array() -> None:
    assert parse_selection_response([HOME, TARGET]) == [HOME, TARGET]
    assert parse_selection_response([]) == []


def test_selector_call_disables_provider_thinking_for_json_object_providers() -> None:
    _FakeGateway.last_kwargs = None
    gateway = _FakeGateway(_Result(status="completed", value=[HOME]))
    gateway.provider_profile = "deepseek"  # type: ignore[attr-defined]
    _select(gateway)
    assert _FakeGateway.last_kwargs is not None
    assert _FakeGateway.last_kwargs.get("extra_body") == {
        "thinking": {"type": "disabled"}
    }


def test_1_valid_two_picks_are_usable() -> None:
    picks, diagnostics = _select(
        _FakeGateway(_Result(status="completed", value=[TARGET, HOME]))
    )
    assert diagnostics.usable is True
    assert picks == [TARGET, HOME]
    assert diagnostics.selection_source == ""  # the caller sets the source
    assert diagnostics.raw_pick_count == 2
    assert diagnostics.valid_pick_count == 2
    assert diagnostics.unusable_reason == ""


def test_2_empty_list_is_unusable_empty() -> None:
    picks, diagnostics = _select(_FakeGateway(_Result(status="completed", value=[])))
    assert picks == []
    assert diagnostics.usable is False
    assert diagnostics.unusable_reason == "empty"


def test_3_call_unavailable_is_unusable() -> None:
    picks, diagnostics = _select(
        _FakeGateway(
            _Result(
                status="unavailable",
                value=None,
                reason="model_call_attempts_exhausted",
                audits=(_Audit(error_type="APITimeoutError"),),
            )
        )
    )
    assert picks == []
    assert diagnostics.unusable_reason == "call_unavailable"
    assert diagnostics.call_status == "unavailable"


def test_3b_schema_failure_is_distinguished_from_transport() -> None:
    picks, diagnostics = _select(
        _FakeGateway(
            _Result(
                status="unavailable",
                value=None,
                audits=(_Audit(error_type="ValueError"),),
            )
        )
    )
    assert picks == []
    assert diagnostics.unusable_reason == "invalid_schema"


def test_4_out_of_pool_url_is_unusable() -> None:
    picks, diagnostics = _select(
        _FakeGateway(
            _Result(status="completed", value=[HOME, "https://invented.example/"])
        )
    )
    assert picks == []
    assert diagnostics.unusable_reason == "unknown_url"


def test_5_over_k_is_unusable_without_truncation() -> None:
    three = _candidates() + [_Candidate("https://extra.example/")]
    picks, diagnostics = _select(
        _FakeGateway(
            _Result(status="completed", value=[HOME, TARGET, "https://extra.example/"])
        ),
        candidates=three,
    )
    assert picks == []
    assert diagnostics.unusable_reason == "over_k"


def test_6_duplicates_are_unusable() -> None:
    picks, diagnostics = _select(
        _FakeGateway(_Result(status="completed", value=[TARGET, TARGET]))
    )
    assert picks == []
    assert diagnostics.unusable_reason == "duplicate_only"


def test_forbidden_candidate_is_a_policy_violation() -> None:
    picks, diagnostics = _select(
        _FakeGateway(_Result(status="completed", value=[TARGET])),
        forbidden_urls=frozenset({TARGET}),
    )
    assert picks == []
    assert diagnostics.unusable_reason == "policy_violation"


def test_exception_is_unusable_not_raised() -> None:
    class _Boom:
        def complete_structured(self, **kwargs):
            raise RuntimeError("gateway exploded")

    picks, diagnostics = _select(_Boom())
    assert picks == []
    assert diagnostics.call_status == "exception"
    assert diagnostics.unusable_reason == "call_unavailable"


def test_one_logical_call_per_window() -> None:
    _FakeGateway.calls = 0
    _select(_FakeGateway(_Result(status="completed", value=[HOME])))
    assert _FakeGateway.calls == 1


def test_diagnostics_contract_fields_are_all_present() -> None:
    payload = SelectionAuthorityDiagnostics().to_dict()
    assert set(payload) == {
        "enabled",
        "authority",
        "model",
        "call_status",
        "elapsed_ms",
        "raw_pick_count",
        "valid_pick_count",
        "usable",
        "unusable_reason",
        "model_picks",
        "fallback_invoked",
        "fallback_picks",
        "final_picks",
        "selection_source",
        "input_size",
        "input_set",
    }
    assert payload["authority"] == "model_preference_with_legacy_fallback"


# ---------------------------------------------------------------------------
# §42 runtime contract: original-pool fallback and availability invariant.
# ---------------------------------------------------------------------------


def _runtime_candidates():
    from src.web.research.candidate_pool import CandidatePoolItem

    return tuple(
        CandidatePoolItem(
            id=f"candidate_{index}",
            canonical_url=f"https://example.com/{index}",
            url=f"https://example.com/{index}",
            title=f"Title {index}",
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


def _runtime_claim():
    from src.web.research.contracts import EvidenceRequirement, ResearchClaim

    return ResearchClaim(
        id="claim_1",
        question_id="question_1",
        text="Which module systems?",
        kind="factual",
        priority="critical",
        state="pending",
        evidence_requirement=EvidenceRequirement(),
    )


class _ExplodingGateway:
    def complete_structured(self, **kwargs):  # pragma: no cover - must not run
        raise AssertionError("model must not be called on the rules path")


def test_runtime_default_path_never_calls_the_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.application.active_research_runtime import _select_assessment_window

    monkeypatch.delenv(SELECTION_AUTHORITY_ENV, raising=False)
    context: dict = {}
    selected = _select_assessment_window(
        _runtime_candidates(),
        claim=_runtime_claim(),
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


def test_runtime_fallback_reruns_the_legacy_window_on_the_original_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.application.active_research_runtime import (
        _bounded_assessment_candidates,
        _select_assessment_window,
    )

    monkeypatch.setenv(SELECTION_AUTHORITY_ENV, "model")
    candidates = _runtime_candidates()
    claim = _runtime_claim()
    legacy = _bounded_assessment_candidates(
        candidates, assignments={}, max_reads=2, excluded_candidate_ids=frozenset()
    )

    class _EmptyModel:
        def complete_structured(self, **kwargs):
            return _Result(status="completed", value=[])

    context: dict = {}
    selected = _select_assessment_window(
        candidates,
        claim=claim,
        assignments={},
        max_reads=2,
        excluded_candidate_ids=frozenset(),
        trace=None,
        context=context,
        model_gateway=_EmptyModel(),
        run_id="run_1",
        wave_index=1,
        timeout_seconds=5.0,
    )
    assert [item.id for item in selected] == [item.id for item in legacy]

    record = context["claim_engine_metrics"]["selection_authority"][-1]
    assert record["usable"] is False
    assert record["unusable_reason"] == "empty"
    assert record["fallback_invoked"] is True
    assert record["selection_source"] == "legacy_fallback"
    assert record["fallback_picks"] == record["final_picks"]
    assert record["final_picks"]
    assert context["claim_engine_metrics"]["orchestration_model_calls"] == 1


def test_runtime_model_path_uses_model_picks_and_counts_orchestration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.application.active_research_runtime import _select_assessment_window

    monkeypatch.setenv(SELECTION_AUTHORITY_ENV, "model")
    candidates = _runtime_candidates()
    target_url = candidates[2].canonical_url

    class _Model:
        def complete_structured(self, **kwargs):
            return _Result(status="completed", value=[target_url])

    context: dict = {}
    selected = _select_assessment_window(
        candidates,
        claim=_runtime_claim(),
        assignments={},
        max_reads=2,
        excluded_candidate_ids=frozenset(),
        trace=None,
        context=context,
        model_gateway=_Model(),
        run_id="run_1",
        wave_index=1,
        timeout_seconds=5.0,
    )
    assert [item.id for item in selected] == [candidates[2].id]
    record = context["claim_engine_metrics"]["selection_authority"][-1]
    assert record["selection_source"] == "model"
    assert record["usable"] is True
    assert record["model_picks"] == [target_url]
    assert record["fallback_invoked"] is False
    assert context["claim_engine_metrics"]["orchestration_model_calls"] == 1


def test_runtime_unavailable_model_can_never_empty_the_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.application.active_research_runtime import _select_assessment_window

    monkeypatch.setenv(SELECTION_AUTHORITY_ENV, "model")

    class _Unavailable:
        def complete_structured(self, **kwargs):
            return _Result(
                status="unavailable",
                value=None,
                audits=(_Audit(error_type="APITimeoutError"),),
            )

    context: dict = {}
    selected = _select_assessment_window(
        _runtime_candidates(),
        claim=_runtime_claim(),
        assignments={},
        max_reads=2,
        excluded_candidate_ids=frozenset(),
        trace=None,
        context=context,
        model_gateway=_Unavailable(),
        run_id="run_1",
        wave_index=1,
        timeout_seconds=5.0,
    )
    assert len(selected) == 2  # legacy availability preserved
    record = context["claim_engine_metrics"]["selection_authority"][-1]
    assert record["unusable_reason"] == "call_unavailable"
    assert record["selection_source"] == "legacy_fallback"
    assert record["fallback_picks"]
