"""Regression for the real-acceptance defects D1 / R0 / D2.

D1  production policy service must persist message-level attachment identity
R0  an explicit deep selection must obtain a real Deep run identity
D2  a malformed semantic decision degrades to deterministic research only for
    an already-authorised research turn (never for controls/cancellations)

All three exercise the *production* service instances, so an offline green here
cannot be produced by a base-class substitute.
"""

from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace

from conftest import default_chat_dependencies
from src.application.policy_chat_service import ExternalDataPolicyChatService, PolicyChatCommand
from src.domain.runtime_entities import ChatThread
from src.task_contract import default_contract
from src.tools.persistent_web_agent import PersistentWebToolAgent


def _deps():
    """Real defaults with stubs that accept the policy service's current kwargs."""

    def route(*_args, **_kwargs):
        return {
            "role": "auto",
            "mode": "普通",
            "model_profile": "flash",
            "task_contract": default_contract("research").to_dict(),
        }

    class PedagogyEvaluationStub:
        def evaluate_learner(self, **_kwargs):
            return SimpleNamespace(to_dict=lambda: {})

    class _Plan(SimpleNamespace):
        """Pedagogy plan stub: unknown optional fields default to empty text."""

        def __getattr__(self, _name: str) -> str:
            return ""

    class PedagogyEngineStub:
        def plan(self, **kwargs):
            plan = _Plan(
                to_dict=lambda: {"move": "invite_explanation", "phase": "explain"},
                move="invite_explanation", phase="explain",
            )
            return plan, kwargs.get("state")

    return replace(
        default_chat_dependencies(),
        route_request=route,
        pedagogy_evaluation=PedagogyEvaluationStub(),
        pedagogy_engine=PedagogyEngineStub(),
    )


class FakeGateway:
    def search_exact(self, query: str, *, max_results: int) -> dict:
        self.query = query
        return {
            "status": "ok",
            "reason": "results_found",
            "query": query,
            "results": [{"title": f"{query} ref", "url": "https://example.test/source",
                         "snippet": "summary"}][:max_results],
            "provider_errors": [],
            "providers_attempted": ["test"],
        }

    def read(self, url: str, *, max_chars: int, timeout: float | None = None) -> dict:
        return {"ok": True, "url": url, "content": "Reference body."[:max_chars], "method": "test_read"}


# --- D1 -------------------------------------------------------------------

def test_policy_service_persists_message_attachment_refs(runtime_test_context):
    repository = runtime_test_context.repository
    service = ExternalDataPolicyChatService(repository, _deps())
    repository.create_chat_thread(ChatThread(id="thread-d1", status="active"))
    refs = [{"attachment_id": "att_x", "content_hash": "hash_x", "filename": "shot.png"}]

    prepared = service.start_turn(
        PolicyChatCommand(user_input="比较两个配置", thread_id="thread-d1", attachment_refs=refs)
    )

    stored = repository.get_chat_turn(prepared.turn.id)
    assert stored is not None
    assert stored.attachment_refs == tuple(refs)


# --- R0 -------------------------------------------------------------------

def test_explicit_deep_selection_obtains_a_real_deep_run():
    created: dict = {}

    class ResearchService:
        def create(self, query, **kwargs):
            created.update(kwargs)
            created["query"] = query
            return SimpleNamespace(id="deep-r0", version=1)

        def execute(self, _run_id):
            return SimpleNamespace(id="deep-r0", research_context={}, query_attempts=[])

        def begin_tool_trace(self, _run_id):
            return "op-r0"

        def tool_trace_cancel_requested(self, *_args):
            return False

        def record_tool_trace(self, *_args, **_kwargs):
            pass

    def semantic_must_not_run(**_kwargs):
        raise AssertionError("an explicit deep selection must not enter semantic recovery")

    agent = PersistentWebToolAgent(
        gateway=FakeGateway(), research_service=ResearchService(),
        semantic_completion=semantic_must_not_run,
    )
    trace = agent.resolve("帮我比较流萤在两种配置下的伤害和资源投入", research_intent=True,
                          deep_requested=True)

    assert created.get("research_mode") == "deep"
    assert not trace.error


# --- D2 -------------------------------------------------------------------

def _malformed_completion(**_kwargs):
    return json.dumps({"unexpected": "shape"})


class DeterministicResearchService:
    """Records run creation; the deterministic chain only needs create/trace."""

    def __init__(self):
        self.queries: list[str] = []

    def create(self, query, **_kwargs):
        self.queries.append(query)
        return SimpleNamespace(id="run-d2", version=1)

    def begin_tool_trace(self, _run_id):
        return "op-d2"

    def tool_trace_cancel_requested(self, *_args):
        return False

    def record_tool_trace(self, *_args, **_kwargs):
        pass


def test_malformed_decision_degrades_for_authorised_research():
    service = DeterministicResearchService()
    agent = PersistentWebToolAgent(
        gateway=FakeGateway(), research_service=service, semantic_completion=_malformed_completion,
    )

    trace = agent.resolve(
        "帮我比较流萤在两种配置下的伤害和资源投入，参考我上传的角色截图。",
        research_intent=True,
    )

    assert "SemanticRecovery blocked" not in (trace.error or "")
    assert any(call["name"] == "web_search" for call in trace.calls)
    fallback = next(call for call in trace.calls if call["name"] == "research_semantic_fallback")
    assert fallback["result"]["detail"] == "decision_fields"
    assert fallback["result"]["degraded_to_deterministic"] is True


def test_malformed_decision_still_blocks_without_research_authorisation():
    service = DeterministicResearchService()
    agent = PersistentWebToolAgent(
        gateway=FakeGateway(), research_service=service, semantic_completion=_malformed_completion,
    )

    trace = agent.resolve("帮我比较流萤在两种配置下的伤害和资源投入", research_intent=False)

    assert "SemanticRecovery blocked" in (trace.error or "")
    assert not any(call["name"] == "web_search" for call in trace.calls)
