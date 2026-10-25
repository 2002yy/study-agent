"""CL-M3-S2-C2: round two is chosen from round one's observation.

The production deep-research loop does not run a fixed query list. It reads
pages into `notes`, hands the memo and those notes to the planner's `revise`,
and turns the planner's additional sub-questions into the next round's searches.

This test drives that whole chain through the real chat entrypoint:

    ChatService -> web gate -> PersistentWebToolAgent._resolve_deep_research
      -> WebLookupService (real SQLite) -> fake gateway + fake planner

The fake planner is not scripted with the second query. It derives it from the
text of the page the first round actually read, so a second query containing
that marker can only exist if the observation reached the planner and the
resulting sub-question was really searched.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.application.chat_service import ChatDependencies
from src.application.policy_chat_service import (
    ExternalDataPolicyChatService,
    PolicyChatCommand,
)
from src.application.web_lookup_service import WebLookupService
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.mode_manager import RuntimeModes
from src.repositories.runtime_repository import RuntimeRepository
from src.repositories.web_lookup_repository import WebLookupRepository
from src.task_contract import (
    TaskAwarePedagogyEngine,
    TaskAwarePedagogyEvaluationService,
    route_request_with_task_contract,
)
from src.tools.persistent_web_agent import PersistentWebToolAgent

QUERY = (
    "帮我调研 OMEGA 协议的现状和延迟对比；并梳理最新进展，分别有哪些风险和机会？"
)
FIRST_SUB_QUESTION = "omega protocol latency baseline"
NEEDLE = "OMEGA-42"


class ObservingGateway:
    """A search/read fake whose second result depends on the second query."""

    def __init__(self) -> None:
        self.search_calls: list[str] = []
        self.read_calls: list[str] = []

    def search(self, query: str, *, max_items: int = 10) -> list[dict[str, Any]]:
        self.search_calls.append(query)
        if NEEDLE.lower() in query.lower():
            url = "https://omega.test/follow-up"
            title = f"{query} - follow-up source"
        elif "omega" in query.lower():
            url = "https://alpha.test/report"
            title = f"{query} - baseline report"
        else:
            return []
        return [
            {
                "title": title,
                "url": url,
                "source": "Test source",
                "snippet": f"{query}: deterministic fixture",
            }
        ]

    def read(self, url: str, *, max_chars: int = 6000) -> dict[str, Any]:
        self.read_calls.append(url)
        if url == "https://alpha.test/report":
            content = (
                "Round one page. The measurement label is "
                f"{NEEDLE}, recorded in the baseline table. "
            )
        else:
            content = "Round two page. The label matches the baseline table. "
        return {"ok": True, "url": url, "content": content * 3}

    def warnings(self) -> list[dict[str, str]]:
        return []


@dataclass
class ObservingPlanner:
    """A planner that can only add a query if it really saw the observation."""

    initial: list[str]
    seen_notes: list[list[dict[str, Any]]]
    added: list[str]

    def plan(self, query: str, context: Any) -> list[str]:
        return list(self.initial)

    def revise(
        self,
        memo: str,
        notes: list[dict[str, Any]],
        remaining: list[str],
        context: Any = None,
    ) -> dict[str, Any]:
        self.seen_notes.append([dict(note) for note in notes])
        observed = " ".join(
            str(note.get("facts") or "") for note in notes
        )
        already = any(NEEDLE in item for item in self.added)
        if NEEDLE in observed and not already:
            follow_up = f"{NEEDLE} follow up baseline"
            self.added.append(follow_up)
            return {"done": False, "additional": [follow_up], "compute": None}
        return {"done": True, "additional": [], "compute": None}


def _service(tmp_path: Path, gateway: ObservingGateway, planner: ObservingPlanner):
    database = RuntimeDatabase(tmp_path / "runtime.db")
    repository = RuntimeRepository(database)
    lookup = WebLookupService(
        WebLookupRepository(database),
        gateway,
        planner=planner,
    )
    agent = PersistentWebToolAgent(
        gateway=gateway,
        research_service=lookup,
        semantic_completion=None,
    )
    captured: dict[str, Any] = {"rag_context": ""}

    def build_messages(**kwargs):
        captured["rag_context"] = kwargs["rag_context"]
        return [
            {"role": "system", "content": kwargs["rag_context"]},
            {"role": "user", "content": kwargs["user_input"]},
        ]

    dependencies = ChatDependencies(
        load_runtime_modes=lambda: RuntimeModes(performance_mode="fast"),
        read_memory_bundle=lambda _mode: {},
        build_role_prompt=lambda role, **_kwargs: f"role:{role}",
        route_request=route_request_with_task_contract,
        retrieve_local_knowledge=lambda *_args, **_kwargs: _EmptyRag(),
        build_messages=build_messages,
        chat=lambda *_args, **_kwargs: "answer",
        chat_max_tokens=lambda _mode: 1000,
        resolve_web_tools=agent.resolve,
        pedagogy_engine=TaskAwarePedagogyEngine(),
        pedagogy_evaluation=TaskAwarePedagogyEvaluationService(),
    )
    service = ExternalDataPolicyChatService(repository, dependencies)
    return service, repository, captured


class _EmptyRag:
    def to_dict(self) -> dict[str, Any]:
        return {
            "status": "disabled",
            "context": "",
            "result_count": 0,
            "results": [],
        }


def _turn(service: ExternalDataPolicyChatService, thread_id: str):
    return service.start_turn(
        PolicyChatCommand(
            user_input=QUERY,
            thread_id=thread_id,
            web_policy="auto",
            cloud_context_policy="allow_local_evidence",
        )
    )


def _balanced_escalation(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.application.helpers.load_frontend_settings",
        lambda: {"deep_research_sensitivity": "balanced"},
    )


def test_the_second_search_uses_the_first_rounds_observation(tmp_path, monkeypatch):
    _balanced_escalation(monkeypatch)
    gateway = ObservingGateway()
    planner = ObservingPlanner(
        initial=[FIRST_SUB_QUESTION], seen_notes=[], added=[]
    )
    service, _repository, _captured = _service(tmp_path, gateway, planner)

    prepared = _turn(service, "c2-feedback")

    # The first round searched the initial sub-question and read its page.
    assert gateway.search_calls[0] == FIRST_SUB_QUESTION
    assert gateway.read_calls[0] == "https://alpha.test/report"

    # The planner saw the page text before it produced the second sub-question.
    assert planner.seen_notes, "planner never received the round-one notes"
    assert any(
        NEEDLE in str(note.get("facts") or "")
        for note in planner.seen_notes[0]
    )
    assert planner.added == [f"{NEEDLE} follow up baseline"]

    # The second query is the observation-derived one, and it was searched.
    assert len(gateway.search_calls) == 2
    assert NEEDLE in gateway.search_calls[1]
    assert gateway.read_calls[-1] == "https://omega.test/follow-up"

    # Two rounds are durable in the real WebLookupRun: round one and the
    # observation-derived round two.
    run_id = prepared.rag["web_tools"]["run_id"]
    assert run_id
    run = WebLookupRepository(
        RuntimeDatabase(tmp_path / "runtime.db")
    ).get(run_id)
    assert run is not None
    # The system chose the multi-round mode itself; the caller did not.
    assert run.research_context.get("research_mode") == "deep"
    attempts = list(run.query_attempts)
    queries = [str(attempt.get("query", "")) for attempt in attempts]
    rounds = {int(attempt.get("round") or 0) for attempt in attempts}
    assert len(attempts) >= 2
    assert rounds == {1, 2}
    assert NEEDLE in queries[1]
    notes = (run.research_context.get("deep") or {}).get("notes") or []
    assert any(NEEDLE in str(note.get("facts") or "") for note in notes)

    # The durable chat turn points at that same run.
    stored = RuntimeRepository(
        RuntimeDatabase(tmp_path / "runtime.db")
    ).get_chat_turn(prepared.turn.id)
    assert stored is not None
    assert stored.rag_snapshot["web_tools"]["run_id"] == run_id


def test_a_first_round_without_the_needed_observation_adds_no_query(
    tmp_path, monkeypatch
):
    """The negative control: no observation means no invented follow-up."""

    _balanced_escalation(monkeypatch)
    gateway = ObservingGateway()
    empty_page = gateway.read
    gateway.read = lambda url, *, max_chars=6000: {
        "ok": True,
        "url": url,
        "content": "The page contains no measurement label at all.",
    }
    planner = ObservingPlanner(
        initial=[FIRST_SUB_QUESTION], seen_notes=[], added=[]
    )
    service, repository, _captured = _service(tmp_path, gateway, planner)
    try:
        prepared = _turn(service, "c2-no-observation")
    finally:
        gateway.read = empty_page

    assert len(gateway.search_calls) == 1
    assert planner.added == []
    run_id = prepared.rag["web_tools"]["run_id"]
    run = WebLookupRepository(
        RuntimeDatabase(tmp_path / "runtime.db")
    ).get(run_id)
    assert run is not None
    attempts = list(run.query_attempts)
    assert {int(attempt.get("round") or 0) for attempt in attempts} == {1}
    # Nothing was invented to fill the gap.
    assert all(
        NEEDLE not in str(attempt.get("query", "")) for attempt in attempts
    )
