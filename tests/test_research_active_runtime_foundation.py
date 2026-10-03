from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.application.active_research_runtime import (
    _ExternalAttemptBudgetExhausted,
    _attempt_number,
    _model_attempt_start,
)
from src.web.research.claim_planner import (
    CLAIM_PLANNER_MAX_TOKENS,
    RUNTIME_CLAIM_PLAN_SCHEMA_VERSION,
    RuntimeClaimPlanner,
)
from src.web.research.contracts import ResearchBudget
from src.web.research.evidence_gain import EvidenceGainResult
from src.web.research.model_gateway import (
    ResearchModelAttemptStart,
    ResearchModelCallAudit,
    ResearchModelGateway,
)
from src.web.research.runtime import (
    CLAIM_ENGINE_RUNTIME_CONTEXT_KEY,
    RESEARCH_RUNTIME_SCHEMA_VERSION_V1,
    ResearchRuntimeCursor,
    RuntimeCandidate,
    RuntimeExternalPurpose,
    RuntimeExternalAttemptStart,
    RuntimePhase,
    RuntimePlannedQuery,
    RuntimeQueryOutcome,
    attach_runtime_cursor,
    begin_external_attempt,
    begin_model_attempt,
    finish_model_attempt,
    load_runtime_cursor,
    recover_interrupted_model_attempt,
    recover_interrupted_external_attempt,
)


class _FakeClient:
    def __init__(self, outcomes: list[Any]) -> None:
        self.outcomes = list(outcomes)
        self.with_options_calls: list[dict[str, Any]] = []
        self.create_calls: list[dict[str, Any]] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def with_options(self, **kwargs: Any) -> "_FakeClient":
        self.with_options_calls.append(dict(kwargs))
        return self

    def _create(self, **kwargs: Any) -> Any:
        self.create_calls.append(dict(kwargs))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _response(
    content: str,
    *,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
) -> Any:
    total_tokens = (
        None
        if prompt_tokens is None or completion_tokens is None
        else prompt_tokens + completion_tokens
    )
    usage = (
        None
        if total_tokens is None
        else SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
    )
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content),
                finish_reason="stop",
            )
        ],
        usage=usage,
    )


def _gateway(outcomes: list[Any]) -> tuple[ResearchModelGateway, _FakeClient]:
    client = _FakeClient(outcomes)
    gateway = ResearchModelGateway(
        provider_profile="openai",
        model_profile="flash",
        model_name="test-model",
        client=client,
        timeout_seconds=9.0,
        max_attempts=2,
        now=lambda: "2026-08-27T12:00:00+00:00",
        monotonic=_Monotonic(),
    )
    return gateway, client


class _Monotonic:
    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        self.value += 0.25
        return self.value


def _budget() -> ResearchBudget:
    return ResearchBudget(
        max_candidates=20,
        max_reads=8,
        soft_timeout_seconds=45.0,
        hard_timeout_seconds=60.0,
        max_total_chars=48_000,
    )


def _valid_claim_payload() -> str:
    return (
        '{"schema_version":"research-runtime-claim-plan-v1",'
        '"critical_claim":{"question_anchor":"What is the current API rate limit?",'
        '"kind":"factual","policy_profile":"current_fact"},'
        '"supporting_claims":[]}'
    )


def _attempt_marker(
    call_id: str = "logical:attempt:1",
    *,
    attempt: int = 1,
) -> ResearchModelAttemptStart:
    return ResearchModelAttemptStart(
        call_id=call_id,
        logical_call_id="logical",
        purpose="research_claim_planning",
        provider_profile="openai",
        model_profile="flash",
        model_name="test-model",
        attempt=attempt,
        started_at="2026-08-27T12:00:00+00:00",
        response_schema_version=RUNTIME_CLAIM_PLAN_SCHEMA_VERSION,
        input_sha256="a" * 64,
        input_chars=12,
        data_categories=("user_question",),
        data_counts=(("user_question", 1),),
    )


def _audit(call_id: str = "logical:attempt:1") -> ResearchModelCallAudit:
    return ResearchModelCallAudit(
        call_id=call_id,
        logical_call_id="logical",
        purpose="research_claim_planning",
        provider_profile="openai",
        model_profile="flash",
        model_name="test-model",
        attempt=1,
        started_at="2026-08-27T12:00:00+00:00",
        completed_at="2026-08-27T12:00:01+00:00",
        elapsed_seconds=1.0,
        status="completed",
        response_schema_version=RUNTIME_CLAIM_PLAN_SCHEMA_VERSION,
        input_sha256="a" * 64,
        input_chars=12,
        response_sha256="b" * 64,
        response_chars=20,
    )


def test_model_gateway_disables_hidden_retries_and_audits_explicit_attempts() -> None:
    gateway, client = _gateway(
        [
            _response("not-json"),
            _response('{"ok":true}', prompt_tokens=11, completion_tokens=3),
        ]
    )
    events: list[str] = []

    result = gateway.complete_structured(
        logical_call_id="claim:run-1:1",
        purpose="research_claim_planning",
        messages=[{"role": "user", "content": "PRIVATE-MARKER"}],
        audit_payload={"question": "public question"},
        response_schema_version="test-v1",
        parse=lambda value: value["ok"],
        data_categories=("user_question",),
        data_counts={"user_question": 1},
        on_attempt_started=lambda marker: events.append(f"start:{marker.attempt}"),
        on_attempt_finished=lambda audit: events.append(f"finish:{audit.attempt}"),
    )

    assert result.completed is True
    assert result.value is True
    assert [item.status for item in result.audits] == ["attempt_failed", "completed"]
    assert client.with_options_calls == [{"max_retries": 0}, {"max_retries": 0}]
    assert events == ["start:1", "finish:1", "start:2", "finish:2"]
    assert result.audits[1].input_tokens == 11
    assert result.audits[1].output_tokens == 3
    assert result.audits[1].total_tokens == 14
    assert all(call["response_format"] == {"type": "json_object"} for call in client.create_calls)
    assert "PRIVATE-MARKER" not in str([item.to_dict() for item in result.audits])


def test_model_gateway_exhaustion_is_unavailable_without_token_estimates() -> None:
    gateway, _ = _gateway([TimeoutError("one"), TimeoutError("two")])

    result = gateway.complete_structured(
        logical_call_id="claim:run-2:1",
        purpose="research_claim_planning",
        messages=[{"role": "user", "content": "question"}],
        audit_payload={"question": "question"},
        response_schema_version="test-v1",
        parse=lambda value: value,
    )

    assert result.status == "unavailable"
    assert result.value is None
    assert result.reason == "model_call_attempts_exhausted"
    assert len(result.audits) == 2
    assert all(item.status == "attempt_failed" for item in result.audits)
    assert all(item.input_tokens is None for item in result.audits)
    assert all(item.output_tokens is None for item in result.audits)
    assert all(item.total_tokens is None for item in result.audits)


def test_claim_planner_defaults_to_shadow_and_code_owns_policy_and_ids() -> None:
    gateway, _ = _gateway([_response(_valid_claim_payload())])
    planner = RuntimeClaimPlanner(gateway)

    result = planner.plan(
        run_id="run-1",
        question="What is the current API rate limit?",
        reference_date="2026-08-27",
        budget=_budget(),
        freshness_requested=True,
        freshness_days=7,
        timestamp="2026-08-27T12:00:00+00:00",
    )

    assert result.completed is True
    state = result.state
    assert state is not None
    assert state.mode == "shadow"
    assert state.reference_date == "2026-08-27"
    assert len(state.claims) == 1
    claim = state.claims[0]
    assert claim.id.startswith("claim_")
    assert claim.created_by == "runtime_claim_planner"
    assert set(claim.evidence_requirement.source_roles) == {
        "primary",
        "authoritative_secondary",
        "independent_secondary",
    }
    assert claim.evidence_requirement.max_age_days == 7
    assert claim.evidence_requirement.requires_dated_evidence is True
    assert state.gaps[0].id.startswith("gap_")
    assert state.gaps[0].desired_source_role == "primary"
    assert [item.sequence for item in state.trace] == [0, 1]
    assert [item.event_type for item in state.trace] == ["claim_created", "gap_created"]


def test_claim_planner_allows_active_only_when_explicitly_requested() -> None:
    gateway, _ = _gateway([_response(_valid_claim_payload())])

    result = RuntimeClaimPlanner(gateway).plan(
        run_id="run-active",
        question="What is the current API rate limit?",
        reference_date="2026-08-27",
        budget=_budget(),
        mode="active",
    )

    assert result.completed is True
    assert result.state is not None
    assert result.state.mode == "active"


def test_claim_planner_requests_bounded_completion_budget() -> None:
    """Planner control-plane output is deliberately bounded and task-specific."""

    gateway, client = _gateway([_response(_valid_claim_payload())])

    result = RuntimeClaimPlanner(gateway).plan(
        run_id="run-budget",
        question="What is the current API rate limit?",
        reference_date="2026-08-27",
        budget=_budget(),
        mode="active",
    )

    assert result.completed is True
    assert client.create_calls, "planner must issue exactly one model call"
    for call in client.create_calls:
        assert call["max_tokens"] == CLAIM_PLANNER_MAX_TOKENS == 320


@pytest.mark.parametrize(
    "payload",
    [
        (
            '{"schema_version":"research-runtime-claim-plan-v1",'
            '"critical_claim":{"question_anchor":"Question","kind":"factual",'
            '"policy_profile":"causal_analysis"},"supporting_claims":[]}'
        ),
        (
            '{"schema_version":"research-runtime-claim-plan-v1",'
            '"critical_claim":{"question_anchor":"Not in question","kind":"factual",'
            '"policy_profile":"current_fact"},"supporting_claims":[]}'
        ),
        (
            '{"schema_version":"research-runtime-claim-plan-v1",'
            '"critical_claim":{"question_anchor":"Question","kind":"factual",'
            '"policy_profile":"current_fact","evidence_id":"model-owned"},'
            '"supporting_claims":[]}'
        ),
    ],
)
def test_claim_planner_invalid_schema_or_policy_fails_closed(payload: str) -> None:
    gateway, _ = _gateway([_response(payload), _response(payload)])

    result = RuntimeClaimPlanner(gateway).plan(
        run_id="run-invalid",
        question="Question",
        reference_date="2026-08-27",
        budget=_budget(),
    )

    assert result.status == "unavailable"
    assert result.state is None
    assert len(result.audits) == 1
    assert all(item.status == "attempt_failed" for item in result.audits)


def test_runtime_cursor_round_trip_and_attach_preserves_unrelated_context() -> None:
    query = RuntimePlannedQuery(
        id="q1",
        gap_id="g1",
        claim_id="c1",
        intent="primary",
        query="official source query",
        desired_source_role="primary",
    )
    candidate = RuntimeCandidate(
        id="candidate_1",
        url="https://example.test/official",
        title="Official source",
        query_ids=("q1",),
        intents=("primary",),
        providers=("searxng",),
        first_seen_rank=1,
    )
    cursor = ResearchRuntimeCursor(
        round_index=1,
        phase="searching",
        planned_queries=(query,),
        query_outcomes=(
            RuntimeQueryOutcome(
                query_id="q1",
                status="ok",
                result_count=1,
                providers=("searxng",),
            ),
        ),
        candidates=(candidate,),
        planned_read_ids=("candidate_1",),
    )

    restored = ResearchRuntimeCursor.from_dict(cursor.to_dict())
    assert restored == cursor
    context = attach_runtime_cursor({"legacy": {"keep": True}}, cursor)
    assert context["legacy"] == {"keep": True}
    assert context[CLAIM_ENGINE_RUNTIME_CONTEXT_KEY]["schema_version"] == "research-runtime-v2"
    loaded = load_runtime_cursor(context)
    assert loaded.available is True
    assert loaded.cursor == cursor


def test_corrupt_runtime_cursor_fails_safe_without_throwing() -> None:
    result = load_runtime_cursor(
        {CLAIM_ENGINE_RUNTIME_CONTEXT_KEY: {"schema_version": "old"}}
    )
    assert result.status == "unavailable"
    assert result.cursor is None
    assert result.reason == "invalid_claim_engine_runtime"


def test_runtime_cursor_rejects_unknown_query_and_candidate_references() -> None:
    with pytest.raises(ValueError, match="unknown query"):
        ResearchRuntimeCursor.from_dict(
            {
                **ResearchRuntimeCursor().to_dict(),
                "planned_queries": [],
                "query_outcomes": [
                    RuntimeQueryOutcome(
                        query_id="missing",
                        status="empty",
                        result_count=0,
                    ).to_dict()
                ],
            }
        )

    with pytest.raises(ValueError, match="unknown candidate"):
        ResearchRuntimeCursor.from_dict(
            {
                **ResearchRuntimeCursor().to_dict(),
                "planned_read_ids": ["missing"],
            }
        )


def test_runtime_cursor_rejects_inconsistent_or_malformed_wave_truth() -> None:
    no_gain = EvidenceGainResult(
        substantive_gain=False,
        gain_reasons=(),
        affected_claim_ids=(),
        affected_gap_ids=(),
    ).to_dict()

    with pytest.raises(ValueError, match="gain history cannot exceed wave index"):
        ResearchRuntimeCursor.from_dict(
            {
                **ResearchRuntimeCursor().to_dict(),
                "gain_history": [no_gain],
            }
        )

    with pytest.raises(ValueError, match="pre-wave cursor cannot carry wave state"):
        ResearchRuntimeCursor.from_dict(
            {
                **ResearchRuntimeCursor().to_dict(),
                "wave_id": "research_wave:run:0",
            }
        )

    malformed = {**no_gain, "substantive_gain": True}
    with pytest.raises(ValueError, match="substantive_gain contradicts"):
        ResearchRuntimeCursor.from_dict(
            {
                **ResearchRuntimeCursor().to_dict(),
                "wave_index": 1,
                "gain_history": [malformed],
            }
        )


def test_inflight_model_call_recovers_as_interrupted_unknown() -> None:
    started = begin_model_attempt(ResearchRuntimeCursor(phase="planning"), _attempt_marker())
    assert started.inflight_model_call is not None

    recovered = recover_interrupted_model_attempt(started)
    assert recovered.inflight_model_call is None
    assert recovered.failures[-1].code == "claim_planning_failed"
    assert recovered.failures[-1].detail == "interrupted_unknown"
    assert recovered.failures[-1].failure_id
    assert recovered.failures[-1].item_id == "logical:attempt:1"


def test_recovered_model_attempt_advances_once_then_exhausts_ceiling() -> None:
    first = recover_interrupted_model_attempt(
        begin_model_attempt(ResearchRuntimeCursor(phase="planning"), _attempt_marker())
    )

    assert _model_attempt_start(first, "logical") == 2

    second = recover_interrupted_model_attempt(
        begin_model_attempt(
            first,
            _attempt_marker("logical:attempt:2", attempt=2),
        )
    )

    assert [item.item_id for item in second.failures] == [
        "logical:attempt:1",
        "logical:attempt:2",
    ]
    with pytest.raises(RuntimeError, match="model attempts exhausted"):
        _model_attempt_start(second, "logical")


def test_inflight_external_call_recovers_as_interrupted_unknown() -> None:
    marker = RuntimeExternalAttemptStart(
        call_id="research_read:run-1:candidate-1:attempt:1",
        purpose="read",
        item_id="candidate-1",
        attempt=1,
        started_at="2026-08-27T12:00:00+00:00",
    )
    started = begin_external_attempt(ResearchRuntimeCursor(phase="reading"), marker)

    recovered = recover_interrupted_external_attempt(started)

    assert recovered.inflight_external_call is None
    failure = recovered.failures[-1]
    assert failure.code == "read_failed"
    assert failure.phase == "reading"
    assert failure.item_id == marker.call_id
    assert failure.detail == "interrupted_unknown"
    assert failure.attempt_id == marker.call_id
    assert failure.failure_id


def test_v1_model_recovery_checkpoint_preserves_attempt_two_marker() -> None:
    cursor = ResearchRuntimeCursor(
        phase="planning", schema_version=RESEARCH_RUNTIME_SCHEMA_VERSION_V1
    )
    recovered = recover_interrupted_model_attempt(
        begin_model_attempt(cursor, _attempt_marker())
    )

    checkpointed = ResearchRuntimeCursor.from_dict(recovered.to_dict())

    assert checkpointed.failures[-1].code == "interrupted_unknown"
    assert checkpointed.failures[-1].legacy_input is True
    assert _model_attempt_start(checkpointed, "logical") == 2


@pytest.mark.parametrize("purpose,phase", [("read", "reading"), ("search", "searching")])
def test_v1_external_recovery_checkpoint_preserves_attempt_two_marker(
    purpose: RuntimeExternalPurpose,
    phase: RuntimePhase,
) -> None:
    item_id = f"{purpose}-item"
    marker = RuntimeExternalAttemptStart(
        call_id=f"research_{purpose}:run-1:{item_id}:attempt:1",
        purpose=purpose,
        item_id=item_id,
        attempt=1,
        started_at="2026-09-01T00:00:00+00:00",
    )
    cursor = ResearchRuntimeCursor(
        phase=phase,
        schema_version=RESEARCH_RUNTIME_SCHEMA_VERSION_V1,
    )
    recovered = recover_interrupted_external_attempt(
        begin_external_attempt(cursor, marker)
    )

    checkpointed = ResearchRuntimeCursor.from_dict(recovered.to_dict())

    assert checkpointed.failures[-1].code == "interrupted_unknown"
    assert _attempt_number(checkpointed, item_id) == 2


def test_v1_second_model_interruption_never_allows_attempt_three() -> None:
    cursor = ResearchRuntimeCursor(
        phase="planning", schema_version=RESEARCH_RUNTIME_SCHEMA_VERSION_V1
    )
    first = ResearchRuntimeCursor.from_dict(
        recover_interrupted_model_attempt(
            begin_model_attempt(cursor, _attempt_marker())
        ).to_dict()
    )
    second = ResearchRuntimeCursor.from_dict(
        recover_interrupted_model_attempt(
            begin_model_attempt(
                first,
                _attempt_marker("logical:attempt:2", attempt=2),
            )
        ).to_dict()
    )

    with pytest.raises(RuntimeError, match="model attempts exhausted"):
        _model_attempt_start(second, "logical")


@pytest.mark.parametrize("purpose,phase", [("read", "reading"), ("search", "searching")])
def test_v1_second_external_interruption_never_reuses_consumed_call(
    purpose: RuntimeExternalPurpose,
    phase: RuntimePhase,
) -> None:
    item_id = f"{purpose}-item"
    cursor = ResearchRuntimeCursor(
        phase=phase,
        schema_version=RESEARCH_RUNTIME_SCHEMA_VERSION_V1,
    )
    first_marker = RuntimeExternalAttemptStart(
        call_id=f"research_{purpose}:run-1:{item_id}:attempt:1",
        purpose=purpose,
        item_id=item_id,
        attempt=1,
        started_at="2026-09-01T00:00:00+00:00",
    )
    first = ResearchRuntimeCursor.from_dict(
        recover_interrupted_external_attempt(
            begin_external_attempt(cursor, first_marker)
        ).to_dict()
    )
    second_marker = RuntimeExternalAttemptStart(
        call_id=f"research_{purpose}:run-1:{item_id}:attempt:2",
        purpose=purpose,
        item_id=item_id,
        attempt=2,
        started_at="2026-09-01T00:00:01+00:00",
    )
    second = ResearchRuntimeCursor.from_dict(
        recover_interrupted_external_attempt(
            begin_external_attempt(first, second_marker)
        ).to_dict()
    )

    with pytest.raises(
        _ExternalAttemptBudgetExhausted,
        match="external attempts exhausted",
    ):
        _attempt_number(second, item_id)


def test_pre_b5_v1_cursor_loads_with_no_external_call_inflight() -> None:
    legacy = ResearchRuntimeCursor(
        phase="searching", schema_version=RESEARCH_RUNTIME_SCHEMA_VERSION_V1
    ).to_dict()
    del legacy["inflight_external_call"]

    restored = ResearchRuntimeCursor.from_dict(legacy)

    assert restored.inflight_external_call is None


def test_pre_p1c_v1_cursor_loads_with_empty_wave_truth() -> None:
    legacy = ResearchRuntimeCursor(
        phase="searching", schema_version=RESEARCH_RUNTIME_SCHEMA_VERSION_V1
    ).to_dict()
    for key in (
        "wave_index",
        "wave_id",
        "active_gap_ids",
        "gain_history",
        "no_gain_batches_by_claim",
        "no_gain_batches_by_gap",
    ):
        del legacy[key]

    restored = ResearchRuntimeCursor.from_dict(legacy)

    assert restored.wave_index == 0
    assert restored.wave_id == ""
    assert restored.active_gap_ids == ()
    assert restored.gain_history == ()
    assert restored.no_gain_batches_by_claim == {}
    assert restored.no_gain_batches_by_gap == {}


def test_model_attempt_completion_requires_matching_inflight_call() -> None:
    cursor = begin_model_attempt(ResearchRuntimeCursor(), _attempt_marker())
    completed = finish_model_attempt(cursor, _audit())
    assert completed.inflight_model_call is None
    assert completed.model_calls == (_audit(),)

    with pytest.raises(ValueError, match="does not match"):
        finish_model_attempt(
            begin_model_attempt(ResearchRuntimeCursor(), _attempt_marker()),
            _audit("other:attempt:1"),
        )


def test_a4a_production_modules_do_not_import_eval_code() -> None:
    research_dir = Path(__file__).resolve().parents[1] / "src" / "web" / "research"
    for name in ("model_gateway.py", "claim_planner.py", "runtime.py"):
        text = (research_dir / name).read_text(encoding="utf-8")
        assert "src.evals" not in text


def test_runtime_cursor_rejects_malformed_wave_fields() -> None:
    """P1-C batch 2: wave-related cursor fields fail closed on malformed input."""
    with pytest.raises(ValueError):
        ResearchRuntimeCursor.from_dict(
            {
                **ResearchRuntimeCursor().to_dict(),
                "wave_index": -1,
            }
        )

    with pytest.raises(ValueError):
        ResearchRuntimeCursor.from_dict(
            {
                **ResearchRuntimeCursor().to_dict(),
                "active_gap_ids": ["gap_1", "gap_1"],
            }
        )

    with pytest.raises(ValueError):
        ResearchRuntimeCursor.from_dict(
            {
                **ResearchRuntimeCursor().to_dict(),
                "active_gap_ids": [""],
            }
        )

    with pytest.raises((ValueError, TypeError)):
        ResearchRuntimeCursor.from_dict(
            {
                **ResearchRuntimeCursor().to_dict(),
                "gain_history": ["not a mapping"],
            }
        )

    with pytest.raises(ValueError):
        ResearchRuntimeCursor.from_dict(
            {
                **ResearchRuntimeCursor().to_dict(),
                "no_gain_batches_by_claim": {"gap_1": -1},
            }
        )

    with pytest.raises(ValueError):
        ResearchRuntimeCursor.from_dict(
            {
                **ResearchRuntimeCursor().to_dict(),
                "no_gain_batches_by_claim": {"gap_1": 1.5},
            }
        )

    with pytest.raises(ValueError):
        ResearchRuntimeCursor.from_dict(
            {
                **ResearchRuntimeCursor().to_dict(),
                "no_gain_batches_by_claim": {"gap_1": True},
            }
        )


def test_assessment_call_suffix_is_canonical_over_candidate_order() -> None:
    """P1-C batch 2: the assessment logical identity must not depend on the
    candidate list order, only on the sorted candidate set."""
    from src.application.active_research_runtime import _assessment_call_suffix

    cursor = ResearchRuntimeCursor(
        wave_id="research_wave:run_dbg:2",
    )
    ids_a = ("candidate_a", "candidate_b", "candidate_c")
    ids_b = ("candidate_c", "candidate_a", "candidate_b")

    suffix_a = _assessment_call_suffix(cursor, "claim_1", ids_a)
    suffix_b = _assessment_call_suffix(cursor, "claim_1", ids_b)

    assert suffix_a == suffix_b
    assert "research_wave:run_dbg:2" in suffix_a
    assert "claim_1" in suffix_a

    # A different candidate set must change the fingerprint.
    ids_c = ("candidate_a", "candidate_b", "candidate_d")
    suffix_c = _assessment_call_suffix(cursor, "claim_1", ids_c)
    assert suffix_c != suffix_a
