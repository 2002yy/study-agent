"""Answer publication gate tests (RQ1-C answer batch).

Research-backed turns (carrying a server-owned ``answer_validation`` plan)
publish the generated candidate only when claim/evidence binding validates.
Everything else replaces the learner-facing text with the canonical blocked
copy while the rejected audit truth is persisted in the same commit.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Sequence

from src.application.chat_service import (
    RESEARCH_ANSWER_BLOCKED_COPY,
    ChatCommand,
    ChatDependencies,
    ChatService,
)
from src.application.policy_chat_service import (
    ExternalDataPolicyChatService,
    PolicyChatCommand,
)
from src.domain.answer_claims import answer_content_hash
from src.domain.answer_validation import sha256_text
from src.domain.runtime_entities import ChatTurn
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.mode_manager import RuntimeModes
from src.pedagogy.evaluation import PedagogyEvaluationService
from src.repositories.runtime_repository import RuntimeRepository
from src.tools.web_agent import WebToolTrace

EVIDENCE_ID = "evidence_abc123"
RESEARCH_CLAIM_ID = "research_claim_1"
CANDIDATE = "该版本已正式发布，并修复了已知问题。"
CLAIM_TEXT = "该版本已正式发布。"
ANSWER = "candidate text to publish"


class _FakeRagResult:
    context = "local context"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": "found",
            "context": "local",
            "result_count": 0,
            "results": [],
        }


def _row(evidence_id: str = EVIDENCE_ID) -> dict[str, Any]:
    return {
        "evidence_id": evidence_id,
        "claim_id": RESEARCH_CLAIM_ID,
        "title": "Official release",
        "url": "https://official.example/release",
        "source_role": "official_statement",
        "source_cluster_id": "cluster_1",
        "relation": "supports",
        "strength": "strong",
        "locator": "第四段",
        "anchored_spans": ("official confirmation of the release",),
        "caveats": (),
    }


def _segment_entry(
    ref: str,
    *,
    kind: str = "factual",
    status: str = "asserted",
    support: Sequence[str] = (),
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "segment_ref": ref,
        "kind": kind,
        "evidence_support": list(support),
    }
    if status:
        entry["status"] = status
    return entry


def _binding_payload(
    segments: Sequence[dict[str, Any]],
    *,
    refused: bool = False,
    segment_count: int = 1,
) -> str:
    """Build a v3 payload covering exactly ``segment_count`` server segments."""
    provided = {
        str(entry.get("segment_ref"))
        for entry in segments
        if isinstance(entry, dict)
    }
    entries = [dict(entry) for entry in segments if isinstance(entry, dict)]
    default_support: list[str] = []
    for entry in entries:
        if entry.get("segment_ref") == "s1":
            default_support = list(entry.get("evidence_support") or [])
            break
    for index in range(1, segment_count + 1):
        ref = f"s{index}"
        if ref not in provided:
            entries.append(
                {
                    "segment_ref": ref,
                    "kind": "factual",
                    "status": "asserted",
                    "evidence_support": list(default_support),
                }
            )
    return json.dumps(
        {"refused": refused, "segments": entries}, ensure_ascii=False
    )


def _command(
    *,
    rows: list[dict[str, Any]] | None = None,
    allowed_attempts: int = 1,
    policy_service: bool = False,
) -> ChatCommand | PolicyChatCommand:
    base: dict[str, Any] = dict(
        user_input="该版本发布了吗？",
        selected_role="nahida",
        web_context="source block text",
        web_context_run_id="web_lookup_1",
        answer_validation=(
            {"evidence_rows": rows, "allowed_attempts": allowed_attempts}
            if rows is not None
            else None
        ),
    )
    if policy_service:
        base["research_sources"] = {"run_id": "web_lookup_1"}
        return PolicyChatCommand(**base)
    return ChatCommand(**base)


def _dependencies(chat_fn: Callable[..., str]) -> ChatDependencies:
    return ChatDependencies(
        load_runtime_modes=lambda: RuntimeModes(
            memory_mode="preview", performance_mode="standard"
        ),
        read_memory_bundle=lambda context_mode: {},
        build_role_prompt=lambda role, **kwargs: f"role:{role}",
        route_request=lambda **kwargs: {
            "role": "nahida",
            "mode": "普通",
            "model_profile": "flash",
            "reason": "test",
        },
        retrieve_local_knowledge=lambda *args, **kwargs: _FakeRagResult(),
        build_messages=lambda **kwargs: [
            {"role": "system", "content": kwargs["role_prompt"]},
            {"role": "user", "content": kwargs["user_input"]},
        ],
        chat=chat_fn,
        stream_chat=lambda *args, **kwargs: iter(["part", " two"]),
        chat_max_tokens=lambda performance_mode: 1000,
        resolve_web_tools=lambda *args, **kwargs: WebToolTrace(enabled=False),
        pedagogy_evaluation=PedagogyEvaluationService(),
    )


def _service(
    tmp_path, chat_fn: Callable[..., str], *, policy_service: bool = False
) -> tuple[ChatService, RuntimeRepository]:
    repository = RuntimeRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    service_class = ExternalDataPolicyChatService if policy_service else ChatService
    service = service_class(repository, _dependencies(chat_fn))
    return service, repository


def _turn(repository: RuntimeRepository, turn_id: str) -> ChatTurn:
    turn = repository.get_chat_turn(turn_id)
    if turn is None:
        raise AssertionError(f"turn not found: {turn_id}")
    return turn


def _audit(turn: ChatTurn) -> dict[str, Any]:
    stored = (turn.rag_snapshot or {}).get("answer_validation_audit")
    if not isinstance(stored, dict):
        raise AssertionError("missing answer_validation_audit")
    return stored


def _run_turn(
    service: ChatService,
    repository: RuntimeRepository,
    command: ChatCommand | PolicyChatCommand,
) -> tuple[str, ChatTurn]:
    prepared = service.start_turn(command)
    reply = service.generate(prepared)
    return reply, _turn(repository, prepared.turn.id)


def test_passed_binding_publishes_candidate_with_full_audit(tmp_path) -> None:
    """Answer generation and a passed binding are both authoritative-audited."""
    calls = [_binding_payload([_segment_entry("s1", support=(EVIDENCE_ID,))])]
    log = {"calls": 0, "tasks": []}

    def chat_fn(*args: Any, **kwargs: Any) -> str:
        log["calls"] += 1
        log["tasks"].append(kwargs.get("task_name", ""))
        return calls.pop(0) if log["calls"] > 1 else CANDIDATE

    service, repository = _service(tmp_path, chat_fn)
    reply, turn = _run_turn(service, repository, _command(rows=[_row()]))
    assert reply == CANDIDATE
    assert turn.status == "completed"
    assert turn.assistant_message == CANDIDATE
    audit = _audit(turn)
    assert audit["schema_version"] == "answer-validation-audit-v1"
    assert audit["candidate_answer_sha256"] == sha256_text(CANDIDATE)
    assert audit["learner_answer_sha256"] == sha256_text(CANDIDATE)
    generation = audit["phases"]["answer_generation"]
    assert generation["outcome"] == "completed"
    assert generation["model_calls"] == 1
    binding = audit["phases"]["answer_claim_binding"]
    assert binding["outcome"] == "passed"
    assert binding["model_calls"] == 1
    assert binding["error_type"] == ""
    assert log["calls"] == 2
    assert log["tasks"] == ["single_chat", "answer_claim_binding"]
    claims = (turn.rag_snapshot or {}).get("answer_claim_snapshot")
    assert claims is not None and claims["status"] == "validated"
    assert claims["answer_hash"] == answer_content_hash(CANDIDATE)


def test_rejected_binding_never_publishes_candidate(tmp_path) -> None:
    calls = [json.dumps({"refused": True, "claims": [], "claim_links": []})]

    def chat_fn(*args: Any, **kwargs: Any) -> str:
        return calls.pop(0) if kwargs.get("task_name") == "answer_claim_binding" else ANSWER

    service, repository = _service(tmp_path, chat_fn)
    reply, turn = _run_turn(service, repository, _command(rows=[_row()]))
    assert reply == RESEARCH_ANSWER_BLOCKED_COPY
    assert turn.status == "completed"
    assert turn.assistant_message == RESEARCH_ANSWER_BLOCKED_COPY
    audit = _audit(turn)
    assert audit["candidate_answer_sha256"] == sha256_text(ANSWER)
    assert audit["learner_answer_sha256"] == sha256_text(RESEARCH_ANSWER_BLOCKED_COPY)
    assert audit["candidate_answer_sha256"] != audit["learner_answer_sha256"]
    binding = audit["phases"]["answer_claim_binding"]
    assert binding["outcome"] == "rejected"
    assert binding["model_calls"] == 1
    claims = (turn.rag_snapshot or {}).get("answer_claim_snapshot")
    assert claims is not None and claims["status"] == "rejected"
    assert claims["answer_hash"] == answer_content_hash(RESEARCH_ANSWER_BLOCKED_COPY)


def test_zero_remaining_budget_makes_zero_binder_calls(tmp_path) -> None:
    calls = {"calls": 0}

    def chat_fn(*args: Any, **kwargs: Any) -> str:
        calls["calls"] += 1
        return ANSWER

    service, repository = _service(tmp_path, chat_fn)
    reply, turn = _run_turn(
        service, repository, _command(rows=[_row()], allowed_attempts=0)
    )
    assert reply == RESEARCH_ANSWER_BLOCKED_COPY
    assert calls["calls"] == 1
    audit = _audit(turn)
    binding = audit["phases"]["answer_claim_binding"]
    assert binding["outcome"] == "budget_exhausted"
    assert binding["model_calls"] == 0
    assert binding["error_type"] == "budget_exhausted"


def test_retry_counts_every_physical_binder_call(tmp_path) -> None:
    calls = {"binding": 0}

    def chat_fn(*args: Any, **kwargs: Any) -> str:
        if kwargs.get("task_name") == "answer_claim_binding":
            calls["binding"] += 1
            if calls["binding"] == 1:
                raise TimeoutError("transient timeout")
            return _binding_payload([_segment_entry("s1", support=(EVIDENCE_ID,))])
        return ANSWER

    service, repository = _service(tmp_path, chat_fn)
    reply, turn = _run_turn(
        service, repository, _command(rows=[_row()], allowed_attempts=2)
    )
    assert reply == ANSWER
    audit = _audit(turn)
    binding = audit["phases"]["answer_claim_binding"]
    assert binding["outcome"] == "passed"
    assert binding["model_calls"] == 2
    assert binding["attempts"] == 2


def test_single_authorized_attempt_does_not_retry(tmp_path) -> None:
    calls = {"binding": 0}

    def chat_fn(*args: Any, **kwargs: Any) -> str:
        if kwargs.get("task_name") == "answer_claim_binding":
            calls["binding"] += 1
            raise TimeoutError("transient timeout")
        return ANSWER

    service, repository = _service(tmp_path, chat_fn)
    reply, turn = _run_turn(service, repository, _command(rows=[_row()]))
    assert reply == RESEARCH_ANSWER_BLOCKED_COPY
    assert calls["binding"] == 1
    audit = _audit(turn)
    binding = audit["phases"]["answer_claim_binding"]
    assert binding["outcome"] == "rejected"
    assert binding["model_calls"] == 1
    assert binding["error_type"] == "producer_failed:TimeoutError"


def test_provider_error_never_leaks_raw_message(tmp_path) -> None:
    def chat_fn(*args: Any, **kwargs: Any) -> str:
        if kwargs.get("task_name") == "answer_claim_binding":
            raise RuntimeError("secret internal provider detail")
        return ANSWER

    service, repository = _service(tmp_path, chat_fn)
    reply, turn = _run_turn(service, repository, _command(rows=[_row()]))
    assert reply == RESEARCH_ANSWER_BLOCKED_COPY
    persisted = json.dumps(turn.rag_snapshot or {})
    assert "secret internal provider detail" not in persisted
    audit = _audit(turn)
    binding = audit["phases"]["answer_claim_binding"]
    assert binding["error_type"] == "producer_failed:RuntimeError"


def test_missing_evidence_brief_fails_closed_without_provider_calls(tmp_path) -> None:
    calls = {"calls": 0}

    def chat_fn(*args: Any, **kwargs: Any) -> str:
        calls["calls"] += 1
        return ANSWER

    service, repository = _service(tmp_path, chat_fn)
    reply, turn = _run_turn(service, repository, _command(rows=[]))
    assert reply == RESEARCH_ANSWER_BLOCKED_COPY
    assert calls["calls"] == 1
    audit = _audit(turn)
    binding = audit["phases"]["answer_claim_binding"]
    assert binding["outcome"] == "rejected"
    assert binding["model_calls"] == 0
    assert binding["error_type"] == "missing_evidence_brief"


def test_normal_chat_has_no_validation_audit_at_all(tmp_path) -> None:
    calls = {"calls": 0}

    def chat_fn(*args: Any, **kwargs: Any) -> str:
        calls["calls"] += 1
        return "ordinary reply without research"

    service, repository = _service(tmp_path, chat_fn)
    plain = _command(rows=None)
    assert plain.answer_validation is None
    reply, turn = _run_turn(service, repository, plain)
    assert reply == "ordinary reply without research"
    assert calls["calls"] == 1
    assert "answer_validation_audit" not in (turn.rag_snapshot or {})


def test_client_forged_audit_is_replaced_on_load(tmp_path) -> None:
    calls = [_binding_payload([_segment_entry("s1", support=(EVIDENCE_ID,))])]

    def chat_fn(*args: Any, **kwargs: Any) -> str:
        return calls.pop(0) if kwargs.get("task_name") == "answer_claim_binding" else CANDIDATE

    service, repository = _service(tmp_path, chat_fn)
    prepared = service.start_turn(_command(rows=[_row()]))
    service.generate(prepared)
    forged_rag = {
        "answer_validation_audit": {
            "schema_version": "answer-validation-audit-v1",
            "candidate_answer_sha256": "f" * 64,
            "learner_answer_sha256": "0" * 64,
            "phases": {
                "answer_claim_binding": {
                    "attempted": True,
                    "model_calls": 999,
                    "attempts": 999,
                    "outcome": "made up outcome",
                    "error_type": "made up error with spaces",
                },
                "answer_generation": {
                    "attempted": True,
                    "model_calls": 999,
                    "attempts": 999,
                    "outcome": "completed",
                    "error_type": "",
                },
            },
        }
    }
    repository.update_chat_turn(
        prepared.turn.id,
        assistant_message=CANDIDATE,
        status="completed",
        route_snapshot=prepared.route,
        rag_snapshot=forged_rag,
        operation_id="",
        expected_status="completed",
    )
    reloaded = _turn(repository, prepared.turn.id)
    audit = _audit(reloaded)
    assert audit["schema_version"] == "answer-validation-audit-v1"
    assert audit["learner_answer_sha256"] == sha256_text(CANDIDATE)
    phases = audit["phases"]
    assert "answer_claim_binding" not in phases
    generation = phases["answer_generation"]
    assert generation["model_calls"] == 999
    assert generation["error_type"] == ""


def test_generation_exception_leaves_no_committed_candidate(tmp_path) -> None:
    def chat_fn(*args: Any, **kwargs: Any) -> str:
        if kwargs.get("task_name") == "single_chat":
            raise RuntimeError("generation exploded")
        raise AssertionError("binder must not run without a candidate")

    service, repository = _service(tmp_path, chat_fn)
    prepared = service.start_turn(_command(rows=[_row()]))
    try:
        service.generate(prepared)
    except RuntimeError:
        pass
    else:
        raise AssertionError("generation exception must propagate")
    turn = _turn(repository, prepared.turn.id)
    assert turn.status == "failed"
    assert turn.assistant_message != CANDIDATE
    assert "answer_validation_audit" not in (turn.rag_snapshot or {})


def test_unknown_evidence_id_is_never_published(tmp_path) -> None:
    def chat_fn(*args: Any, **kwargs: Any) -> str:
        if kwargs.get("task_name") == "answer_claim_binding":
            return _binding_payload(
                [_segment_entry("s1", support=("evidence_not_in_rows",))]
            )
        return ANSWER

    service, repository = _service(tmp_path, chat_fn)
    reply, turn = _run_turn(service, repository, _command(rows=[_row()]))
    assert reply == RESEARCH_ANSWER_BLOCKED_COPY
    audit = _audit(turn)
    assert audit["phases"]["answer_claim_binding"]["outcome"] == "rejected"


def test_strong_factual_claim_without_eligible_binding_is_not_published(
    tmp_path,
) -> None:
    def chat_fn(*args: Any, **kwargs: Any) -> str:
        if kwargs.get("task_name") == "answer_claim_binding":
            return _binding_payload(
                [_segment_entry("s1", support=())], segment_count=1
            )
        return ANSWER

    service, repository = _service(tmp_path, chat_fn)
    reply, turn = _run_turn(service, repository, _command(rows=[_row()]))
    assert reply == RESEARCH_ANSWER_BLOCKED_COPY
    audit = _audit(turn)
    binding = audit["phases"]["answer_claim_binding"]
    assert binding["outcome"] == "rejected"
    assert binding["model_calls"] == 1
    claims = (turn.rag_snapshot or {}).get("answer_claim_snapshot")
    assert claims is not None and claims["status"] == "rejected"


def test_web_policy_denied_never_calls_the_binder(tmp_path) -> None:
    from src.pedagogy.evaluation import SemanticEvaluation
    from src.task_contract import (
        TaskAwarePedagogyEngine,
        TaskAwarePedagogyEvaluationService,
        route_request_with_task_contract,
    )

    class _FailingSemanticEvaluator:
        def evaluate(self, **kwargs: Any) -> SemanticEvaluation:
            raise AssertionError("semantic evaluation must not run in this test")

    calls = {"binding": 0, "generation": 0}

    def chat_fn(*args: Any, **kwargs: Any) -> str:
        if kwargs.get("task_name") == "answer_claim_binding":
            calls["binding"] += 1
            raise AssertionError("binder must not run when web is denied")
        calls["generation"] += 1
        return ANSWER

    def retrieve(_query: str, **kwargs: Any) -> Any:
        return _FakeRagResult()

    repository = RuntimeRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    dependencies = ChatDependencies(
        route_request=route_request_with_task_contract,
        read_memory_bundle=lambda _mode: {},
        retrieve_local_knowledge=retrieve,
        resolve_web_tools=lambda *args, **kwargs: WebToolTrace(enabled=False),
        build_messages=lambda **kwargs: [
            {"role": "system", "content": kwargs.get("rag_context", "")},
            {"role": "user", "content": kwargs["user_input"]},
        ],
        pedagogy_engine=TaskAwarePedagogyEngine(),
        pedagogy_evaluation=TaskAwarePedagogyEvaluationService(
            _FailingSemanticEvaluator()
        ),
        build_role_prompt=lambda *_args, **_kwargs: "ROLE",
        chat=chat_fn,
        chat_max_tokens=lambda performance_mode: 1000,
    )
    service = ExternalDataPolicyChatService(repository, dependencies)
    base = _command(rows=[_row()], policy_service=True)
    assert isinstance(base, PolicyChatCommand)
    denied_kwargs = {**base.__dict__, "web_policy": "off", "web_consent": False}
    denied = PolicyChatCommand(**denied_kwargs)
    prepared = service.start_turn(denied)
    reply = service.generate(prepared)
    assert reply == ANSWER
    assert calls["binding"] == 0
    assert calls["generation"] == 1
    turn = _turn(repository, prepared.turn.id)
    assert (turn.rag_snapshot or {}).get("answer_validation_audit") is None
    policy = (turn.route_snapshot or {}).get("external_data_policy")
    recorded = [
        item
        for item in (policy or {}).get("external_calls", [])
        if isinstance(item, dict) and item.get("purpose") == "answer_claim_binding"
    ]
    assert recorded == []


def test_policy_service_production_path_publishes_passed_candidate(tmp_path) -> None:
    from src.pedagogy.evaluation import SemanticEvaluation
    from src.task_contract import (
        TaskAwarePedagogyEngine,
        TaskAwarePedagogyEvaluationService,
        route_request_with_task_contract,
    )

    class _FailingSemanticEvaluator:
        def evaluate(self, **kwargs: Any) -> SemanticEvaluation:
            raise AssertionError("semantic evaluation must not run in this test")

    calls = [_binding_payload([_segment_entry("s1", support=(EVIDENCE_ID,))])]

    def chat_fn(*args: Any, **kwargs: Any) -> str:
        return calls.pop(0) if kwargs.get("task_name") == "answer_claim_binding" else ANSWER

    def retrieve(_query: str, **kwargs: Any) -> Any:
        return _FakeRagResult()

    repository = RuntimeRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    dependencies = ChatDependencies(
        route_request=route_request_with_task_contract,
        read_memory_bundle=lambda _mode: {},
        retrieve_local_knowledge=retrieve,
        resolve_web_tools=lambda *args, **kwargs: WebToolTrace(enabled=False),
        build_messages=lambda **kwargs: [
            {"role": "system", "content": kwargs.get("rag_context", "")},
            {"role": "user", "content": kwargs["user_input"]},
        ],
        pedagogy_engine=TaskAwarePedagogyEngine(),
        pedagogy_evaluation=TaskAwarePedagogyEvaluationService(
            _FailingSemanticEvaluator()
        ),
        build_role_prompt=lambda *_args, **_kwargs: "ROLE",
        chat=chat_fn,
        chat_max_tokens=lambda performance_mode: 1000,
    )
    service = ExternalDataPolicyChatService(repository, dependencies)
    reply, turn = _run_turn(
        service, repository, _command(rows=[_row()], policy_service=True)
    )
    assert reply == ANSWER
    audit = _audit(turn)
    assert audit["phases"]["answer_claim_binding"]["outcome"] == "passed"


def test_g16_audit_records_binding_outbound_on_passed_policy_turn(tmp_path) -> None:
    from src.pedagogy.evaluation import SemanticEvaluation
    from src.task_contract import (
        TaskAwarePedagogyEngine,
        TaskAwarePedagogyEvaluationService,
        route_request_with_task_contract,
    )

    class _FailingSemanticEvaluator:
        def evaluate(self, **kwargs: Any) -> SemanticEvaluation:
            raise AssertionError("semantic evaluation must not run in this test")

    calls = [_binding_payload([_segment_entry("s1", support=(EVIDENCE_ID,))])]

    def chat_fn(*args: Any, **kwargs: Any) -> str:
        return calls.pop(0) if kwargs.get("task_name") == "answer_claim_binding" else ANSWER

    def retrieve(_query: str, **kwargs: Any) -> Any:
        return _FakeRagResult()

    repository = RuntimeRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    dependencies = ChatDependencies(
        route_request=route_request_with_task_contract,
        read_memory_bundle=lambda _mode: {},
        retrieve_local_knowledge=retrieve,
        resolve_web_tools=lambda *args, **kwargs: WebToolTrace(enabled=False),
        build_messages=lambda **kwargs: [
            {"role": "system", "content": kwargs.get("rag_context", "")},
            {"role": "user", "content": kwargs["user_input"]},
        ],
        pedagogy_engine=TaskAwarePedagogyEngine(),
        pedagogy_evaluation=TaskAwarePedagogyEvaluationService(
            _FailingSemanticEvaluator()
        ),
        build_role_prompt=lambda *_args, **_kwargs: "ROLE",
        chat=chat_fn,
        chat_max_tokens=lambda performance_mode: 1000,
    )
    service = ExternalDataPolicyChatService(repository, dependencies)
    reply, turn = _run_turn(
        service, repository, _command(rows=[_row()], policy_service=True)
    )
    assert reply == ANSWER
    policy = (turn.route_snapshot or {}).get("external_data_policy")
    assert isinstance(policy, dict)
    calls_recorded = [
        item
        for item in policy.get("external_calls", [])
        if isinstance(item, dict)
    ]
    purposes = [item.get("purpose") for item in calls_recorded]
    assert "answer_claim_binding" in purposes
    binding = next(
        item
        for item in calls_recorded
        if item.get("purpose") == "answer_claim_binding"
    )
    assert binding["status"] == "completed"
    assert binding["provider"]
    assert binding["data_categories"] == [
        "current_question",
        "candidate_answer",
        "web_results",
    ]
    assert binding["data_counts"]["candidate_answer"] == 1
    assert binding["data_counts"]["web_results"] == 1
    assert binding["attempts"] == 1


def test_g16_audit_records_rejected_binding_outcome(tmp_path) -> None:
    from src.pedagogy.evaluation import SemanticEvaluation
    from src.task_contract import (
        TaskAwarePedagogyEngine,
        TaskAwarePedagogyEvaluationService,
        route_request_with_task_contract,
    )

    class _FailingSemanticEvaluator:
        def evaluate(self, **kwargs: Any) -> SemanticEvaluation:
            raise AssertionError("semantic evaluation must not run in this test")

    def chat_fn(*args: Any, **kwargs: Any) -> str:
        if kwargs.get("task_name") == "answer_claim_binding":
            return json.dumps({"refused": True, "segments": []})
        return ANSWER

    def retrieve(_query: str, **kwargs: Any) -> Any:
        return _FakeRagResult()

    repository = RuntimeRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    dependencies = ChatDependencies(
        route_request=route_request_with_task_contract,
        read_memory_bundle=lambda _mode: {},
        retrieve_local_knowledge=retrieve,
        resolve_web_tools=lambda *args, **kwargs: WebToolTrace(enabled=False),
        build_messages=lambda **kwargs: [
            {"role": "system", "content": kwargs.get("rag_context", "")},
            {"role": "user", "content": kwargs["user_input"]},
        ],
        pedagogy_engine=TaskAwarePedagogyEngine(),
        pedagogy_evaluation=TaskAwarePedagogyEvaluationService(
            _FailingSemanticEvaluator()
        ),
        build_role_prompt=lambda *_args, **_kwargs: "ROLE",
        chat=chat_fn,
        chat_max_tokens=lambda performance_mode: 1000,
    )
    service = ExternalDataPolicyChatService(repository, dependencies)
    reply, turn = _run_turn(
        service, repository, _command(rows=[_row()], policy_service=True)
    )
    assert reply == RESEARCH_ANSWER_BLOCKED_COPY
    policy = (turn.route_snapshot or {}).get("external_data_policy")
    binding = next(
        item
        for item in (policy or {}).get("external_calls", [])
        if isinstance(item, dict) and item.get("purpose") == "answer_claim_binding"
    )
    assert binding["status"] == "rejected"
    assert "producer_refused" not in json.dumps(binding)


# --- BLOCK-only answer reasoning policy (anti-drift invariants) ---------------
#
# Gate=BLOCK is known before generation (no eligible evidence rows, or no
# attempt budget) and the release gate then replaces whatever the model wrote
# with RESEARCH_ANSWER_BLOCKED_COPY. Measured on real production prompts, the
# default answer call spends 1330-2083 hidden reasoning tokens (16-41s) for
# output that is discarded, so the blocked branch must not reason - while any
# other gate outcome must keep the production default.


def _generation_calls(seen: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in seen if item.get("task_name") == "single_chat"]


def test_block_without_evidence_rows_disables_answer_thinking(tmp_path) -> None:
    seen: list[dict[str, Any]] = []

    def chat_fn(*args: Any, **kwargs: Any) -> str:
        seen.append(dict(kwargs))
        return "candidate text that the release gate will discard"

    service, repository = _service(tmp_path, chat_fn)
    reply, turn = _run_turn(service, repository, _command(rows=[]))

    # Published surface is unchanged: the blocked copy still wins.
    assert reply == RESEARCH_ANSWER_BLOCKED_COPY
    assert turn.assistant_message == RESEARCH_ANSWER_BLOCKED_COPY
    assert _audit(turn)["phases"]["answer_claim_binding"]["error_type"] == (
        "missing_evidence_brief"
    )
    generation = _generation_calls(seen)
    assert generation, "expected the blocked branch to still generate"
    assert generation[0].get("extra_body") == {"thinking": {"type": "disabled"}}


def test_block_without_attempt_budget_disables_answer_thinking(tmp_path) -> None:
    seen: list[dict[str, Any]] = []

    def chat_fn(*args: Any, **kwargs: Any) -> str:
        seen.append(dict(kwargs))
        return ANSWER

    service, repository = _service(tmp_path, chat_fn)
    reply, turn = _run_turn(
        service, repository, _command(rows=[_row()], allowed_attempts=0)
    )

    assert reply == RESEARCH_ANSWER_BLOCKED_COPY
    generation = _generation_calls(seen)
    assert generation[0].get("extra_body") == {"thinking": {"type": "disabled"}}
    binding = _audit(turn)["phases"]["answer_claim_binding"]
    assert binding["outcome"] == "budget_exhausted"


def test_block_disables_thinking_on_the_streaming_surface(tmp_path) -> None:
    seen: list[dict[str, Any]] = []

    def stream_chat(*args: Any, **kwargs: Any) -> Any:
        seen.append(dict(kwargs))
        return iter(["part", " two"])

    def chat_fn(*args: Any, **kwargs: Any) -> str:
        return ANSWER

    repository = RuntimeRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    dependencies = ChatDependencies(
        load_runtime_modes=lambda: RuntimeModes(
            memory_mode="preview", performance_mode="standard"
        ),
        read_memory_bundle=lambda context_mode: {},
        build_role_prompt=lambda role, **kwargs: f"role:{role}",
        route_request=lambda **kwargs: {
            "role": "nahida",
            "mode": "普通",
            "model_profile": "flash",
            "reason": "test",
        },
        retrieve_local_knowledge=lambda *args, **kwargs: _FakeRagResult(),
        build_messages=lambda **kwargs: [
            {"role": "system", "content": kwargs["role_prompt"]},
            {"role": "user", "content": kwargs["user_input"]},
        ],
        chat=chat_fn,
        stream_chat=stream_chat,
        chat_max_tokens=lambda performance_mode: 1000,
        resolve_web_tools=lambda *args, **kwargs: WebToolTrace(enabled=False),
        pedagogy_evaluation=PedagogyEvaluationService(),
    )
    service = ChatService(repository, dependencies)
    prepared = service.start_turn(_command(rows=[]))
    list(service.stream(prepared))

    assert seen and seen[0].get("extra_body") == {"thinking": {"type": "disabled"}}


def test_substantive_answer_keeps_production_thinking_default(tmp_path) -> None:
    """Gate != BLOCK must never inherit the blocked-branch reasoning policy."""

    seen: list[dict[str, Any]] = []

    def chat_fn(*args: Any, **kwargs: Any) -> str:
        seen.append(dict(kwargs))
        if kwargs.get("task_name") == "answer_claim_binding":
            return _binding_payload([_segment_entry("s1", support=(EVIDENCE_ID,))])
        return CANDIDATE

    service, repository = _service(tmp_path, chat_fn)
    reply, _turn = _run_turn(service, repository, _command(rows=[_row()]))

    assert reply == CANDIDATE
    generation = _generation_calls(seen)
    assert generation
    assert generation[0].get("extra_body") is None


def test_bounded_policy_flag_applies_thinking_off_to_gate_pass_answers(
    tmp_path, monkeypatch
) -> None:
    """§40c diagnostic override: gate-pass answers run bounded thinking-off."""

    monkeypatch.setenv("RESEARCH_ANSWER_BOUNDED_POLICY", "on")
    seen: list[dict[str, Any]] = []

    def chat_fn(*args: Any, **kwargs: Any) -> str:
        seen.append(dict(kwargs))
        if kwargs.get("task_name") == "answer_claim_binding":
            return _binding_payload([_segment_entry("s1", support=(EVIDENCE_ID,))])
        return CANDIDATE

    service, repository = _service(tmp_path, chat_fn)
    reply, _turn = _run_turn(service, repository, _command(rows=[_row()]))

    assert reply == CANDIDATE
    generation = _generation_calls(seen)
    assert generation
    assert generation[0].get("extra_body") == {"thinking": {"type": "disabled"}}
    binding = [
        call for call in seen if call.get("task_name") == "answer_claim_binding"
    ]
    assert binding
    assert binding[0].get("extra_body") == {"thinking": {"type": "disabled"}}


def test_consistency_gate_flags_evidence_denial_despite_valid_binding(
    tmp_path, monkeypatch
) -> None:
    """§40c: an answer that denies evidence must not publish over a supports ledger."""

    monkeypatch.setenv("RESEARCH_ANSWER_CONSISTENCY_GATE", "on")

    def chat_fn(*args: Any, **kwargs: Any) -> str:
        if kwargs.get("task_name") == "answer_claim_binding":
            return _binding_payload([_segment_entry("s1", support=(EVIDENCE_ID,))])
        return "本轮没有任何证据可以支持该结论。"

    service, repository = _service(tmp_path, chat_fn)
    reply, turn = _run_turn(service, repository, _command(rows=[_row()]))

    assert reply == "联网检索结果未能通过证据核验，本次回答未发布基于联网来源的结论。"
    audit = turn.rag_snapshot.get("answer_validation_audit") or {}
    binding_phase = (audit.get("phases") or {}).get("answer_claim_binding") or {}
    assert binding_phase.get("outcome") == "rejected"
    assert str(binding_phase.get("error_type") or "").startswith("consistency_failed")


def test_consistency_gate_publishes_clean_answer(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("RESEARCH_ANSWER_CONSISTENCY_GATE", "on")

    def chat_fn(*args: Any, **kwargs: Any) -> str:
        if kwargs.get("task_name") == "answer_claim_binding":
            return _binding_payload([_segment_entry("s1", support=(EVIDENCE_ID,))])
        return CANDIDATE

    service, repository = _service(tmp_path, chat_fn)
    reply, turn = _run_turn(service, repository, _command(rows=[_row()]))

    assert reply == CANDIDATE
    consistency = turn.rag_snapshot.get("answer_consistency") or {}
    assert consistency.get("ok") is True
    assert consistency.get("codes") == []
