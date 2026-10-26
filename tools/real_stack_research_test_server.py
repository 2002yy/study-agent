"""Real-stack server variant for durable ResearchRun cancellation gates."""

from __future__ import annotations

from dataclasses import replace
import time
from typing import Any

from tools.real_stack_test_server import app, _real_stack_chat_service
from src.application.policy_chat_service import ExternalDataPolicyChatService
from src.application.runtime_repository import (
    get_chat_service,
    get_web_lookup_repository,
    get_web_lookup_service,
)
from src.application.web_lookup_service import WebLookupService
from src.domain.runtime_entities import WebLookupRun
from src.tools.persistent_web_agent import PersistentWebToolAgent
from src.tools.web_agent import WebToolTrace

RESEARCH_PREFIX = "请联网研究："
DEEP_RESEARCH_PREFIX = "请深度研究："
DEEP_OBSERVATION_MARKER = "DEEP-OBSERVATION-42"


class SlowDeterministicResearchGateway:
    """Pause external boundaries so the browser can cancel a running run."""

    def search(self, query: str, *, max_items: int = 10) -> list[dict[str, Any]]:
        time.sleep(2.0)
        return [
            {
                "title": query,
                "url": "https://docs.python.org/3/tutorial/classes.html",
                "source": "Python documentation",
                "snippet": f"Deterministic research evidence for {query}",
            }
        ][:max_items]

    def read(self, url: str, *, max_chars: int = 6000) -> dict[str, Any]:
        time.sleep(0.08)
        content = (
            "Dependency injection keeps object construction outside the code that uses "
            "the dependency, so tests can replace the implementation explicitly."
        )
        return {
            "ok": True,
            "url": url,
            "content": content[:max_chars],
        }

    def warnings(self) -> list[dict[str, str]]:
        return []


def _real_stack_web_lookup_service() -> WebLookupService:
    return ModeAwareResearchService(
        get_web_lookup_repository(),
        SlowDeterministicResearchGateway(),
    )


class DeterministicDeepGateway:
    """Two-round fake search: the second page only exists after the first read."""

    def search(self, query: str, *, max_items: int = 10) -> list[dict[str, Any]]:
        time.sleep(1.2)
        if "FOLLOWUP" in query:
            url = "https://example.test/deep-followup"
            title = "Follow-up evidence"
        else:
            url = "https://example.test/deep-baseline"
            title = "Baseline evidence"
        return [
            {
                "title": f"{title} ({query})",
                "url": url,
                "source": "E2E deep source",
                "snippet": f"Deterministic deep result for {query}",
            }
        ][:max_items]

    def read(self, url: str, *, max_chars: int = 6000) -> dict[str, Any]:
        time.sleep(0.08)
        if "baseline" in url:
            content = (
                f"{DEEP_OBSERVATION_MARKER} appears only in the page this round read. "
                "It anchors the follow-up query."
            )
        else:
            content = (
                "The follow-up page confirms the baseline table and adds the "
                "independent check the first round asked for."
            )
        return {"ok": True, "url": url, "content": content[:max_chars]}

    def warnings(self) -> list[dict[str, str]]:
        return []


class DeterministicDeepPlanner:
    """Revise() derives the second query from the note it was actually given."""

    def __init__(self) -> None:
        self._added = False

    def plan(self, query: str, context: Any) -> list[str]:
        return [f"{query} baseline"]

    def revise(
        self,
        memo: str,
        notes: list[dict[str, Any]],
        remaining: list[str],
        context: Any = None,
    ) -> dict[str, Any]:
        observed = " ".join(str(note.get("facts") or "") for note in notes or [])
        if DEEP_OBSERVATION_MARKER in observed and not self._added:
            self._added = True
            return {
                "done": False,
                "additional": [f"FOLLOWUP {DEEP_OBSERVATION_MARKER} second round"],
                "compute": None,
            }
        return {"done": True, "additional": [], "compute": None}


def _real_stack_deep_lookup_service() -> WebLookupService:
    return WebLookupService(
        get_web_lookup_repository(),
        DeterministicDeepGateway(),
        planner=DeterministicDeepPlanner(),
    )


class ModeAwareResearchService(WebLookupService):
    """Replay a stored run with the fake that matches the run's own mode.

    A deep run is created through ``resolve_web_tools`` with the deep planner,
    but retry and resume arrive at the HTTP route, which is wired to this
    service. Without the switch a deep run would resume under the research fake
    and read the research page, so its recorded evidence would come from a
    different fixture than the one that produced it.
    """

    def execute(
        self, run_id: str, *, raise_on_error: bool = False, **kwargs: Any
    ) -> WebLookupRun:
        context = self.get(run_id).research_context
        mode = context.get("research_mode") if isinstance(context, dict) else None
        if mode != "deep":
            return super().execute(run_id, raise_on_error=raise_on_error, **kwargs)
        # A fresh planner per replay: its observation flag must not leak across runs.
        return WebLookupService(
            self.repository,
            DeterministicDeepGateway(),
            planner=DeterministicDeepPlanner(),
        ).execute(run_id, raise_on_error=raise_on_error, **kwargs)


def _resolve_deterministic_deep_research(
    user_input: str,
    *,
    owner_thread_id: str | None = None,
    owner_turn_id: str | None = None,
    **_kwargs: Any,
) -> WebToolTrace:
    agent = PersistentWebToolAgent(
        gateway=DeterministicDeepGateway(),
        research_service=_real_stack_deep_lookup_service(),
        semantic_completion=None,
    )
    return agent.resolve(
        user_input,
        owner_thread_id=owner_thread_id,
        owner_turn_id=owner_turn_id,
        research_intent=True,
        history_allowed=True,
        deep_requested=True,
    )


def _resolve_deterministic_research(
    user_input: str,
    *,
    owner_thread_id: str | None = None,
    owner_turn_id: str | None = None,
    **kwargs: Any,
) -> WebToolTrace:
    """Replace only explicit research planning and preserve other chat fixtures."""

    if user_input.strip().startswith(DEEP_RESEARCH_PREFIX):
        return _resolve_deterministic_deep_research(
            user_input,
            owner_thread_id=owner_thread_id,
            owner_turn_id=owner_turn_id,
            **kwargs,
        )
    if not user_input.strip().startswith(RESEARCH_PREFIX):
        return WebToolTrace(enabled=False)

    service = _real_stack_web_lookup_service()
    run = service.create(
        user_input,
        owner_thread_id=owner_thread_id,
        owner_turn_id=owner_turn_id,
        run_kind="chat_tool_loop",
    )
    completed = service.execute(run.id, raise_on_error=False)
    calls: tuple[dict[str, Any], ...] = ()
    if completed.status == "completed" and completed.provider_status == "found":
        calls = (
            {
                "name": "web_search",
                "arguments": {"query": user_input},
                "result": {
                    "status": completed.status,
                    "items": completed.items,
                    "source_block": completed.source_block,
                },
            },
        )
    return WebToolTrace(
        calls=calls,
        error=completed.error,
        run_id=run.id,
    )


def _real_stack_research_chat_service() -> ExternalDataPolicyChatService:
    base = _real_stack_chat_service()
    return ExternalDataPolicyChatService(
        base.repository,
        replace(
            base.dependencies,
            resolve_web_tools=_resolve_deterministic_research,
        ),
    )


app.dependency_overrides[get_web_lookup_service] = _real_stack_web_lookup_service
app.dependency_overrides[get_chat_service] = _real_stack_research_chat_service
