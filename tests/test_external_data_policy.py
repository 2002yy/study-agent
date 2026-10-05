from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from src.application.chat_service import ChatDependencies
from src.application.policy_chat_service import (
    ExternalDataPolicyChatService,
    PolicyChatCommand,
)
from src.external_data_policy import decide_external_data
from src.domain.runtime_entities import ChatThread
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.pedagogy.evaluation import SemanticEvaluation
from src.repositories.runtime_repository import RuntimeRepository
from src.task_contract import (
    TaskAwarePedagogyEngine,
    TaskAwarePedagogyEvaluationService,
    route_request_with_task_contract,
)
from src.tools.web_agent import WebToolTrace


@dataclass
class _RagResult:
    enabled: bool

    def to_dict(self) -> dict[str, Any]:
        if not self.enabled:
            return {
                "status": "disabled",
                "query": "",
                "retrieval_mode": "hybrid",
                "reason": "disabled",
                "context": "",
                "sources": "",
                "result_count": 0,
                "results": [],
                "debug": {},
                "attempts": [],
                "rewritten_query": "",
            }
        return {
            "status": "found",
            "query": "database index",
            "retrieval_mode": "hybrid",
            "reason": "",
            "context": "LOCAL SECRET EVIDENCE",
            "sources": "private-notes.md",
            "result_count": 1,
            "results": [
                {
                    "score": 0.9,
                    "chunk": {
                        "chunk_id": "chunk-1",
                        "title": "Private notes",
                        "source_path": "private-notes.md",
                        "start_line": 1,
                        "end_line": 2,
                        "text": "LOCAL SECRET EVIDENCE",
                    },
                }
            ],
            "debug": {},
            "attempts": [],
            "rewritten_query": "",
        }


class _FailingSemanticEvaluator:
    def evaluate(self, **kwargs):
        raise AssertionError("semantic evaluation must not run for quick answers")


def _service(
    tmp_path: Path,
    *,
    semantic_evaluator=None,
    retrieve_override=None,
    web_trace: WebToolTrace | None = None,
):
    captured: dict[str, Any] = {
        "web_calls": 0,
        "rag_enabled": [],
        "messages": [],
    }

    def retrieve(_query: str, **kwargs):
        captured["rag_enabled"].append(kwargs["enabled"])
        if retrieve_override is not None:
            return retrieve_override(_query, **kwargs)
        return _RagResult(enabled=bool(kwargs["enabled"]))

    def resolve_web(_query: str, **kwargs):
        captured["web_calls"] += 1
        captured["web_context"] = kwargs["conversation_context"]
        captured["owner_thread_id"] = kwargs["owner_thread_id"]
        captured["owner_turn_id"] = kwargs["owner_turn_id"]
        captured["research_intent"] = kwargs["research_intent"]
        if web_trace is not None:
            return web_trace
        return WebToolTrace(
            calls=(
                {
                    "name": "web_search",
                    "arguments": {"query": "database index"},
                    "result": {
                        "status": "ok",
                        "results": [
                            {
                                "title": "Official docs",
                                "url": "https://example.test/docs",
                            }
                        ]
                    },
                },
                {
                    "name": "web_read",
                    "arguments": {"url": "https://example.test/docs"},
                    "result": {
                        "ok": True,
                        "url": "https://example.test/docs",
                        "content": "Official docs full page",
                    },
                },
            )
        )

    def build_messages(**kwargs):
        captured["messages"].append(kwargs)
        return [
            {"role": "system", "content": kwargs["rag_context"]},
            {"role": "user", "content": kwargs["user_input"]},
        ]

    repository = RuntimeRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    dependencies = ChatDependencies(
        route_request=route_request_with_task_contract,
        read_memory_bundle=lambda _mode: {"summary": "PRIVATE MEMORY"},
        retrieve_local_knowledge=retrieve,
        resolve_web_tools=resolve_web,
        build_messages=build_messages,
        pedagogy_engine=TaskAwarePedagogyEngine(),
        pedagogy_evaluation=TaskAwarePedagogyEvaluationService(
            semantic_evaluator or _FailingSemanticEvaluator()
        ),
        build_role_prompt=lambda *_args, **_kwargs: "ROLE",
        stream_chat=lambda *_args, **_kwargs: iter(("ok",)),
    )
    return ExternalDataPolicyChatService(repository, dependencies), captured


def test_policy_decision_requires_consent_in_ask_mode():
    denied = decide_external_data(
        web_policy="ask",
        web_consent=False,
        cloud_context_policy="recent_chat",
        task_source_policy="local_and_web",
    )
    allowed = decide_external_data(
        web_policy="ask",
        web_consent=True,
        cloud_context_policy="recent_chat",
        task_source_policy="local_and_web",
    )

    assert denied.web_allowed is False
    assert denied.reason == "web_consent_required"
    assert allowed.web_allowed is True
    assert allowed.history_allowed is True
    assert allowed.memory_allowed is False


def test_question_only_blocks_web_history_memory_and_local_evidence(tmp_path):
    service, captured = _service(tmp_path)

    prepared = service.start_turn(
        PolicyChatCommand(
            user_input="数据库索引是什么？",
            thread_id="chat-private",
            chat_history=[{"role": "user", "content": "PRIVATE HISTORY"}],
            rag_enabled=True,
            web_policy="off",
            cloud_context_policy="question_only",
        )
    )

    message_args = captured["messages"][0]
    assert captured["web_calls"] == 0
    assert captured["rag_enabled"] == [True]
    assert message_args["chat_history"] == []
    assert message_args["memory_bundle"] == {}
    assert "LOCAL SECRET EVIDENCE" not in message_args["rag_context"]
    assert prepared.rag["result_count"] == 1
    assert prepared.route["external_data_policy"]["web_allowed"] is False
    assert prepared.route["external_data_policy"]["local_evidence_to_model_allowed"] is False
    execution = prepared.rag["external_data_policy"]
    assert execution["web_search_performed"] is False
    assert execution["history_sent_to_model"] is False
    assert execution["history_message_count"] == 0
    assert execution["learning_state_sent_to_model"] is False
    assert execution["memory_context_sent_to_model"] is False
    assert execution["local_evidence_sent_to_model"] is False
    assert execution["local_evidence_chunk_count"] == 0


def test_recent_chat_keeps_history_but_blocks_memory_and_local_evidence(tmp_path):
    service, captured = _service(tmp_path)

    service.start_turn(
        PolicyChatCommand(
            user_input="数据库索引是什么？",
            thread_id="chat-recent",
            chat_history=[{"role": "user", "content": "RECENT HISTORY"}],
            rag_enabled=True,
            web_policy="off",
            cloud_context_policy="recent_chat",
        )
    )

    message_args = captured["messages"][0]
    assert message_args["chat_history"] == [
        {"role": "user", "content": "RECENT HISTORY"}
    ]
    assert message_args["memory_bundle"] == {}
    assert "LOCAL SECRET EVIDENCE" not in message_args["rag_context"]


def test_auto_with_local_evidence_allows_full_context(tmp_path):
    service, captured = _service(tmp_path)

    prepared = service.start_turn(
        PolicyChatCommand(
            user_input="数据库索引是什么？",
            thread_id="chat-full",
            chat_history=[{"role": "user", "content": "RECENT HISTORY"}],
            rag_enabled=True,
            web_policy="auto",
            cloud_context_policy="allow_local_evidence",
        )
    )

    message_args = captured["messages"][0]
    assert captured["web_calls"] == 1
    assert captured["web_context"] == "user: RECENT HISTORY"
    assert captured["owner_thread_id"] == "chat-full"
    assert captured["owner_turn_id"] == prepared.turn.id
    assert message_args["chat_history"] == [
        {"role": "user", "content": "RECENT HISTORY"}
    ]
    assert message_args["memory_bundle"] == {"summary": "PRIVATE MEMORY"}
    assert "LOCAL SECRET EVIDENCE" in message_args["rag_context"]
    assert "Official docs" in message_args["rag_context"]
    assert prepared.route["external_data_policy"]["web_allowed"] is True
    execution = prepared.rag["external_data_policy"]
    assert execution == prepared.route["external_data_policy"]
    assert execution["web_search_performed"] is True
    assert execution["history_sent_to_model"] is False
    assert execution["learning_state_sent_to_model"] is False
    assert execution["memory_context_sent_to_model"] is False
    assert execution["local_evidence_sent_to_model"] is False

    assert list(service.stream(prepared)) == ["ok"]
    execution = prepared.rag["external_data_policy"]
    assert execution["history_sent_to_model"] is True
    assert execution["history_message_count"] == 1
    assert execution["learning_state_sent_to_model"] is True
    assert execution["memory_context_sent_to_model"] is True
    assert execution["local_evidence_sent_to_model"] is True
    assert execution["local_evidence_chunk_count"] == 1
    assert prepared.web_context_used is True
    answer_call = next(
        call
        for call in execution["external_calls"]
        if call["purpose"] == "answer_generation"
    )
    assert answer_call["status"] == "attempted"
    assert answer_call["provider"]
    stored = service.repository.get_chat_turn(prepared.turn.id)
    assert stored is not None
    assert stored.rag_snapshot["external_data_policy"] == execution


@pytest.mark.parametrize("cloud_context_policy", ["question_only", "recent_chat"])
def test_restricted_context_blocks_semantic_evaluation_before_provider_call(
    tmp_path, cloud_context_policy
):
    class RecordingSemanticEvaluator:
        provider_name = "external-test"

        def __init__(self):
            self.calls = []

        def evaluate(self, **kwargs):
            self.calls.append(kwargs)
            raise AssertionError("restricted semantic review crossed the policy boundary")

    evaluator = RecordingSemanticEvaluator()
    service, _captured = _service(tmp_path, semantic_evaluator=evaluator)
    service.repository.create_chat_thread(
        ChatThread(
            id="chat-semantic-private",
            learning_state={
                "objective": "PRIVATE OBJECTIVE",
                "protocol": "socratic_rediscovery",
                "payload": {"expected_concepts": ["PRIVATE EXPECTED CONCEPT"]},
            },
        )
    )

    prepared = service.start_turn(
        PolicyChatCommand(
            user_input="所以每轮范围减半，因为剩余规模变成之前的一半。",
            thread_id="chat-semantic-private",
            task_intent="learn",
            cloud_context_policy=cloud_context_policy,
            web_policy="off",
        )
    )

    assert evaluator.calls == []
    assert prepared.learner_evaluation.final_decision == "needs_semantic_review"
    assert prepared.learner_evaluation.semantic_review_status == "blocked_by_policy"
    semantic_call = next(
        call
        for call in prepared.rag["external_data_policy"]["external_calls"]
        if call["purpose"] == "semantic_evaluation"
    )
    assert semantic_call == {
        "call_id": "semantic_evaluation:1",
        "purpose": "semantic_evaluation",
        "provider": "external-test",
        "data_categories": [
            "learner_input",
            "learning_objective",
            "learning_protocol",
            "expected_concepts",
            "evidence_refs",
        ],
        "data_counts": {
            "learner_input": 1,
            "learning_objective": 1,
            "learning_protocol": 1,
            "expected_concepts": 1,
            "evidence_refs": 0,
        },
        "status": "blocked_by_policy",
        "result": "blocked_by_policy",
    }
    assert prepared.rag["external_data_policy"]["learning_state_sent_to_model"] is False


def test_allowed_context_calls_semantic_provider_and_audits_actual_categories(tmp_path):
    class RecordingSemanticEvaluator:
        provider_name = "external-test"

        def __init__(self):
            self.calls = []

        def evaluate(self, **kwargs):
            self.calls.append(kwargs)
            return SemanticEvaluation(
                reasoning_complete=True,
                transfer_ready=True,
                confidence=0.9,
            )

    evaluator = RecordingSemanticEvaluator()
    service, _captured = _service(tmp_path, semantic_evaluator=evaluator)
    service.repository.create_chat_thread(
        ChatThread(
            id="chat-semantic-allowed",
            learning_state={
                "objective": "PRIVATE OBJECTIVE",
                "protocol": "socratic_rediscovery",
                "payload": {"expected_concepts": ["PRIVATE EXPECTED CONCEPT"]},
            },
        )
    )

    prepared = service.start_turn(
        PolicyChatCommand(
            user_input="所以每轮范围减半，因为剩余规模变成之前的一半。",
            thread_id="chat-semantic-allowed",
            task_intent="learn",
            cloud_context_policy="allow_local_evidence",
            web_policy="off",
        )
    )

    assert evaluator.calls[0]["objective"] == "PRIVATE OBJECTIVE"
    semantic_call = next(
        call
        for call in prepared.rag["external_data_policy"]["external_calls"]
        if call["purpose"] == "semantic_evaluation"
    )
    assert semantic_call["status"] == "completed"
    assert semantic_call["result"] == "completed"
    assert semantic_call["data_counts"]["expected_concepts"] == 1
    assert prepared.rag["external_data_policy"]["learning_state_sent_to_model"] is True


def test_chat_turn_audits_policy_blocked_external_query_embedding(tmp_path, monkeypatch):
    from src.rag.service import index_documents
    from src.tools.local_knowledge import retrieve_local_knowledge

    index_path = tmp_path / "rag.json"
    document = tmp_path / "private.md"
    document.write_text("private database index evidence", encoding="utf-8")
    index_documents([document], index_path=index_path, max_chars=200, overlap_chars=0)
    monkeypatch.setenv("RAG_VECTOR_BACKEND", "chroma")
    monkeypatch.setenv("RAG_EMBEDDING_PROVIDER", "openai")
    monkeypatch.setenv("RAG_EMBEDDING_MODEL", "text-embedding-3-small")

    def retrieve(query: str, **kwargs):
        return retrieve_local_knowledge(query, index_path=index_path, **kwargs)

    service, _captured = _service(tmp_path, retrieve_override=retrieve)
    prepared = service.start_turn(
        PolicyChatCommand(
            user_input="请根据本地资料解释数据库索引",
            thread_id="chat-query-embedding-private",
            task_intent="quick_answer",
            rag_enabled=True,
            rag_retrieval_mode="backend_vector",
            web_policy="off",
            cloud_context_policy="question_only",
        )
    )

    assert prepared.rag["reason"] == "external_embedding_blocked_by_policy"
    query_call = next(
        call
        for call in prepared.rag["external_data_policy"]["external_calls"]
        if call["purpose"] == "query_embedding"
    )
    assert query_call["status"] == "blocked_by_policy"
    assert query_call["provider"] == "openai:text-embedding-3-small"
    assert query_call["data_counts"] == {"retrieval_query": 1}


def test_recovered_research_context_keeps_run_provenance_in_turn_evidence(tmp_path):
    service, captured = _service(tmp_path)

    prepared = service.start_turn(
        PolicyChatCommand(
            user_input="Use the recovered sources",
            thread_id="chat-recovered-research",
            task_intent="quick_answer",
            web_context="RECOVERED RESEARCH SOURCE BLOCK",
            web_context_run_id="research-recovered-1",
            web_policy="auto",
            cloud_context_policy="allow_local_evidence",
        )
    )

    assert "RECOVERED RESEARCH SOURCE BLOCK" in captured["messages"][0]["rag_context"]
    assert prepared.rag["web_context"] == {
        "used": True,
        "run_id": "research-recovered-1",
        "source": "research_run",
    }
    stored = service.repository.get_chat_turn(prepared.turn.id)
    assert stored is not None
    assert stored.rag_snapshot["web_context"]["run_id"] == "research-recovered-1"


def test_research_task_does_not_query_local_knowledge(tmp_path):
    service, captured = _service(tmp_path)

    prepared = service.start_turn(
        PolicyChatCommand(
            user_input="联网看看gpt5.6sol",
            thread_id="chat-research",
            rag_enabled=True,
            web_policy="auto",
            cloud_context_policy="allow_local_evidence",
        )
    )

    assert captured["rag_enabled"] == [False]
    assert captured["web_calls"] == 1
    assert captured["research_intent"] is True
    assert prepared.route["task_contract"]["source_policy"] == "web_only"
    assert prepared.rag["result_count"] == 0


@pytest.mark.parametrize("context_policy,expected", [("question_only", False), ("recent_chat", True)])
def test_research_query_lead_obeys_history_permission(tmp_path, context_policy, expected):
    service, captured = _service(tmp_path)
    service.start_turn(PolicyChatCommand(
        user_input="快去", thread_id=f"research-lead-{context_policy}",
        chat_history=[{"role": "user", "content": "请联网研究：opus5.5"}],
        web_policy="auto", cloud_context_policy=context_policy,
    ))
    assert captured["web_calls"] == 1
    assert ("Research query lead: opus5.5" in captured["web_context"]) is expected


@pytest.mark.parametrize("web_policy,consent", [("off", True), ("ask", False)])
def test_research_recovery_cannot_override_network_permission(tmp_path, web_policy, consent):
    service, captured = _service(tmp_path)
    service.start_turn(PolicyChatCommand(
        user_input="请联网研究：opus5.5", thread_id=f"research-permission-{web_policy}",
        web_policy=web_policy, web_consent=consent, cloud_context_policy="recent_chat",
    ))
    assert captured["web_calls"] == 0


def test_explicit_research_without_any_tool_call_is_forced_to_report_gap(tmp_path):
    service, captured = _service(tmp_path, web_trace=WebToolTrace())

    prepared = service.start_turn(
        PolicyChatCommand(
            user_input="请联网研究：opus5",
            thread_id="chat-research-no-tools",
            web_policy="auto",
            cloud_context_policy="allow_local_evidence",
        )
    )

    assert prepared.rag["web_tools"]["used"] is False
    rag_context = captured["messages"][0]["rag_context"]
    assert "本轮没有取得任何已读取正文或结构化一手证据" in rag_context
    assert "不得依据搜索摘要或模型既有知识输出具体事实" in rag_context


def test_explicit_quick_answer_override_controls_the_whole_turn(tmp_path):
    service, captured = _service(tmp_path)

    prepared = service.start_turn(
        PolicyChatCommand(
            user_input="联网看看最新数据库消息",
            thread_id="chat-explicit-quick",
            task_intent="quick_answer",
            rag_enabled=True,
            web_policy="off",
            cloud_context_policy="allow_local_evidence",
        )
    )

    contract = prepared.route["task_contract"]
    assert contract["task_intent"] == "quick_answer"
    assert contract["explicit_override"] is True
    assert contract["reason"] == "explicit_task_override"
    assert captured["rag_enabled"] == [True]
    assert captured["web_calls"] == 0
    assert prepared.learner_evaluation.final_decision == "not_applicable"
    assert "task_intent:quick_answer" in prepared.pedagogy_plan.constraints
    assert prepared.turn.pedagogy_snapshot["task_contract"] == contract


def test_continuation_reuses_original_task_contract(tmp_path):
    service, _ = _service(tmp_path)
    first = service.start_turn(
        PolicyChatCommand(
            user_input="联网看看最新数据库消息",
            thread_id="chat-contract-continuation",
            task_intent="research",
            web_policy="off",
        )
    )
    service.interrupt_turn(first, "partial")

    continuation = service.start_turn(
        PolicyChatCommand(
            user_input="带我系统学习数据库索引",
            thread_id="chat-contract-continuation",
            task_intent="learn",
            continuation_of_turn_id=first.turn.id,
            turn_id=first.turn.id,
            partial_reply="partial",
            web_policy="off",
        )
    )

    assert continuation.route["task_contract"] == first.route["task_contract"]
    assert continuation.route["task_contract"]["task_intent"] == "research"


def test_retry_reuses_parent_task_contract(tmp_path):
    service, _ = _service(tmp_path)
    first = service.start_turn(
        PolicyChatCommand(
            user_input="联网看看最新数据库消息",
            thread_id="chat-contract-retry",
            task_intent="quick_answer",
            web_policy="off",
        )
    )
    service.fail_turn(first)

    retried = service.start_turn(
        PolicyChatCommand(
            user_input="带我系统学习数据库索引",
            thread_id="chat-contract-retry",
            task_intent="learn",
            retry_of_turn_id=first.turn.id,
            web_policy="off",
        )
    )

    assert retried.turn.id != first.turn.id
    assert retried.route["task_contract"] == first.route["task_contract"]
    assert retried.route["task_contract"]["task_intent"] == "quick_answer"


def test_ask_mode_does_not_treat_manual_web_context_as_consent(tmp_path):
    service, captured = _service(tmp_path)

    prepared = service.start_turn(
        PolicyChatCommand(
            user_input="数据库索引是什么？",
            thread_id="chat-ask-context",
            web_context="UNTRUSTED MANUAL WEB CONTEXT",
            web_policy="ask",
            web_consent=False,
            cloud_context_policy="recent_chat",
        )
    )

    message_args = captured["messages"][0]
    assert captured["web_calls"] == 0
    assert "UNTRUSTED MANUAL WEB CONTEXT" not in message_args["rag_context"]
    assert prepared.route["external_data_policy"]["web_allowed"] is False
    assert prepared.route["external_data_policy"]["reason"] == "web_consent_required"
    assert prepared.web_context_used is False
    assert prepared.rag["web_context"] == {
        "used": False,
        "run_id": "",
        "source": "manual",
    }


def test_server_rendered_publication_does_not_invent_answer_egress(tmp_path):
    service, _captured = _service(tmp_path)
    prepared = service.start_turn(
        PolicyChatCommand(
            user_input="FastAPI当前最新版本及发布日期",
            thread_id="chat-server-rendered-publication",
            task_intent="research",
            web_policy="auto",
            cloud_context_policy="allow_local_evidence",
        )
    )

    service.generate(prepared)

    execution = prepared.rag["external_data_policy"]
    assert prepared.route.get("answer_generation_calls", 0) == 0
    assert not any(
        call.get("purpose") == "answer_generation"
        for call in execution["external_calls"]
    )
    assert execution["history_sent_to_model"] is False
    assert execution["learning_state_sent_to_model"] is False
    assert execution["memory_context_sent_to_model"] is False
    assert execution["local_evidence_sent_to_model"] is False

    stored = service.repository.get_chat_turn(prepared.turn.id)
    assert stored is not None
    stored_execution = stored.rag_snapshot["external_data_policy"]
    assert not any(
        call.get("purpose") == "answer_generation"
        for call in stored_execution["external_calls"]
    )
