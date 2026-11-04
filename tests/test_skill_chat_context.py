from dataclasses import replace

import pytest

from src import skills
from src.application.chat_service import ChatCommand, ChatDependencies, ChatService
from src.application.policy_chat_service import (
    ExternalDataPolicyChatService,
    PolicyChatCommand,
)
from src.application.skill_context import bound_skill_ids
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.mode_manager import RuntimeModes
from src.repositories.runtime_repository import RuntimeRepository
from src.tools.web_agent import WebToolTrace
from src.task_contract import (
    route_request_with_task_contract,
    TaskAwarePedagogyEngine,
    TaskAwarePedagogyEvaluationService,
)

CONTENT = "---\nname: clear-steps\ndescription: Explain in clear steps\n---\nSKILL_TEST_DIRECTIVE: explain assumptions before steps."


@pytest.fixture
def installed(monkeypatch, tmp_path):
    from src import api

    monkeypatch.setattr(skills, "SKILL_STORE_PATH", tmp_path / "skills.json")
    monkeypatch.setattr(api, "FRONTEND_SETTINGS_PATH", tmp_path / "frontend.yaml")
    store = skills.SkillStore()
    row = store.import_skill(CONTENT)
    store.set_enabled(row["id"], True)
    return store, row["id"]


def make_service(tmp_path, policy, sent):
    class Rag:
        def to_dict(self):
            return {
                "status": "disabled",
                "context": "",
                "results": [],
                "result_count": 0,
            }

    def chat(messages, **kwargs):
        sent.append(messages)
        kwargs["on_completion"]("stop")
        return "A plain final answer."

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
        chat=chat,
    )
    repo = RuntimeRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    cls = ExternalDataPolicyChatService if policy else ChatService
    return cls(repo, deps), repo


@pytest.mark.parametrize("policy", [False, True])
def test_selected_skill_reaches_actual_model_request_only_for_this_turn(
    tmp_path, installed, policy
):
    _, skill_id = installed
    sent = []
    service, repo = make_service(tmp_path, policy, sent)
    cls = PolicyChatCommand if policy else ChatCommand
    command = cls(
        user_input="Explain Java references",
        selected_role="nahida",
        selected_mode="普通",
        selected_skill_ids=[skill_id],
    )
    prepared = service.start_turn(command)
    assert "SKILL_TEST_DIRECTIVE" in str(prepared.messages)
    assert prepared.route["skills"]["count"] == 1
    assert "SKILL_TEST_DIRECTIVE" not in str(prepared.route)
    service.generate(prepared)
    assert len(sent) == 1 and "SKILL_TEST_DIRECTIVE" in str(sent[0])
    assert (
        "SKILL_TEST_DIRECTIVE"
        not in repo.get_chat_thread(prepared.thread.id).settings_snapshot[
            "conversationInstruction"
        ]
    )
    if policy:
        audit = prepared.route["external_data_policy"]
        assert "skill_context" in audit["answer_data_categories"]
        answer_call = next(
            c for c in audit["external_calls"] if c["purpose"] == "answer_generation"
        )
        assert answer_call["data_counts"]["skill_context"] == 1
    next_turn = service.start_turn(
        cls(
            user_input="Next question",
            thread_id=prepared.thread.id,
            selected_role="nahida",
            selected_mode="普通",
        )
    )
    assert "SKILL_TEST_DIRECTIVE" not in str(next_turn.messages)


@pytest.mark.parametrize("policy", [False, True])
def test_disabled_skill_is_rejected_without_a_model_call(tmp_path, installed, policy):
    store, skill_id = installed
    store.set_enabled(skill_id, False)
    sent = []
    service, _ = make_service(tmp_path, policy, sent)
    cls = PolicyChatCommand if policy else ChatCommand
    with pytest.raises(ValueError, match="disabled"):
        service.start_turn(cls(user_input="hello", selected_skill_ids=[skill_id]))
    assert sent == []


def test_cloud_policy_blocks_skill_before_any_model_call(tmp_path, installed):
    _, skill_id = installed
    sent = []
    service, _ = make_service(tmp_path, True, sent)
    with pytest.raises(ValueError, match="本地技能"):
        service.start_turn(
            PolicyChatCommand(
                user_input="hello",
                selected_skill_ids=[skill_id],
                cloud_context_policy="question_only",
            )
        )
    assert sent == []


def test_retry_preserves_ids_and_refuses_switching():
    route = {"skills": {"ids": ["first"]}}
    assert bound_skill_ids([], route) == ["first"]
    with pytest.raises(ValueError, match="cannot switch"):
        bound_skill_ids(["other"], route)
    with pytest.raises(ValueError, match="cannot switch"):
        bound_skill_ids(["new"], {})
    assert bound_skill_ids([], {}) == []
    assert bound_skill_ids(["new"], None) == ["new"]


def test_http_request_preserves_skill_identity_without_persisting_skill_text():
    from src.api.models.chat import ChatRequest
    from src.api.routes.chat_routes import _chat_command

    request = ChatRequest(user_input="hello", selected_skill_ids=["chosen"])
    command = _chat_command(request)
    assert command.selected_skill_ids == ["chosen"]
    assert command.conversation_instruction == ""


@pytest.mark.parametrize("policy", [False, True])
def test_retry_cannot_add_a_skill_to_a_parent_that_selected_none(
    tmp_path, installed, policy
):
    _, skill_id = installed
    sent = []
    service, _ = make_service(tmp_path, policy, sent)
    cls = PolicyChatCommand if policy else ChatCommand
    original = cls(user_input="hello", selected_role="nahida", selected_mode="普通")
    prepared = service.start_turn(original)
    service.fail_turn(prepared)
    with pytest.raises(ValueError, match="cannot switch"):
        service.start_turn(
            replace(
                original,
                thread_id=prepared.thread.id,
                retry_of_turn_id=prepared.turn.id,
                selected_skill_ids=[skill_id],
            )
        )
    assert sent == []
