from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

import src.web.research.claim_planner as claim_planner_module
from src.web.research.claim_planner import (
    CLAIM_PLANNER_MAX_ATTEMPTS_PER_INVOCATION,
    CLAIM_PLANNER_MAX_TOKENS,
    RuntimeClaimPlanner,
)
from src.web.research.contracts import ResearchBudget
from src.web.research.model_gateway import ResearchModelGateway
from src.web.research.policy import evidence_policy_for_claim


class _StructuredClient:
    def __init__(self, content: str) -> None:
        self.chat = SimpleNamespace(completions=self)
        self.content = content
        self.calls: list[dict[str, Any]] = []

    def with_options(self, **kwargs: Any) -> _StructuredClient:
        assert kwargs == {"max_retries": 0}
        return self

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=self.content),
                    finish_reason="stop",
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=20,
                completion_tokens=30,
                total_tokens=50,
            ),
        )


class _FailIfCalledClient(_StructuredClient):
    def create(self, **kwargs: Any) -> Any:
        raise AssertionError(f"shared client must not be called: {kwargs}")


def _budget() -> ResearchBudget:
    return ResearchBudget(
        max_candidates=20,
        max_reads=8,
        soft_timeout_seconds=45,
        hard_timeout_seconds=60,
        max_total_chars=16000,
    )


def _plan_payload(
    *,
    critical_anchor: str = "verified current release date",
    critical_kind: str = "factual",
    critical_profile: str = "current_fact",
    supporting: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "research-runtime-claim-plan-v1",
        "critical_claim": {
            "question_anchor": critical_anchor,
            "kind": critical_kind,
            "policy_profile": critical_profile,
        },
        "supporting_claims": supporting or [],
    }


def _valid_plan(*, fenced: bool = False) -> str:
    payload = json.dumps(_plan_payload())
    if fenced:
        return f"```json\n{payload}\n```"
    return payload


def _plan(planner: RuntimeClaimPlanner, *, attempt_start: int = 1) -> Any:
    return planner.plan(
        run_id="run_claim_planner_budget",
        question="What is the verified current release date?",
        reference_date="2026-09-05",
        budget=_budget(),
        mode="active",
        timeout_seconds=20,
        attempt_start=attempt_start,
    )


def test_planner_has_small_anchored_schema_and_does_not_mutate_shared_retry_budget() -> None:
    client = _StructuredClient(_valid_plan(fenced=True))
    shared = ResearchModelGateway(
        client=client,
        model_name="shared-model",
        timeout_seconds=20,
    )

    planner = RuntimeClaimPlanner(shared)
    result = _plan(planner)

    assert result.completed
    assert len(client.calls) == 1
    assert client.calls[0]["max_tokens"] == CLAIM_PLANNER_MAX_TOKENS == 320
    response_format = client.calls[0]["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True
    schema = response_format["json_schema"]["schema"]
    assert schema["additionalProperties"] is False
    assert schema["required"] == [
        "schema_version",
        "critical_claim",
        "supporting_claims",
    ]
    critical_branches = schema["properties"]["critical_claim"]["anyOf"]
    assert all("priority" not in branch["properties"] for branch in critical_branches)
    assert all("question_anchor" in branch["properties"] for branch in critical_branches)
    assert planner.model_gateway.max_attempts == CLAIM_PLANNER_MAX_ATTEMPTS_PER_INVOCATION == 1
    assert shared.max_attempts == 2

    assert result.state is not None
    assert len(result.state.claims) == 1
    assert result.state.claims[0].text == "verified current release date"
    assert result.state.claims[0].priority == "critical"


def test_planner_schema_policy_pairs_match_code_owned_policy_validation() -> None:
    schema = claim_planner_module._CLAIM_PLAN_RESPONSE_FORMAT["json_schema"]["schema"]
    branches = schema["properties"]["critical_claim"]["anyOf"]
    schema_pairs = {
        (branch["properties"]["kind"]["enum"][0], profile)
        for branch in branches
        for profile in branch["properties"]["policy_profile"]["enum"]
    }

    accepted_pairs: set[tuple[str, str]] = set()
    for kind in claim_planner_module._CLAIM_KINDS:
        for profile in claim_planner_module._POLICY_PROFILES:
            try:
                evidence_policy_for_claim(
                    kind=kind,  # type: ignore[arg-type]
                    priority="critical",
                    profile=profile,  # type: ignore[arg-type]
                )
            except ValueError:
                continue
            accepted_pairs.add((kind, profile))

    assert schema_pairs == accepted_pairs


def test_planner_position_assigns_critical_and_major_priorities() -> None:
    client = _StructuredClient(
        json.dumps(
            _plan_payload(
                supporting=[
                    {
                        "question_anchor": "release date",
                        "kind": "factual",
                        "policy_profile": "official_statement",
                    }
                ]
            )
        )
    )

    result = _plan(
        RuntimeClaimPlanner(
            ResearchModelGateway(
                client=client,
                model_name="shared-model",
                timeout_seconds=20,
            )
        )
    )

    assert result.completed
    assert result.state is not None
    assert {(claim.text, claim.priority) for claim in result.state.claims} == {
        ("verified current release date", "critical"),
        ("release date", "major"),
    }


def test_planner_rejects_anchor_not_copied_from_question_without_fabricated_claim() -> None:
    client = _StructuredClient(
        json.dumps(_plan_payload(critical_anchor="Python 3.11.0 is the current release"))
    )

    result = _plan(
        RuntimeClaimPlanner(
            ResearchModelGateway(
                client=client,
                model_name="shared-model",
                timeout_seconds=20,
            )
        )
    )

    assert result.status == "unavailable"
    assert result.state is None
    assert len(result.audits) == 1
    assert result.audits[0].status == "attempt_failed"
    assert result.audits[0].error_type == "ValueError"
    assert len(client.calls) == 1


def test_planner_rejects_duplicate_question_anchors() -> None:
    client = _StructuredClient(
        json.dumps(
            _plan_payload(
                supporting=[
                    {
                        "question_anchor": "verified current release date",
                        "kind": "factual",
                        "policy_profile": "official_statement",
                    }
                ]
            )
        )
    )

    result = _plan(
        RuntimeClaimPlanner(
            ResearchModelGateway(
                client=client,
                model_name="shared-model",
                timeout_seconds=20,
            )
        )
    )

    assert result.status == "unavailable"
    assert result.state is None
    assert len(result.audits) == 1
    assert result.audits[0].error_type == "ValueError"
    assert len(client.calls) == 1


def test_planner_rejects_kind_policy_mismatch_even_if_json_shape_is_valid() -> None:
    client = _StructuredClient(
        json.dumps(
            _plan_payload(
                critical_kind="analytical",
                critical_profile="current_fact",
            )
        )
    )

    result = _plan(
        RuntimeClaimPlanner(
            ResearchModelGateway(
                client=client,
                model_name="shared-model",
                timeout_seconds=20,
            )
        )
    )

    assert result.status == "unavailable"
    assert result.state is None
    assert len(result.audits) == 1
    assert result.audits[0].error_type == "ValueError"
    assert len(client.calls) == 1


def test_planner_parse_failure_is_unavailable_without_immediate_retry_or_fabricated_claim() -> None:
    client = _StructuredClient("not-json")
    shared = ResearchModelGateway(
        client=client,
        model_name="shared-model",
        timeout_seconds=20,
    )

    result = _plan(RuntimeClaimPlanner(shared))

    assert result.status == "unavailable"
    assert result.state is None
    assert len(result.audits) == 1
    assert result.audits[0].status == "attempt_failed"
    assert result.audits[0].error_type == "JSONDecodeError"
    assert len(client.calls) == 1


def test_planner_durable_recovery_attempt_two_spends_exactly_one_model_call() -> None:
    client = _StructuredClient(_valid_plan())
    planner = RuntimeClaimPlanner(
        ResearchModelGateway(
            client=client,
            model_name="shared-model",
            timeout_seconds=20,
        )
    )

    result = _plan(planner, attempt_start=2)

    assert result.completed
    assert len(result.audits) == 1
    assert result.audits[0].attempt == 2
    assert len(client.calls) == 1


def test_planner_attempt_beyond_shared_durable_budget_fails_closed_without_call() -> None:
    client = _StructuredClient(_valid_plan())
    planner = RuntimeClaimPlanner(
        ResearchModelGateway(
            client=client,
            model_name="shared-model",
            timeout_seconds=20,
        )
    )

    result = _plan(planner, attempt_start=3)

    assert result.status == "unavailable"
    assert result.reason == "claim_plan_attempts_exhausted"
    assert result.state is None
    assert result.audits == ()
    assert client.calls == []


def test_shared_lazy_client_is_resolved_only_when_planner_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lazy_client = _StructuredClient(_valid_plan())
    resolutions: list[str] = []

    def fake_get_client(*, provider_profile: str) -> _StructuredClient:
        resolutions.append(provider_profile)
        return lazy_client

    monkeypatch.setattr(claim_planner_module, "get_client", fake_get_client)
    shared = ResearchModelGateway(
        provider_profile="openai",
        client=None,
        model_name="shared-model",
        timeout_seconds=20,
    )

    planner = RuntimeClaimPlanner(shared)
    assert resolutions == []

    result = _plan(planner)

    assert result.completed
    assert resolutions == ["openai"]
    assert len(lazy_client.calls) == 1
    assert lazy_client.calls[0]["response_format"]["type"] == "json_schema"
    assert shared._client is None  # noqa: SLF001


def test_dedicated_planner_endpoint_routes_only_planner_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dedicated = _StructuredClient(_valid_plan())
    created: list[dict[str, Any]] = []

    def fake_openai(**kwargs: Any) -> _StructuredClient:
        created.append(kwargs)
        return dedicated

    monkeypatch.setenv("RESEARCH_CLAIM_PLANNER_BASE_URL", "http://127.0.0.1:8001/v1")
    monkeypatch.setenv("RESEARCH_CLAIM_PLANNER_MODEL_NAME", "fast-planner")
    monkeypatch.setenv("RESEARCH_CLAIM_PLANNER_API_KEY", "local")
    monkeypatch.setattr(claim_planner_module, "OpenAI", fake_openai)

    shared_client = _FailIfCalledClient(_valid_plan())
    shared = ResearchModelGateway(
        client=shared_client,
        model_name="shared-4b",
        timeout_seconds=20,
    )
    planner = RuntimeClaimPlanner(shared)

    result = _plan(planner)

    assert result.completed
    assert created == [
        {
            "api_key": "local",
            "base_url": "http://127.0.0.1:8001/v1",
            "max_retries": 0,
        }
    ]
    assert len(dedicated.calls) == 1
    assert dedicated.calls[0]["model"] == "fast-planner"
    assert dedicated.calls[0]["response_format"]["type"] == "json_schema"
    assert shared_client.calls == []
    assert shared.max_attempts == 2


def test_partial_dedicated_planner_configuration_fails_fast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RESEARCH_CLAIM_PLANNER_BASE_URL", "http://127.0.0.1:8001/v1")
    monkeypatch.delenv("RESEARCH_CLAIM_PLANNER_MODEL_NAME", raising=False)
    monkeypatch.delenv("RESEARCH_CLAIM_PLANNER_API_KEY", raising=False)

    shared = ResearchModelGateway(
        client=_StructuredClient(_valid_plan()),
        model_name="shared-model",
        timeout_seconds=20,
    )

    with pytest.raises(RuntimeError, match="dedicated claim planner requires"):
        RuntimeClaimPlanner(shared)
