from __future__ import annotations

from types import SimpleNamespace

import tools.rq1c_qualification_guardrails as guardrails
from src.web.research.model_gateway import ResearchModelGateway


class _FakeCompletions:
    def __init__(self) -> None:
        self.calls = 0

    def create(self, **kwargs: object) -> object:
        self.calls += 1
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content='{"ok": true}'),
                    finish_reason="stop",
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=1,
                completion_tokens=1,
                total_tokens=2,
            ),
        )


class _FakeClient:
    def __init__(self) -> None:
        self.completions = _FakeCompletions()
        self.chat = SimpleNamespace(completions=self.completions)

    def with_options(self, **kwargs: object) -> _FakeClient:
        return self


def _gateway(client: _FakeClient, *, max_attempts: int) -> ResearchModelGateway:
    return ResearchModelGateway(
        client=client,
        model_name="rq1c-test-model",
        timeout_seconds=5.0,
        max_attempts=max_attempts,
    )


def _call(gateway: ResearchModelGateway, index: int):
    return gateway.complete_structured(
        logical_call_id=f"logical:{index}",
        purpose="test",
        messages=[{"role": "user", "content": "test"}],
        audit_payload={"index": index},
        response_schema_version="test-v1",
        parse=lambda raw: raw,
        max_tokens=20,
        attempt_start=1,
    )


def test_reservation_caps_research_before_answer_capacity(monkeypatch) -> None:
    client = _FakeClient()
    gateway = _gateway(client, max_attempts=1)
    original = ResearchModelGateway.complete_structured
    monkeypatch.setattr(guardrails, "MAX_RESEARCH_MODEL_CALLS", 2)

    with guardrails._reserve_answer_model_capacity():
        assert _call(gateway, 1).completed
        assert _call(gateway, 2).completed
        blocked = _call(gateway, 3)
        assert blocked.status == "unavailable"
        assert blocked.reason == "qualification_research_model_budget_exhausted"
        assert blocked.audits == ()

    assert client.completions.calls == 2
    assert ResearchModelGateway.complete_structured is original


def test_reservation_bounds_retry_to_remaining_physical_capacity(monkeypatch) -> None:
    client = _FakeClient()
    gateway = _gateway(client, max_attempts=2)
    monkeypatch.setattr(guardrails, "MAX_RESEARCH_MODEL_CALLS", 1)

    with guardrails._reserve_answer_model_capacity():
        result = gateway.complete_structured(
            logical_call_id="logical:retry",
            purpose="test",
            messages=[{"role": "user", "content": "test"}],
            audit_payload={"kind": "retry"},
            response_schema_version="test-v1",
            parse=lambda raw: (_ for _ in ()).throw(ValueError("reject")),
            max_tokens=20,
            attempt_start=1,
        )

    assert result.status == "unavailable"
    assert len(result.audits) == 1
    assert client.completions.calls == 1
