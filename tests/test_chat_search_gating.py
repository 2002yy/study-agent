"""CL-M3-S2-C1b: permission is not an instruction to search.

`quick_answer` keeps `local_and_web` (option B). The source policy says which
sources a turn *may* use; a separate deterministic gate decides whether this
turn actually runs the web agent. These tests drive the real `ChatService` and
the real production subclass (`ExternalDataPolicyChatService`), with a spy where
the network call would be.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.application.chat_service import ChatCommand, ChatDependencies, ChatService
from src.application.policy_chat_service import (
    ExternalDataPolicyChatService,
    PolicyChatCommand,
)
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.mode_manager import RuntimeModes
from src.repositories.runtime_repository import RuntimeRepository
from src.task_contract import (
    TaskAwarePedagogyEngine,
    TaskAwarePedagogyEvaluationService,
    route_request_with_task_contract,
)
from src.tools.web_agent import WebToolTrace

STATIC_QUESTION = "Java 的 JVM 是什么？它和 JRE 有什么区别？"
TODAY_NEWS = "今天的 DeepSeek 新闻有哪些？"
EXPLICIT_LOOKUP = "帮我查一下最新 JVM 官方文档"
NO_WEB_RESEARCH = "不要联网，帮我查一下最新 JVM 文档"
EXPLICIT_RESEARCH = "帮我研究 Rust 和 Go，并核对官方资料"


class _Rag:
    def to_dict(self) -> dict[str, Any]:
        return {
            "status": "found",
            "context": "LOCAL CONTEXT",
            "result_count": 1,
            "results": [],
        }


def _web_trace() -> WebToolTrace:
    return WebToolTrace(
        calls=(
            {
                "name": "web_search",
                "arguments": {"query": "deepseek news"},
                "result": {
                    "status": "ok",
                    "results": [
                        {"title": "Official docs", "url": "https://example.test/docs"}
                    ],
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


@dataclass
class _BaseHarness:
    service: ChatService
    repository: RuntimeRepository
    captured: dict[str, Any]


def _base_service(tmp_path: Path, *, route=None) -> _BaseHarness:
    captured: dict[str, Any] = {"web_calls": 0, "research_intent": []}

    def resolve_web(_query: str, **kwargs):
        captured["web_calls"] += 1
        captured["research_intent"].append(kwargs["research_intent"])
        return _web_trace()

    repository = RuntimeRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    dependencies = ChatDependencies(
        load_runtime_modes=lambda: RuntimeModes(performance_mode="fast"),
        read_memory_bundle=lambda _mode: {},
        build_role_prompt=lambda role, **_kwargs: f"role:{role}",
        route_request=route or route_request_with_task_contract,
        retrieve_local_knowledge=lambda *_args, **_kwargs: _Rag(),
        build_messages=lambda **kwargs: [
            {"role": "system", "content": kwargs["rag_context"]},
            {"role": "user", "content": kwargs["user_input"]},
        ],
        chat=lambda *_args, **_kwargs: "reply",
        chat_max_tokens=lambda _mode: 1000,
        resolve_web_tools=resolve_web,
    )
    return _BaseHarness(ChatService(repository, dependencies), repository, captured)


@dataclass
class _PolicyHarness:
    service: ExternalDataPolicyChatService
    captured: dict[str, Any]


def _policy_service(tmp_path: Path) -> _PolicyHarness:
    captured: dict[str, Any] = {"web_calls": 0, "research_intent": []}

    def resolve_web(_query: str, **kwargs):
        captured["web_calls"] += 1
        captured["research_intent"].append(kwargs["research_intent"])
        return _web_trace()

    repository = RuntimeRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    dependencies = ChatDependencies(
        load_runtime_modes=lambda: RuntimeModes(performance_mode="fast"),
        read_memory_bundle=lambda _mode: {},
        build_role_prompt=lambda role, **_kwargs: f"role:{role}",
        route_request=route_request_with_task_contract,
        retrieve_local_knowledge=lambda *_args, **_kwargs: _Rag(),
        build_messages=lambda **kwargs: [
            {"role": "system", "content": kwargs["rag_context"]},
            {"role": "user", "content": kwargs["user_input"]},
        ],
        chat=lambda *_args, **_kwargs: "reply",
        chat_max_tokens=lambda _mode: 1000,
        resolve_web_tools=resolve_web,
        pedagogy_engine=TaskAwarePedagogyEngine(),
        pedagogy_evaluation=TaskAwarePedagogyEvaluationService(),
    )
    return _PolicyHarness(
        ExternalDataPolicyChatService(repository, dependencies),
        captured,
    )


# -- base ChatService ---------------------------------------------------------------


def test_a_static_question_does_not_search_but_keeps_the_permission(tmp_path):
    harness = _base_service(tmp_path)

    prepared = harness.service.start_turn(ChatCommand(user_input=STATIC_QUESTION))

    assert harness.captured["web_calls"] == 0
    assert prepared.route["task_contract"]["task_intent"] == "quick_answer"
    # Option B: the source policy is untouched.
    assert prepared.route["task_contract"]["source_policy"] == "local_and_web"
    assert prepared.rag["web_tools"]["used"] is False
    assert prepared.rag["web_tools"]["used_sources"] == []
    assert prepared.rag["web_tools"]["policy_reason"] == "task_does_not_require_web"
    assert prepared.rag["result_count"] == 1  # local knowledge still used


def test_todays_news_enters_the_search_path(tmp_path):
    harness = _base_service(tmp_path)

    prepared = harness.service.start_turn(ChatCommand(user_input=TODAY_NEWS))

    assert harness.captured["web_calls"] == 1
    assert harness.captured["research_intent"] == [True]
    assert prepared.route["task_contract"]["task_intent"] == "research"
    assert prepared.rag["web_tools"]["used"] is True
    assert prepared.rag["web_tools"]["policy_reason"] == "task_requires_web"
    assert prepared.rag["web_tools"]["used_sources"][0]["url"].endswith("/docs")


def test_an_explicit_lookup_is_allowed_to_search(tmp_path):
    harness = _base_service(tmp_path)

    prepared = harness.service.start_turn(ChatCommand(user_input=EXPLICIT_LOOKUP))

    assert harness.captured["web_calls"] == 1
    assert prepared.route["task_contract"]["task_intent"] == "research"


def test_no_web_instruction_wins_over_a_research_request(tmp_path):
    harness = _base_service(tmp_path)

    prepared = harness.service.start_turn(ChatCommand(user_input=NO_WEB_RESEARCH))

    assert harness.captured["web_calls"] == 0
    assert prepared.rag["web_tools"]["used"] is False
    assert prepared.rag["web_tools"]["used_sources"] == []
    assert prepared.rag["web_tools"]["policy_reason"] == "web_disabled_by_user"
    # The contract can still be `research`; the refusal is recorded, not hidden.
    assert prepared.route["task_contract"]["task_intent"] == "research"


def test_deep_mode_cannot_override_the_no_web_instruction(tmp_path):
    harness = _base_service(tmp_path)

    prepared = harness.service.start_turn(
        ChatCommand(user_input=EXPLICIT_RESEARCH + "，但不要联网", performance_mode="deep")
    )

    assert harness.captured["web_calls"] == 0
    assert prepared.rag["web_tools"]["policy_reason"] == "web_disabled_by_user"


def test_the_turn_entry_supplies_a_contract_even_from_the_legacy_router(tmp_path):
    """P1: the host's router may be the legacy one; the turn entry still owns a
    complete, persisted contract so the gate has something to read."""

    harness = _base_service(
        tmp_path,
        route=lambda **_kwargs: {
            "role": "nahida",
            "mode": "普通",
            "model_profile": "flash",
            "reason": "legacy",
        },
    )

    prepared = harness.service.start_turn(ChatCommand(user_input=STATIC_QUESTION))

    contract = prepared.route["task_contract"]
    assert contract["task_intent"] == "quick_answer"
    stored = harness.repository.get_chat_turn(prepared.turn.id)
    assert stored is not None
    assert stored.route_snapshot["task_contract"]["task_intent"] == "quick_answer"
    assert harness.captured["web_calls"] == 0


# -- production subclass: ExternalDataPolicyChatService ------------------------------


def test_the_production_service_does_not_search_a_static_question(tmp_path):
    harness = _policy_service(tmp_path)

    prepared = harness.service.start_turn(
        PolicyChatCommand(
            user_input=STATIC_QUESTION,
            thread_id="c1b-static",
            web_policy="auto",
            cloud_context_policy="allow_local_evidence",
        )
    )

    assert harness.captured["web_calls"] == 0
    assert prepared.route["external_data_policy"]["web_allowed"] is True
    assert prepared.rag["web_tools"]["policy_reason"] == "task_does_not_require_web"
    assert prepared.rag["web_tools"]["used_sources"] == []
    assert prepared.rag["result_count"] == 1


def test_the_production_service_searches_todays_news(tmp_path):
    harness = _policy_service(tmp_path)

    prepared = harness.service.start_turn(
        PolicyChatCommand(
            user_input=TODAY_NEWS,
            thread_id="c1b-news",
            web_policy="auto",
            cloud_context_policy="allow_local_evidence",
        )
    )

    assert harness.captured["web_calls"] == 1
    assert harness.captured["research_intent"] == [True]
    assert prepared.route["external_data_policy"]["web_allowed"] is True
    assert prepared.rag["web_tools"]["policy_reason"] == "task_requires_web"
    assert prepared.rag["web_tools"]["used_sources"][0]["url"].endswith("/docs")


def test_the_production_service_honours_no_web_inside_deep_mode(tmp_path):
    harness = _policy_service(tmp_path)

    prepared = harness.service.start_turn(
        PolicyChatCommand(
            user_input=NO_WEB_RESEARCH,
            thread_id="c1b-no-web",
            performance_mode="deep",
            web_policy="auto",
            cloud_context_policy="allow_local_evidence",
        )
    )

    assert harness.captured["web_calls"] == 0
    assert prepared.rag["web_tools"]["used"] is False
    assert prepared.rag["web_tools"]["policy_reason"] == "web_disabled_by_user"
    assert prepared.rag["web_tools"]["used_sources"] == []


def test_a_short_research_follow_up_still_resumes(tmp_path):
    """Continuity is a reason to search: "快去" after an explicit research ask."""

    harness = _policy_service(tmp_path)

    prepared = harness.service.start_turn(
        PolicyChatCommand(
            user_input="快去",
            thread_id="c1b-resume",
            chat_history=[{"role": "user", "content": "请联网研究：opus5.5"}],
            web_policy="auto",
        )
    )

    assert harness.captured["web_calls"] == 1
    assert prepared.rag["web_tools"]["policy_reason"] == "task_requires_web"


def test_a_short_follow_up_without_a_research_lead_does_not_search(tmp_path):
    harness = _policy_service(tmp_path)

    prepared = harness.service.start_turn(
        PolicyChatCommand(
            user_input="快去",
            thread_id="c1b-resume-empty",
            chat_history=[{"role": "user", "content": "数据库索引是什么？"}],
            web_policy="auto",
        )
    )

    assert harness.captured["web_calls"] == 0
    assert prepared.rag["web_tools"]["policy_reason"] == "task_does_not_require_web"
