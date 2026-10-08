"""Activation: the production runtime factory really constructs the Standard chat service.

This test answers one question only - is the accepted Standard continuation now the service the
runtime builds? It does not re-test Standard semantics (lease contention, deadline,
exactly-once, binding, authority and fail-safe are held by their own authority tests).

The identity assertions matter most: the lookup resolver and the Standard gateway must be the
same production objects, so nobody can later swap in a look-alike gateway.
"""

from __future__ import annotations

from types import SimpleNamespace

from src.application.standard_chat_service import StandardContinuationChatService


def test_runtime_chat_service_activates_standard_continuation(monkeypatch):
    from src.application import runtime_repository as runtime

    gateway_sentinel = object()

    class FakeWebAgent:
        def __init__(self):
            self.gateway = gateway_sentinel
            self.resolved = 0

        def resolve(self, *_args, **_kwargs):
            self.resolved += 1
            raise AssertionError("composition must not resolve anything")

    web_agent = FakeWebAgent()
    runtime_repository = SimpleNamespace(database=object())
    lookup_repository = object()

    monkeypatch.setattr(runtime, "get_runtime_repository", lambda: runtime_repository)
    monkeypatch.setattr(runtime, "get_web_lookup_repository", lambda: lookup_repository)
    monkeypatch.setattr(runtime, "get_web_tool_agent", lambda: web_agent)

    runtime.get_chat_service.cache_clear()
    try:
        service = runtime.get_chat_service()

        # 1. The runtime builds the accepted service.
        assert isinstance(service, StandardContinuationChatService)

        # 2. One repository, shared.
        assert service.repository is runtime_repository

        # 3. The continuation is wired with the same authorities.
        continuation = service._standard_continuation
        assert continuation is not None
        assert continuation.repository is runtime_repository
        assert continuation.runs is lookup_repository

        # 4. The gateway is the agent's own gateway, not a new one.
        assert continuation.gateway is web_agent.gateway

        # 5. The lookup seam comes from that same agent.
        assert service.dependencies.resolve_web_tools.__self__ is web_agent
    finally:
        runtime.get_chat_service.cache_clear()


def test_the_base_dependencies_are_unchanged(monkeypatch):
    from src.application import runtime_repository as runtime

    class FakeWebAgent:
        gateway = object()

        def resolve(self, *_args, **_kwargs):
            raise AssertionError("composition must not resolve anything")

    web_agent = FakeWebAgent()
    monkeypatch.setattr(runtime, "get_runtime_repository", lambda: SimpleNamespace(database=object()))
    monkeypatch.setattr(runtime, "get_web_lookup_repository", object)
    monkeypatch.setattr(runtime, "get_web_tool_agent", lambda: web_agent)

    runtime.get_chat_service.cache_clear()
    try:
        service = runtime.get_chat_service()
        dependencies = service.dependencies
        # The pre-existing composition is preserved, not replaced.
        assert dependencies.pedagogy_engine is not None
        assert dependencies.pedagogy_evaluation is not None
        assert callable(dependencies.route_request)
        assert dependencies.resolve_web_tools.__self__ is web_agent
    finally:
        runtime.get_chat_service.cache_clear()


def test_activation_adds_no_second_cache(monkeypatch):
    from src.application import runtime_repository as runtime

    # No get_standard_continuation_service factory: the chat service's own cache owns it.
    assert not hasattr(runtime, "get_standard_continuation_service")
