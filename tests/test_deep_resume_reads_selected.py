"""CL-M3 S2-C: a resumed deep run must read what its attempt had queued.

A deep run persists its source selection before it reads the page. If the user
stops the run in that window, the retry starts from durable state where the
candidate is already "selected" and therefore de-duplicated on the next round.
Before this regression the retry never read it, the run finished with
``provider_status=candidates_only`` and no note, so "重试研究" silently produced
research with no evidence at all.

The cancellation is injected where the real one is observed: the stage write to
"reading" happens between persisting the selection and the first read, and the
next ``ensure_active`` sees the cancel request.
"""

from __future__ import annotations

from typing import Any

from src.application.web_lookup_service import WebLookupService
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.web_lookup_repository import WebLookupRepository

SOURCE_URL = "https://alpha.test/report"
READ_TEXT = "RESUMED-READ-OK the report states the measured latency."


class RecordingGateway:
    def __init__(self) -> None:
        self.search_calls: list[str] = []
        self.read_calls: list[str] = []

    def search(self, query: str, *, max_items: int = 10) -> list[dict[str, Any]]:
        self.search_calls.append(query)
        return [
            {
                "title": "Alpha report",
                "url": SOURCE_URL,
                "snippet": "Alpha latency report",
            }
        ][:max_items]

    def read(self, url: str, *, max_chars: int = 6000) -> dict[str, Any]:
        self.read_calls.append(url)
        return {"ok": True, "url": url, "content": READ_TEXT[:max_chars]}

    def warnings(self) -> list[dict[str, str]]:
        return []


class SingleQuestionPlanner:
    def plan(self, query: str, context: Any) -> list[str]:
        return ["alpha latency"]

    def revise(
        self,
        memo: str,
        notes: list[dict[str, Any]],
        remaining: list[str],
        context: Any = None,
    ) -> dict[str, Any]:
        return {"done": True, "additional": [], "compute": None}


def _service(tmp_path) -> tuple[WebLookupService, RecordingGateway]:
    repository = WebLookupRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    gateway = RecordingGateway()
    return WebLookupService(repository, gateway, planner=SingleQuestionPlanner()), gateway


def test_a_retried_deep_run_reads_the_source_its_cancelled_attempt_selected(
    tmp_path, monkeypatch
):
    service, gateway = _service(tmp_path)
    run = service.create("alpha latency comparison", research_mode="deep")

    original_set_stage = service.repository.set_stage
    cancelled_once = False

    def cancel_at_reading(run_id: str, *, stage: str, operation_id: str):
        nonlocal cancelled_once
        saved = original_set_stage(run_id, stage=stage, operation_id=operation_id)
        if stage == "reading" and not cancelled_once:
            cancelled_once = True
            service.repository.request_cancel(run_id)
        return saved

    monkeypatch.setattr(service.repository, "set_stage", cancel_at_reading)
    stopped = service.execute(run.id)

    # The interrupt landed after the selection was persisted and before the read.
    assert stopped.status == "cancelled"
    assert gateway.read_calls == []
    queued = [
        record
        for record in stopped.selected_sources
        if isinstance(record.get("assessment"), dict)
        and record["assessment"].get("worth_reading") is True
    ]
    assert queued, "the interrupted attempt must leave its selection durable"
    assert all(not record.get("read") for record in queued)

    monkeypatch.setattr(service.repository, "set_stage", original_set_stage)
    resumed = service.execute(run.id)

    # The retry read the queued page instead of finishing on titles alone.
    assert gateway.read_calls == [SOURCE_URL]
    assert resumed.status == "completed"
    assert resumed.provider_status == "found"
    notes = resumed.research_context["deep"]["notes"]
    assert [note["url"] for note in notes] == [SOURCE_URL]
    assert READ_TEXT in notes[0]["facts"]
