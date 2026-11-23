"""Real reader-chain wiring with fake backends; no repository or model calls."""

from dataclasses import fields
from types import SimpleNamespace
from typing import cast

from src.application.research_runtime_live_values import ActiveRuntimeLiveValues
from src.application.research_runtime_read_execution import ActiveReadExecutionContext
from src.application.research_runtime_read_scheduling import ActiveReadDispatchContext
from src.web.research.chain_executor import ChainRun, ChainStepResult
from src.web.research.contracts import ResearchState
from src.web.research.runtime import ResearchRuntimeCursor, RuntimeReadOutcome
from tests.research_read_candidate_factory import read_candidate


BACKENDS = ("native_http", "wigolo_http")


def _dispatch() -> ActiveReadDispatchContext:
    return ActiveReadDispatchContext(
        live=ActiveRuntimeLiveValues(state=cast(ResearchState, object())),
        breaker=None,
        available_backends=BACKENDS,
        research_seconds_left=lambda: 30.0,
    )


def test_default_chain_uses_fresh_attempt_history_and_shared_executor_factory() -> None:
    order: list[str] = []
    routed: list[tuple[str, ...]] = []
    requested: list[dict] = []
    def gateway_read(url, *, max_chars):
        return {"ok": True, "url": url, "max_chars": max_chars}

    def hard_seconds_left():
        return 25.0

    class _Site:
        def try_specialist(self, context, candidate, source_limit):
            order.append("specialist")
            requested.append(
                {"context": context, "candidate": candidate.id, "limit": source_limit}
            )
            return None

    def escalation_backend():
        order.append("escalation")
        return "escalation-adapter"

    def build_executors(**kwargs):
        order.append("factory")
        assert kwargs == {
            "source_limit": 1200,
            "gateway_read": gateway_read,
            "escalation_backend": "escalation-adapter",
            "hard_seconds_left": hard_seconds_left,
        }
        return {"native_http": object()}

    def run_chain(**kwargs):
        order.append("chain")
        assert kwargs["candidate_id"] == "target"
        assert kwargs["url"] == "https://example.org/article"
        assert kwargs["host"] == "example.org"
        assert kwargs["chain"] == BACKENDS
        assert kwargs["outer_attempt_number"] == 2
        assert kwargs["health_state_for"]("native_http", "example.org") == ""
        routed.append(kwargs["attempted_backends"])
        kwargs["record_outcome"](
            ChainStepResult(
                backend="wigolo_http", retrieval_state="fetched", usable_content=True
            )
        )
        return ChainRun(
            candidate_id="target",
            steps=(),
            action="resolve",
            attempted_backends=kwargs["attempted_backends"],
        )

    dispatch = _dispatch()
    execution = ActiveReadExecutionContext(
        gateway=SimpleNamespace(escalation_backend=escalation_backend),
        gateway_read=gateway_read,
        hard_seconds_left=hard_seconds_left,
        dispatch=dispatch,
        read_site=_Site(),
        executor_factory=build_executors,
        chain_runner=run_chain,
    )
    assert not {"state", "cursor", "context", "read_outcomes"} & {
        field.name for field in fields(execution)
    }

    first_context: dict = {}
    first = (
        RuntimeReadOutcome(
            candidate_id="target", backend="native_http", status="failed"
        ),
    )
    dispatch.live.context = first_context
    dispatch.live.cursor = ResearchRuntimeCursor(read_outcomes=first)
    result, steps = execution.run_candidate(
        candidate=read_candidate(),
        source_limit=1200,
        outer_attempt_number=2,
    )
    assert result.action == "resolve" and len(steps) == 1

    resumed_context: dict = {"resumed": True}
    resumed = (
        RuntimeReadOutcome(
            candidate_id="other", backend="native_http", status="failed"
        ),
        RuntimeReadOutcome(
            candidate_id="target", backend="wigolo_http", status="failed"
        ),
    )
    dispatch.live.context = resumed_context
    dispatch.live.cursor = ResearchRuntimeCursor(read_outcomes=resumed)
    execution.run_candidate(
        candidate=read_candidate(),
        source_limit=1200,
        outer_attempt_number=2,
    )
    assert routed == [("native_http",), ("wigolo_http",)]
    assert [item["context"] for item in requested] == [first_context, resumed_context]
    assert order == ["specialist", "escalation", "factory", "chain"] * 2


def test_usable_specialist_short_circuits_default_backend_factory() -> None:
    step = ChainStepResult(
        backend="crawl4ai_browser",
        retrieval_state="fetched",
        usable_content=True,
        content="text",
    )
    current_context = {"reader_capabilities": ["js_render"]}

    class _Site:
        def try_specialist(self, context, candidate, source_limit):
            assert context is current_context
            assert candidate.id == "target" and source_limit == 900
            return step

    def forbidden(**kwargs):
        raise AssertionError(
            "usable specialist must not enter the default reader chain"
        )

    dispatch = _dispatch()
    dispatch.live.context = current_context
    execution = ActiveReadExecutionContext(
        gateway=SimpleNamespace(),
        gateway_read=forbidden,
        hard_seconds_left=lambda: 1.0,
        dispatch=dispatch,
        read_site=_Site(),
        executor_factory=forbidden,
        chain_runner=forbidden,
    )
    result, steps = execution.run_candidate(
        candidate=read_candidate(),
        source_limit=900,
        outer_attempt_number=3,
    )
    assert result.action == "resolve"
    assert result.attempted_backends == ("crawl4ai_browser",)
    assert steps == [step]


def test_default_chain_reloads_history_after_specialist_fallback() -> None:
    """Backend history may be rebound while the specialist route is checked."""

    dispatch = _dispatch()
    old_history = (
        RuntimeReadOutcome(
            candidate_id="target", status="failed", backend="native_http"
        ),
    )
    rebound_history = (
        RuntimeReadOutcome(
            candidate_id="target", status="failed", backend="wigolo_http"
        ),
    )
    initial_context = {"phase": "before"}
    dispatch.live.cursor = ResearchRuntimeCursor(read_outcomes=old_history)
    dispatch.live.context = initial_context
    attempted: list[tuple[str, ...]] = []

    class _Site:
        def try_specialist(self, context, candidate, source_limit):
            assert context is initial_context
            dispatch.live.cursor = ResearchRuntimeCursor(read_outcomes=rebound_history)
            dispatch.live.context = {"phase": "after"}
            return None

    def run_chain(**kwargs):
        attempted.append(kwargs["attempted_backends"])
        return ChainRun(candidate_id="target", steps=(), action="defer")

    execution = ActiveReadExecutionContext(
        gateway=SimpleNamespace(),
        gateway_read=lambda *_args, **_kwargs: {},
        hard_seconds_left=lambda: 25.0,
        dispatch=dispatch,
        read_site=_Site(),
        executor_factory=lambda **_kwargs: {},
        chain_runner=run_chain,
    )
    execution.run_candidate(
        candidate=read_candidate(),
        source_limit=1200,
        outer_attempt_number=2,
    )
    assert attempted == [("wigolo_http",)]
    assert dispatch.live.context == {"phase": "after"}
