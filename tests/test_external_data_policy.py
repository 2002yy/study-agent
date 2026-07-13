from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.application.chat_service import ChatDependencies
from src.application.policy_chat_service import (
    ExternalDataPolicyChatService,
    PolicyChatCommand,
)
from src.external_data_policy import decide_external_data
from src.infrastructure.sqlite.database import RuntimeDatabase
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


def _service(tmp_path: Path):
    captured: dict[str, Any] = {
        "web_calls": 0,
        "rag_enabled": [],
        "messages": [],
    }

    def retrieve(_query: str, **kwargs):
        captured["rag_enabled"].append(kwargs["enabled"])
        return _RagResult(enabled=bool(kwargs["enabled"]))

    def resolve_web(_query: str, **kwargs):
        captured["web_calls"] += 1
        captured["web_context"] = kwargs["conversation_context"]
        return WebToolTrace(
            calls=(
                {
                    "name": "web_search",
                    "arguments": {"query": "database index"},
                    "result": {
                        "results": [
                            {
                                "title": "Official docs",
                                "url": "https://example.test/docs",
                            }
                        ]
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
            _FailingSemanticEvaluator()
        ),
        build_role_prompt=lambda *_args, **_kwargs: "ROLE",
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
    assert message_args["chat_history"] == [
        {"role": "user", "content": "RECENT HISTORY"}
    ]
    assert message_args["memory_bundle"] == {"summary": "PRIVATE MEMORY"}
    assert "LOCAL SECRET EVIDENCE" in message_args["rag_context"]
    assert "Official docs" in message_args["rag_context"]
    assert prepared.route["external_data_policy"]["web_allowed"] is True
    assert prepared.web_context_used is True


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
    assert prepared.route["task_contract"]["source_policy"] == "web_only"
    assert prepared.rag["result_count"] == 0
