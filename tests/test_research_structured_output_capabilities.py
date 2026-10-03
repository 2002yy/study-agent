"""Provider structured-output capability boundary for bounded research calls.

Locks the DeepSeek compatibility branch introduced after the Live12
qualification probes (2026-09-08):

- DeepSeek rejects wire-level ``response_format: json_schema`` (HTTP 400),
  so research adapters fall back to ``json_object`` and carry the same
  schema as a system-prompt contract.
- DeepSeek thinking defaults to high and can consume the entire bounded
  output budget before any JSON is emitted, so bounded research semantic
  calls explicitly disable thinking via ``extra_body``.
- The strict Python parsers keep final authority in both transports.
- Token budgets (320 planner / 220 assessment / 900 extraction), model-call
  accounting, attempt and timeout gates are frozen and must not change here.
"""

from __future__ import annotations

import json
from copy import deepcopy
from types import SimpleNamespace
from typing import Any

import pytest

from src.llm_client import research_structured_output_capabilities
from src.web.research.active_semantics import (
    _CANDIDATE_ASSESSMENT_RESPONSE_FORMAT,
    _CandidateAssessorCompletions,
    _EXTRACTION_SYSTEM_PROMPT,
    CANDIDATE_ASSESSMENT_BASE_MAX_TOKENS,
    CANDIDATE_ASSESSMENT_MAX_TOKENS_PER_CANDIDATE,
    CANDIDATE_ASSESSMENT_WINDOW_MAX_TOKENS,
    CandidateAssessmentResult,
    RuntimeCandidateAssessor,
    RuntimeEvidenceExtractor,
)
from src.web.research.candidate_pool import CandidatePoolItem
from src.web.research.claim_planner import (
    CLAIM_PLANNER_MAX_TOKENS,
    _CLAIM_PLAN_RESPONSE_FORMAT,
    _ClaimPlannerCompletions,
    RuntimeClaimPlanner,
)
from src.web.research.contracts import (
    EvidenceRequirement,
    ResearchBudget,
    ResearchClaim,
)
from src.web.research.gap_planner import GapSearchIntent
from src.web.research.model_gateway import (
    ResearchModelGateway,
    merge_research_extra_body,
    with_json_object_contract,
)

_THINKING_OFF = {"thinking": {"type": "disabled"}}


class _FakeCompletions:
    def __init__(self, response: Any = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._response = response

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self._response


class _FakeChat:
    def __init__(self, response: Any = None) -> None:
        self.completions = _FakeCompletions(response)


class _FakeClient:
    def __init__(self, response: Any = None) -> None:
        self.chat = _FakeChat(response)

    def with_options(self, **_kwargs: Any) -> "_FakeClient":
        return self


def _ok_response(content: str = '{"ok": true}') -> Any:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content, reasoning_content=None),
                finish_reason="stop",
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=1, completion_tokens=1, total_tokens=2
        ),
    )


def _base_messages() -> list[dict[str, str]]:
    return [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "user payload"},
    ]


def test_capability_lookup_is_key_free_and_profile_scoped() -> None:
    assert research_structured_output_capabilities("deepseek") == (
        "json_object",
        _THINKING_OFF,
    )
    assert research_structured_output_capabilities("openai") == ("json_schema", None)


def test_planner_adapter_deepseek_uses_json_object_with_prompt_contract() -> None:
    chat = _FakeChat()
    adapter = _ClaimPlannerCompletions(chat.completions, provider_profile="deepseek")
    adapter.create(
        messages=_base_messages(),
        response_format={"type": "json_object"},
    )

    call = chat.completions.calls[0]
    # Wire transport must stay json_object; the adapter must not re-enable
    # the unsupported json_schema response_format.
    assert call["response_format"] == {"type": "json_object"}
    # The exact planner schema is carried in the system prompt.
    system_content = call["messages"][0]["content"]
    assert system_content.startswith("system prompt")
    schema_json = _CLAIM_PLAN_RESPONSE_FORMAT["json_schema"]["schema"]
    assert json.dumps(schema_json, ensure_ascii=False, indent=1) in system_content
    # Bounded planner calls must not spend the output budget on thinking.
    assert call["extra_body"] == _THINKING_OFF


def test_planner_adapter_openai_keeps_wire_json_schema() -> None:
    chat = _FakeChat()
    adapter = _ClaimPlannerCompletions(chat.completions, provider_profile="openai")
    messages = _base_messages()
    adapter.create(messages=messages, response_format={"type": "json_object"})

    call = chat.completions.calls[0]
    assert call["response_format"] == _CLAIM_PLAN_RESPONSE_FORMAT
    assert call["response_format"]["json_schema"]["strict"] is True
    # No prompt mutation and no thinking override for capable providers.
    assert call["messages"] == messages
    assert "extra_body" not in call


def test_assessor_adapter_deepseek_pins_dynamic_rows_in_prompt_contract() -> None:
    chat = _FakeChat()
    adapter = _CandidateAssessorCompletions(chat.completions, provider_profile="deepseek")
    user_payload = json.dumps(
        {"candidates": [{"id": "a"}, {"id": "b"}]}, ensure_ascii=False
    )
    adapter.create(
        messages=[
            {"role": "system", "content": "assessor prompt"},
            {"role": "user", "content": user_payload},
        ],
        response_format={"type": "json_object"},
    )

    call = chat.completions.calls[0]
    assert call["response_format"] == {"type": "json_object"}
    system_content = call["messages"][0]["content"]
    assert system_content.startswith("assessor prompt")
    schema = deepcopy(_CANDIDATE_ASSESSMENT_RESPONSE_FORMAT["json_schema"]["schema"])
    rows = schema["properties"]["a"]
    rows["minItems"] = 2
    rows["maxItems"] = 2
    assert json.dumps(schema, ensure_ascii=False, indent=1) in system_content
    assert call["extra_body"] == _THINKING_OFF


def test_planner_adapter_deepseek_rejects_invalid_envelope() -> None:
    adapter = _ClaimPlannerCompletions(
        _FakeCompletions(), provider_profile="deepseek"
    )
    with pytest.raises(ValueError, match="claim planner request messages"):
        adapter.create(messages=[])
    with pytest.raises(ValueError, match="claim planner request messages"):
        adapter.create(messages=["not a mapping envelope"])
    with pytest.raises(ValueError, match="claim planner request messages"):
        adapter.create(messages=None)


def test_assessor_adapter_deepseek_rejects_invalid_envelope() -> None:
    adapter = _CandidateAssessorCompletions(
        _FakeCompletions(), provider_profile="deepseek"
    )
    with pytest.raises(ValueError, match="candidate assessment request envelope"):
        adapter.create(
            messages=[
                {"role": "system", "content": "s"},
                {"role": "user", "content": "not json"},
            ],
        )


def test_gateway_extra_body_passthrough_is_transparent_by_default() -> None:
    gateway = ResearchModelGateway(
        provider_profile="openai",
        client=_FakeClient(_ok_response()),
        model_name="shared-model",
        timeout_seconds=20.0,
        max_attempts=1,
    )
    gateway.complete_structured(
        logical_call_id="call:none",
        purpose="purpose",
        messages=_base_messages(),
        audit_payload={},
        response_schema_version="v1",
        parse=lambda raw: raw,
    )
    call = gateway._client.chat.completions.calls[0]  # noqa: SLF001
    assert "extra_body" not in call

    gateway = ResearchModelGateway(
        provider_profile="openai",
        client=_FakeClient(_ok_response()),
        model_name="shared-model",
        timeout_seconds=20.0,
        max_attempts=1,
    )
    gateway.complete_structured(
        logical_call_id="call:extra",
        purpose="purpose",
        messages=_base_messages(),
        audit_payload={},
        response_schema_version="v1",
        parse=lambda raw: raw,
        extra_body=_THINKING_OFF,
    )
    call = gateway._client.chat.completions.calls[0]  # noqa: SLF001
    assert call["extra_body"] == _THINKING_OFF


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
        text="Official current pull-rate policy",
        kind="factual",
        priority="critical",
        state="searching",
        evidence_requirement=EvidenceRequirement(
            source_roles=("primary",),
            min_independent_sources=1,
            requires_primary_source=True,
            requires_successful_read=True,
            requires_dated_evidence=True,
        ),
    )


def test_evidence_extractor_deepseek_sends_thinking_off_and_keeps_budget() -> None:
    # Garbage response -> parse fails fail-closed; we only assert request shape.
    client = _FakeClient(_ok_response(content="not json"))
    gateway = ResearchModelGateway(
        provider_profile="deepseek",
        client=client,
        model_name="m",
        timeout_seconds=20.0,
        max_attempts=1,
    )
    extractor = RuntimeEvidenceExtractor(gateway)
    result = extractor.extract(
        run_id="run-1",
        claim=_claim(),
        candidate=_candidate("a"),
        source_role="primary",
        source_cluster_id="cluster-a",
        content="bounded page text",
    )
    assert result.status == "unavailable"
    call = client.chat.completions.calls[0]
    assert call["response_format"] == {"type": "json_object"}
    assert call["extra_body"] == _THINKING_OFF
    assert call["max_tokens"] == 900


def test_evidence_extractor_deepseek_carries_output_contract_in_prompt() -> None:
    client = _FakeClient(_ok_response(content="not json"))
    gateway = ResearchModelGateway(
        provider_profile="deepseek",
        client=client,
        model_name="m",
        timeout_seconds=20.0,
        max_attempts=1,
    )
    RuntimeEvidenceExtractor(gateway).extract(
        run_id="run-1",
        claim=_claim(),
        candidate=_candidate("a"),
        source_role="primary",
        source_cluster_id="cluster-a",
        content="bounded page text",
    )
    system_content = client.chat.completions.calls[0]["messages"][0]["content"]
    assert system_content.startswith(_EXTRACTION_SYSTEM_PROMPT)
    assert "Output contract (STRICT" in system_content
    # The exact field set is enumerated and input-envelope keys are excluded.
    assert json.dumps(
        sorted(
            {
                "schema_version",
                "candidate_id",
                "claim_id",
                "source_role",
                "source_cluster_id",
                "relation",
                "strength",
                "locator",
                "anchored_spans",
                "caveats",
                "published_at",
            }
        )
    ) in system_content
    assert "claim_text or page" in system_content


def test_evidence_extractor_openai_prompt_unchanged() -> None:
    client = _FakeClient(_ok_response(content="not json"))
    gateway = ResearchModelGateway(
        provider_profile="openai",
        client=client,
        model_name="m",
        timeout_seconds=20.0,
        max_attempts=1,
    )
    RuntimeEvidenceExtractor(gateway).extract(
        run_id="run-1",
        claim=_claim(),
        candidate=_candidate("a"),
        source_role="primary",
        source_cluster_id="cluster-a",
        content="bounded page text",
    )
    call = client.chat.completions.calls[0]
    assert call["messages"][0]["content"] == _EXTRACTION_SYSTEM_PROMPT
    assert "extra_body" not in call


def test_frozen_research_budgets_unchanged() -> None:
    assert CLAIM_PLANNER_MAX_TOKENS == 320
    assert CANDIDATE_ASSESSMENT_BASE_MAX_TOKENS == 100
    assert CANDIDATE_ASSESSMENT_MAX_TOKENS_PER_CANDIDATE == 100
    assert CANDIDATE_ASSESSMENT_WINDOW_MAX_TOKENS == 220


def test_json_object_contract_helpers() -> None:
    messages = _base_messages()
    contracted = with_json_object_contract(messages, {"type": "object"})
    assert messages[0]["content"] == "system prompt"  # input untouched
    assert contracted[0]["content"].startswith("system prompt")
    assert '"type": "object"' in contracted[0]["content"]
    assert contracted[1] == messages[1]

    with pytest.raises(ValueError, match="leading system message"):
        with_json_object_contract([{"role": "user", "content": "u"}], {})

    assert merge_research_extra_body(None, None) is None
    assert merge_research_extra_body(None, _THINKING_OFF) == _THINKING_OFF
    assert merge_research_extra_body({"a": 1}, _THINKING_OFF) == {
        "thinking": {"type": "disabled"},
        "a": 1,
    }
    assert merge_research_extra_body(_THINKING_OFF, None) == _THINKING_OFF


def test_runtime_assessor_deepseek_pipeline_still_reaches_parser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: deepseek adapter feeds gateway, parser rejects garbage fail-closed."""
    client = _FakeClient(_ok_response(content='{"v": "ca2", "a": []}'))
    shared = ResearchModelGateway(
        provider_profile="deepseek",
        client=client,
        model_name="m",
        timeout_seconds=20.0,
        max_attempts=1,
    )
    assessor = RuntimeCandidateAssessor(shared)
    result = assessor.assess(
        run_id="run-1",
        claim=_claim(),
        candidates=(_candidate("a"),),
        assignments={},
        reference_date="2026-09-08",
    )
    assert isinstance(result, CandidateAssessmentResult)
    assert result.status == "unavailable"
    call = client.chat.completions.calls[0]
    assert call["response_format"] == {"type": "json_object"}
    assert call["extra_body"] == _THINKING_OFF
    assert "minItems" in call["messages"][0]["content"]


def _budget() -> ResearchBudget:
    # Mirrors the frozen 6+2 / 45/60s research budget shape.
    return ResearchBudget(
        max_candidates=6,
        max_reads=6,
        soft_timeout_seconds=45.0,
        hard_timeout_seconds=60.0,
    )


def test_runtime_planner_deepseek_pipeline_still_reaches_parser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient(_ok_response(content="garbage"))
    shared = ResearchModelGateway(
        provider_profile="deepseek",
        client=client,
        model_name="m",
        timeout_seconds=20.0,
        max_attempts=1,
    )
    planner = RuntimeClaimPlanner(shared)
    result = planner.plan(
        run_id="run-1",
        question="What pull-rate limits apply on Docker Hub?",
        reference_date="2026-09-08",
        budget=_budget(),
    )
    assert result.status == "unavailable"
    assert result.audits  # fail-closed with a recorded audit trail
    call = client.chat.completions.calls[0]
    assert call["response_format"] == {"type": "json_object"}
    assert call["extra_body"] == _THINKING_OFF
    assert call["max_tokens"] == 320


def test_runtime_planner_openai_pipeline_keeps_json_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient(_ok_response(content="garbage"))
    shared = ResearchModelGateway(
        provider_profile="openai",
        client=client,
        model_name="m",
        timeout_seconds=20.0,
        max_attempts=1,
    )
    planner = RuntimeClaimPlanner(shared)
    result = planner.plan(
        run_id="run-1",
        question="What pull-rate limits apply on Docker Hub?",
        reference_date="2026-09-08",
        budget=_budget(),
    )
    assert result.status == "unavailable"
    call = client.chat.completions.calls[0]
    assert call["response_format"] == _CLAIM_PLAN_RESPONSE_FORMAT
    assert "extra_body" not in call
