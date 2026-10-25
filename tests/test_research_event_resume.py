"""CL-M3-S2-C3b: the stage log is durable and an SSE client can resume it.

The run already persisted its stages inside its SQLite row. This endpoint reads
that log only: reconnecting cannot restart research, and the cursor is the
sequence the client last saw. A resumed stream returns later steps exactly once.
"""

from __future__ import annotations

import json
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routes.web_lookup_routes import TERMINAL_RUN_STATUSES, router
from src.application.runtime_repository import get_web_lookup_service
from src.domain.runtime_entities import WebLookupRun
from tests.test_research_observation_feedback import (
    FIRST_SUB_QUESTION,
    ObservingGateway,
    ObservingPlanner,
    _balanced_escalation,
    _service,
    _turn,
)


def _frames(text: str) -> list[str]:
    return [block for block in text.split("\n\n") if block.strip()]


def _field(block: str, name: str) -> str:
    prefix = f"{name}: "
    for line in block.splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :]
    return ""


def _step_frames(text: str) -> list[str]:
    return [block for block in _frames(text) if _field(block, "event") == "research_step"]


def _app(lookup) -> tuple[FastAPI, TestClient]:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_web_lookup_service] = lambda: lookup
    return app, TestClient(app)


def _run(tmp_path, monkeypatch):
    _balanced_escalation(monkeypatch)
    service, _repository, captured = _service(
        tmp_path,
        ObservingGateway(),
        ObservingPlanner(initial=[FIRST_SUB_QUESTION], seen_notes=[], added=[]),
    )
    prepared = _turn(service, "c3-events")
    run_id = prepared.rag["web_tools"]["run_id"]
    return captured["lookup"], run_id


def test_reconnect_resumes_after_the_last_seen_step(tmp_path, monkeypatch):
    lookup, run_id = _run(tmp_path, monkeypatch)
    _app_obj, client = _app(lookup)
    run = lookup.get(run_id)
    steps = (run.research_context.get("deep") or {}).get("steps") or []
    assert len(steps) >= 2
    assert all(int(step.get("seq") or 0) > 0 for step in steps)

    with client.stream("GET", f"/research-runs/{run_id}/events") as response:
        assert response.status_code == 200
        full_text = "".join(response.iter_text())
    full_steps = _step_frames(full_text)
    assert len(full_steps) == len(steps)
    ids = [int(_field(block, "id")) for block in full_steps]
    assert ids == sorted(ids)
    assert ids == [int(step["seq"]) for step in steps]
    kinds = {json.loads(_field(block, "data"))["kind"] for block in full_steps}
    assert {"planning", "read", "revise"} <= kinds
    idle = [block for block in _frames(full_text) if _field(block, "event") == "research_idle"]
    assert idle and json.loads(_field(idle[0], "data"))["status"] == "completed"

    # Reconnect from the first step: no replay of it, only later steps.
    with client.stream(
        "GET",
        f"/research-runs/{run_id}/events",
        headers={"Last-Event-ID": str(ids[0])},
    ) as response:
        resumed_text = "".join(response.iter_text())
    resumed = _step_frames(resumed_text)
    assert [int(_field(block, "id")) for block in resumed] == ids[1:]
    first_text = json.loads(_field(full_steps[0], "data"))["text"]
    assert first_text not in resumed_text
    assert "event: research_idle" in resumed_text

    # Reading the log started no research and changed no durable state.
    after = lookup.get(run_id)
    assert after.status == run.status
    assert len(after.query_attempts) == len(run.query_attempts)


def test_an_unknown_run_is_a_404_before_any_stream_opens(tmp_path, monkeypatch):
    lookup, _run_id = _run(tmp_path, monkeypatch)
    _app_obj, client = _app(lookup)

    response = client.get("/research-runs/does-not-exist/events")

    assert response.status_code == 404


def test_after_query_uses_the_same_cursor_as_the_header(tmp_path, monkeypatch):
    lookup, run_id = _run(tmp_path, monkeypatch)
    _app_obj, client = _app(lookup)
    run = lookup.get(run_id)
    steps = (run.research_context.get("deep") or {}).get("steps") or []
    first_seq = int(steps[0]["seq"])

    with client.stream(
        "GET", f"/research-runs/{run_id}/events?after={first_seq}"
    ) as response:
        text = "".join(response.iter_text())

    assert [int(_field(block, "id")) for block in _step_frames(text)] == [
        int(step["seq"]) for step in steps[1:]
    ]


def _idle_payload(text: str) -> dict:
    idle = [
        block for block in _frames(text) if _field(block, "event") == "research_idle"
    ]
    assert idle
    return json.loads(_field(idle[0], "data"))


def test_a_partial_run_ends_the_stream_without_waiting(tmp_path, monkeypatch):
    lookup, _run_id = _run(tmp_path, monkeypatch)
    run = WebLookupRun(
        query="partial research",
        stage="partial",
        status="partial",
        provider_status="partial",
        research_context={
            "deep": {
                "steps": [
                    {"seq": 1, "kind": "read", "text": "read page", "at": ""}
                ]
            }
        },
    )
    lookup.repository.create(run)
    _app_obj, client = _app(lookup)
    # A partial run is terminal for the stage feed: assert this before opening
    # the stream so a regression fails fast instead of waiting for the timeout.
    assert "partial" in TERMINAL_RUN_STATUSES

    started = time.monotonic()
    with client.stream(
        "GET", f"/research-runs/{run.id}/events?after=1"
    ) as response:
        text = "".join(response.iter_text())

    # No 300-second wait: a partial run is terminal for the stage feed.
    assert time.monotonic() - started < 2.0
    assert _step_frames(text) == []
    assert _idle_payload(text) == {"run_id": run.id, "status": "partial"}


def test_an_idle_running_run_reports_running_not_completed(tmp_path, monkeypatch):
    lookup, _run_id = _run(tmp_path, monkeypatch)
    run = WebLookupRun(
        query="still running",
        stage="reading",
        status="running",
        provider_status="",
        research_context={
            "deep": {
                "steps": [
                    {"seq": 1, "kind": "read", "text": "read page", "at": ""}
                ]
            }
        },
    )
    lookup.repository.create(run)
    _app_obj, client = _app(lookup)
    monkeypatch.setattr(
        "src.api.routes.web_lookup_routes.STEP_IDLE_TIMEOUT_SECONDS", 0.15
    )
    monkeypatch.setattr(
        "src.api.routes.web_lookup_routes.STEP_POLL_SECONDS", 0.01
    )

    with client.stream(
        "GET", f"/research-runs/{run.id}/events?after=1"
    ) as response:
        text = "".join(response.iter_text())

    assert _step_frames(text) == []
    # Idle means "no new step", not "the research finished".
    assert _idle_payload(text) == {"run_id": run.id, "status": "running"}
