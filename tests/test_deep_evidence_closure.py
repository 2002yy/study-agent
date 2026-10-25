"""CL-M3-S2-C3a: the answer is bound to the pages the research really read.

C2 proved the second round is chosen from the first round's observation. This
closes the other half: the pages that were read must reach the answer context,
carry their public URLs, and survive as sources in the durable chat turn.

The same real chain is used (chat entrypoint -> gate -> deep agent -> real
SQLite), with a fake gateway and planner. No summary-shaped call is trusted:
only a note that has both a URL and read text is projected as evidence.
"""

from __future__ import annotations

from typing import Any

from src.application.chat_service import answer_validation_active
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.runtime_repository import RuntimeRepository
from tests.test_research_observation_feedback import (
    FIRST_SUB_QUESTION,
    NEEDLE,
    ObservingGateway,
    ObservingPlanner,
    _balanced_escalation,
    _service,
    _turn,
)


class EmptyGateway:
    """A search that finds nothing: no page is read, so nothing is evidence."""

    def __init__(self) -> None:
        self.search_calls: list[str] = []
        self.read_calls: list[str] = []

    def search(self, query: str, *, max_items: int = 10) -> list[dict[str, Any]]:
        self.search_calls.append(query)
        return []

    def read(self, url: str, *, max_chars: int = 6000) -> dict[str, Any]:
        self.read_calls.append(url)
        return {"ok": False, "url": url, "error": "not_found"}

    def warnings(self) -> list[dict[str, str]]:
        return []


def _planner() -> ObservingPlanner:
    return ObservingPlanner(initial=[FIRST_SUB_QUESTION], seen_notes=[], added=[])


def test_the_answer_context_carries_the_deep_pages_and_their_urls(tmp_path, monkeypatch):
    _balanced_escalation(monkeypatch)
    service, _repository, captured = _service(tmp_path, ObservingGateway(), _planner())

    prepared = _turn(service, "c3-evidence")

    tools = prepared.rag["web_tools"]
    assert tools["used"] is True
    assert tools["read_count"] == 2
    # A research answer is gated: it cannot be published as free text without
    # the evidence binding step, and that step now has real evidence to bind.
    assert answer_validation_active(prepared) is True
    urls = {item["url"] for item in tools["used_sources"]}
    assert urls == {
        "https://alpha.test/report",
        "https://omega.test/follow-up",
    }

    # The model's context contains the read text and the public URL, not just a
    # search snippet or a count.
    assert NEEDLE in captured["rag_context"]
    assert "https://alpha.test/report" in captured["rag_context"]
    assert "https://omega.test/follow-up" in captured["rag_context"]
    assert prepared.web_context_used is True

    # Two rounds are preserved with their source-bearing results.
    searches = [call for call in tools["calls"] if call["name"] == "web_search"]
    assert {call["arguments"]["round"] for call in searches} == {1, 2}
    assert all(call["result"]["results"] for call in searches)

    stored = RuntimeRepository(
        RuntimeDatabase(tmp_path / "runtime.db")
    ).get_chat_turn(prepared.turn.id)
    assert stored is not None
    stored_tools = stored.rag_snapshot["web_tools"]
    assert stored_tools["used"] is True
    assert {item["url"] for item in stored_tools["used_sources"]} == urls


def test_a_deep_run_without_a_read_page_claims_no_source(tmp_path, monkeypatch):
    _balanced_escalation(monkeypatch)
    gateway = EmptyGateway()
    service, _repository, captured = _service(tmp_path, gateway, _planner())

    prepared = _turn(service, "c3-no-evidence")

    tools = prepared.rag["web_tools"]
    assert tools["used"] is False
    assert tools["used_sources"] == []
    assert prepared.web_context_used is False
    assert answer_validation_active(prepared) is True
    assert "https://" not in captured["rag_context"]
    # The research gap is stated, so the answer cannot pretend it verified.
    assert "没有取得任何已读取正文" in captured["rag_context"]
