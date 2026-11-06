import asyncio
from dataclasses import replace
import json

import pytest

from src import llm_spend_guard as spend
from src.application.chat_service import ChatCommand, ChatDependencies, ChatService
from src.application.policy_chat_service import (
    ExternalDataPolicyChatService,
    PolicyChatCommand,
)
from src.domain.runtime_entities import ChatTurn
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.interactive_repair_budget import current_repair_budget
from src.mode_manager import RuntimeModes
from src.repositories.runtime_repository import RuntimeRepository
from src.task_contract import (
    route_request_with_task_contract,
    TaskAwarePedagogyEngine,
    TaskAwarePedagogyEvaluationService,
)
from src.tools.web_agent import WebToolTrace


@pytest.fixture
def setup_service(monkeypatch, tmp_path):
    from src import api

    monkeypatch.setattr(api, "FRONTEND_SETTINGS_PATH", tmp_path / "frontend.yaml")
    for key in (
        "STUDY_AGENT_SETTLEMENT_ADMISSION",
        "LLM_SPEND_CAP_CNY",
        "LLM_SPEND_DEFAULT_MAX_TOKENS",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("LLM_SPEND_EXPERIMENT_ID", "repair-approved")
    monkeypatch.setenv("LLM_SPEND_EXPERIMENT_CAP_CNY", "30")
    monkeypatch.setenv("LLM_SPEND_INPUT_CNY_PER_MTOK", "1")
    monkeypatch.setenv("LLM_SPEND_OUTPUT_CNY_PER_MTOK", "1")
    monkeypatch.setenv("LLM_EXPERIMENT_ALLOWED_MODELS", "priced-model")
    path = tmp_path / "runtime.db"
    monkeypatch.setenv("LLM_SPEND_LEDGER_DB", str(path))
    spend.reset_spend()
    repo = RuntimeRepository(RuntimeDatabase(path))
    repo.ensure_chat_thread("thread")
    source = {
        "type": "interactive",
        "id": "scene",
        "revision": 1,
        "title": "Scene",
        "summary": "3D",
        "html": "<p>saved source</p>",
        "capabilities": ["three"],
    }
    repo.add_chat_turn(
        ChatTurn(
            id="source",
            thread_id="thread",
            user_message="original",
            assistant_message="```study-ui\n" + json.dumps(source) + "\n```",
            status="completed",
        )
    )
    spend._ledger().ensure_experiment(
        "repair-approved",
        cap_micros=30000000,
        pricing_fingerprint=spend._pricing_fingerprint(),
        now="now",
    )
    events = []

    def send(messages, **kwargs):
        budget = current_repair_budget()
        assert budget is not None and budget.component_id == "scene"
        events.append("send")
        spend.reserve_call(prompt_chars=100, max_tokens=100, model="priced-model")
        kwargs["on_completion"]("stop")
        return "A final answer."

    def stream(messages, **kwargs):
        yield send(messages, **kwargs)

    async def stream_async(messages, **kwargs):
        yield send(messages, **kwargs)

    class Rag:
        def to_dict(self):
            return {
                "status": "disabled",
                "context": "",
                "results": [],
                "result_count": 0,
            }

    deps = replace(
        ChatDependencies(),
        load_runtime_modes=lambda: RuntimeModes(performance_mode="fast"),
        read_memory_bundle=lambda _: {},
        build_role_prompt=lambda *a, **kw: "role",
        retrieve_local_knowledge=lambda *a, **kw: Rag(),
        resolve_web_tools=lambda *a, **kw: WebToolTrace(enabled=False),
        route_request=route_request_with_task_contract,
        pedagogy_engine=TaskAwarePedagogyEngine(),
        pedagogy_evaluation=TaskAwarePedagogyEvaluationService(),
        chat=send,
        stream_chat=stream,
        async_stream_chat=stream_async,
    )

    def make(policy):
        cls = ExternalDataPolicyChatService if policy else ChatService
        command_cls = PolicyChatCommand if policy else ChatCommand
        return cls(repo, deps), command_cls(
            user_input="Fix this page",
            thread_id="thread",
            selected_role="nahida",
            selected_mode="普通",
            interactive_repair={"id": "scene", "revision": 1},
        )

    yield make, events, repo
    spend.reset_spend()


@pytest.mark.parametrize("policy", [False, True])
@pytest.mark.parametrize("transport", ["generate", "stream", "async"])
def test_repair_binds_saved_source_and_guards_all_generation_transports(
    setup_service, policy, transport
):
    make, events, repo = setup_service
    service, command = make(policy)
    prepared = service.start_turn(command)
    record = prepared.route["interactive_repair"]
    assert record["capabilities"] == ["three"]
    assert "saved source" in str(prepared.messages)
    assert current_repair_budget() is None
    if transport == "generate":
        service.generate(prepared)
    elif transport == "stream":
        pieces = []
        for piece in service.stream(prepared):
            assert current_repair_budget() is None
            pieces.append(piece)
        service.complete_turn(prepared, "".join(pieces))
    else:

        async def consume():
            pieces = []
            async for piece in service.stream_async(prepared):
                assert current_repair_budget() is None
                pieces.append(piece)
            service.complete_turn(prepared, "".join(pieces))

        asyncio.run(consume())
    assert events == ["send"]
    assert (
        repo.get_chat_turn(prepared.turn.id).route_snapshot["interactive_repair"]
        == record
    )
    assert spend.experiment_spend()["calls"] == 1


@pytest.mark.parametrize("policy", [False, True])
def test_preparation_failure_is_charged_and_retry_cannot_drop_or_change_source(
    setup_service, policy
):
    make, events, repo = setup_service
    service, command = make(policy)
    command = replace(command, turn_id="failed-repair")
    original_route = service.dependencies.route_request

    def broken_route(**kwargs):
        assert current_repair_budget() is not None
        spend.reserve_call(prompt_chars=100, max_tokens=100, model="priced-model")
        raise RuntimeError("offline prepare failure")

    service.dependencies = replace(service.dependencies, route_request=broken_route)
    with pytest.raises(RuntimeError, match="prepare failure"):
        service.start_turn(command)
    failed = repo.get_chat_turn("failed-repair")
    assert (
        failed.status == "failed"
        and failed.route_snapshot["interactive_repair"]["id"] == "scene"
    )
    assert spend.experiment_spend()["calls"] == 1
    service.dependencies = replace(service.dependencies, route_request=original_route)
    retry = replace(
        command, turn_id=None, retry_of_turn_id="failed-repair", interactive_repair=None
    )
    with pytest.raises(ValueError, match="cannot change"):
        service.start_turn(
            replace(retry, interactive_repair={"id": "another", "revision": 1})
        )
    prepared = service.start_turn(retry)
    service.generate(prepared)
    assert events == ["send"]
    assert spend.experiment_spend()["calls"] == 2


@pytest.mark.parametrize("policy", [False, True])
def test_missing_configuration_refuses_before_router_or_pending_turn(
    setup_service, monkeypatch, policy
):
    make, events, repo = setup_service
    service, command = make(policy)
    monkeypatch.delenv("LLM_SPEND_OUTPUT_CNY_PER_MTOK")
    service.dependencies = replace(
        service.dependencies,
        route_request=lambda **kw: pytest.fail("preparation ran without repair config"),
    )
    with pytest.raises(spend.SpendConfigurationError):
        service.start_turn(command)
    assert events == []
    assert len(repo.list_chat_turns("thread")) == 1


def test_http_command_preserves_repair_source_identity():
    from src.api.models.chat import ChatRequest
    from src.api.routes.chat_routes import _chat_command

    request = ChatRequest(
        user_input="Repair",
        session_id="thread",
        interactive_repair={"id": "scene", "revision": 1},
    )
    command = _chat_command(request, None)
    assert command.interactive_repair == {"id": "scene", "revision": 1}
    assert (
        _chat_command(ChatRequest(user_input="Hello"), None).interactive_repair is None
    )


@pytest.mark.parametrize("policy", [False, True])
def test_repair_cannot_resolve_source_from_other_thread(setup_service, policy):
    make, events, repo = setup_service
    service, command = make(policy)
    repo.ensure_chat_thread("other-thread")
    with pytest.raises(ValueError, match="source unavailable"):
        service.start_turn(replace(command, thread_id="other-thread"))
    assert events == []
    assert repo.list_chat_turns("other-thread") == []


@pytest.mark.parametrize("extra", [{"html": "forged"}, {"max_calls": 100}])
def test_http_repair_rejects_source_and_budget_overrides(extra):
    from pydantic import ValidationError
    from src.api.models.chat import ChatRequest

    with pytest.raises(ValidationError):
        ChatRequest(user_input="Repair", interactive_repair={"id": "scene", "revision": 1, **extra})
