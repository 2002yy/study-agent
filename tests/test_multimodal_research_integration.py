"""Five-surface offline integration acceptance: multimodal Deep research.

Scenario: the learner uploads a character screenshot, asks a comparison
question, then mid-run corrects the configuration and asks for a recompute.

The same test records five surfaces together:
  * browser        - covered by frontend/e2e/conversation-continuous.spec.ts
                     (composer attachment -> attachment_ids -> computation card)
  * HTTP/SSE       - `_chat_command` request binding + `_research_progress` payload
  * SQLite         - turn attachment_refs and run research_context after reload
  * search trace   - the scripted gateway's query list
  * computation    - old result superseded, new result from the new parameters

No paid model is called: vision is a scripted describer and search is a fixed
gateway. This is offline acceptance, not production qualification.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from src.api.models.chat import ChatRequest
from src.api.routes.chat_routes import _chat_command, _research_progress
from src.application.chat_service import _turn_attachment_material
from src.application.session_attachment_service import SessionAttachmentService
from src.application.web_lookup_service import WebLookupService
from src.domain.runtime_entities import ChatThread, ChatTurn
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.runtime_repository import RuntimeRepository
from src.repositories.session_attachment_repository import SessionAttachmentRepository
from src.repositories.web_lookup_repository import WebLookupRepository

SCREENSHOT_TEXT = "流萤 1 魂，光锥叠影 1"
CORRECTION = "按新配置重算：流萤 2 魂，光锥叠影 5"
# A real 1x1 PNG so the upload pipeline validates the image for real.
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)


class ScriptedGateway:
    def __init__(self, mapping: dict[str, list[dict]]):
        self.mapping = {key.lower(): value for key, value in mapping.items()}
        self.search_calls: list[str] = []
        self.read_calls: list[str] = []

    def search(self, query: str, *, max_items: int = 10):
        self.search_calls.append(query)
        for key, results in self.mapping.items():
            if key in query.lower():
                out = []
                for item in results[:max_items]:
                    record = dict(item)
                    record["title"] = f"{query} - {record.get('title', '')}"
                    record["snippet"] = f"{query}: {record.get('snippet', '')}"
                    out.append(record)
                return out
        return []

    def read(self, url: str, *, max_chars: int = 6000):
        self.read_calls.append(url)
        return {"ok": True, "url": url, "content": f"Deterministic content for {url}. " * 3}

    def warnings(self):
        return []


class ScriptedPlanner:
    """One search task, then a compute decision, then a recompute decision."""

    def __init__(self, initial: list[str]):
        self.initial = initial
        self._round = 0

    def plan(self, query, context):
        return list(self.initial)

    def revise(self, memo, notes, remaining):
        self._round += 1
        if self._round == 1:
            return {
                "done": False,
                "additional": [],
                "compute": {
                    "engine": "deterministic", "mode": "table", "statistic": "mean",
                    "series": {"1魂/叠影1": [10.0, 10.0]}, "unit": "dps",
                },
            }
        if self._round == 2:
            return {
                "done": True,
                "additional": [],
                "compute": {
                    "engine": "deterministic", "mode": "table", "statistic": "mean",
                    "series": {"2魂/叠影5": [18.0, 20.0]}, "unit": "dps",
                },
            }
        return {"done": True, "additional": []}


def _result(url: str, title: str) -> dict:
    return {"title": title, "url": url, "source": "Test source", "snippet": f"Evidence from {title}"}


@pytest.fixture()
def scenario(tmp_path: Path, monkeypatch):
    # The recompute needs an extra bounded round, which the (opt-in) incremental
    # steering budget authorises in production too.
    from test_incremental_research_budget import policy

    monkeypatch.setenv("WEB_RESEARCH_MAX_DEEP_ROUNDS", "1")
    monkeypatch.setenv("WEB_RESEARCH_STEERING_BUDGET_POLICY", json.dumps(policy()))
    database = RuntimeDatabase(tmp_path / "runtime.db")
    database.initialize()
    runtime = RuntimeRepository(database)
    runtime.create_chat_thread(ChatThread(id="thread-firefly", status="active"))

    attachments = SessionAttachmentService(
        SessionAttachmentRepository(database),
        attachment_root=tmp_path / "attachments",
        temp_index_path=tmp_path / "temp_attachments_index.json",
        long_term_index_path=tmp_path / "long_term_index.json",
        vision_describer=lambda _path: SCREENSHOT_TEXT,
        vision_enabled=lambda: True,
    )
    import src.application.runtime_repository as runtime_repository

    monkeypatch.setattr(runtime_repository, "get_session_attachment_service", lambda: attachments)

    gateway = ScriptedGateway({"流萤": [_result("https://example.org/firefly", "流萤机制")]})
    service = WebLookupService(
        WebLookupRepository(database), gateway, planner=ScriptedPlanner(["流萤 伤害 资源"])
    )
    screenshot = attachments.upload(
        "thread-firefly", "firefly.png", PNG_BYTES, content_type="image/png"
    )
    return {
        "runtime": runtime,
        "attachments": attachments,
        "gateway": gateway,
        "service": service,
        "screenshot": screenshot,
    }


def test_multimodal_research_uses_attachment_and_recomputes_after_correction(scenario, monkeypatch):
    runtime = scenario["runtime"]
    attachments = scenario["attachments"]
    gateway = scenario["gateway"]
    service = scenario["service"]
    screenshot = scenario["screenshot"]
    assert screenshot.status == "ready", (screenshot.stage_error, screenshot.stage_history)

    # --- HTTP layer: the request binds only this message's selection ---------
    command = _chat_command(
        ChatRequest(
            user_input="帮我比较流萤两个配置的伤害和资源投入，参考我上传的角色截图",
            session_id="thread-firefly",
            attachment_ids=[screenshot.id],
        ),
        None,
        attachments,
    )
    assert command.attachment_refs[0]["attachment_id"] == screenshot.id

    # --- SQLite: the binding is durable on the turn --------------------------
    runtime.add_chat_turn(
        ChatTurn(
            id="turn-firefly", thread_id="thread-firefly", user_message=command.user_input,
            status="pending", attachment_refs=tuple(command.attachment_refs),
        )
    )
    stored = runtime.get_chat_turn("turn-firefly")
    assert stored is not None and stored.attachment_refs[0]["attachment_id"] == screenshot.id

    # --- Research consumes the bound material (not web evidence) -------------
    material = _turn_attachment_material(runtime, "turn-firefly")
    assert material[0]["text"] == SCREENSHOT_TEXT

    run = service.create(
        command.user_input, owner_thread_id="thread-firefly",
        owner_turn_id="turn-firefly", research_mode="deep",
        attachment_material=material,
    )

    # The learner corrects the configuration mid-run, re-binding the screenshot.
    original_search = gateway.search
    injected = False

    def search(query, *, max_items=10):
        nonlocal injected
        if not injected:
            injected = True
            service.steer(
                run.id, content=CORRECTION, request_id="req-firefly",
                attachment_refs=[{"attachment_id": screenshot.id,
                                  "content_hash": screenshot.content_hash,
                                  "filename": screenshot.filename}],
                attachment_material=[{"attachment_id": screenshot.id, "filename": screenshot.filename,
                                      "content_hash": screenshot.content_hash, "text": SCREENSHOT_TEXT}],
            )
            # Retrying the same supplement must not duplicate it.
            service.steer(run.id, content=CORRECTION, request_id="req-firefly",
                          attachment_refs=[], attachment_material=[])
        return original_search(query, max_items=max_items)

    gateway.search = search
    snapshots = []
    checkpoint = service.repository.checkpoint

    def capture_checkpoint(*args, **kwargs):
        saved = checkpoint(*args, **kwargs)
        snapshots.append(_research_progress(saved))
        return saved

    monkeypatch.setattr(service.repository, "checkpoint", capture_checkpoint)
    completed = service.execute(run.id)

    # --- Computation surface: old result retires, new one is computed --------
    deep = completed.research_context["deep"]
    computations = deep["computations"]
    assert [item["status"] for item in computations] == ["superseded", "succeeded"], (
        "steps=" + ",".join(step["kind"] for step in deep.get("steps", []))
    )
    assert computations[0]["result"]["rows"] == [["1魂/叠影1", 10.0]]
    assert computations[1]["result"]["rows"] == [["2魂/叠影5", 19.0]]
    assert computations[1]["input_revision"] > computations[0]["input_revision"]
    assert computations[1]["source_refs"] == ["https://example.org/firefly"]

    # --- Search trace: the original stream is not restarted ------------------
    assert gateway.search_calls.count("流萤 伤害 资源") == 1
    assert gateway.read_calls.count("https://example.org/firefly") == 1
    assert len(deep["steering"]) == 1
    assert deep["steering"][0]["request_id"] == "req-firefly"
    assert deep["steering"][0]["attachment_refs"][0]["attachment_id"] == screenshot.id
    assert [item["attachment_id"] for item in completed.research_context["attachments"]] == [screenshot.id]

    # --- SSE payload carries the same truth ----------------------------------
    progress = _research_progress(completed)
    assert [item["status"] for item in progress["steering"]] == ["applied"]
    assert progress["narration"]
    assert progress["read_count"] == 1
    assert any(event["status"] == "running" and event["findings"] for event in snapshots)
    assert all(SCREENSHOT_TEXT not in str(event["findings"]) for event in snapshots)
    # The attachment's own text never leaks into the published source block
    # (the search query legitimately mentions the character's name).
    assert SCREENSHOT_TEXT not in completed.source_block


def test_cross_session_and_deleted_attachments_are_rejected(scenario):
    runtime = scenario["runtime"]
    attachments = scenario["attachments"]
    screenshot = scenario["screenshot"]
    runtime.create_chat_thread(ChatThread(id="thread-other", status="active"))

    with pytest.raises(ValueError, match="附件不可用"):
        _chat_command(
            ChatRequest(user_input="hi", session_id="thread-other", attachment_ids=[screenshot.id]),
            None, attachments,
        )

    attachments.delete_attachment(screenshot.id)
    with pytest.raises(ValueError, match="附件不可用"):
        _chat_command(
            ChatRequest(user_input="hi", session_id="thread-firefly", attachment_ids=[screenshot.id]),
            None, attachments,
        )


def test_vision_disabled_attachment_carries_no_material(tmp_path, monkeypatch):
    database = RuntimeDatabase(tmp_path / "runtime.db")
    database.initialize()
    attachments = SessionAttachmentService(
        SessionAttachmentRepository(database),
        attachment_root=tmp_path / "attachments",
        temp_index_path=tmp_path / "temp_attachments_index.json",
        long_term_index_path=tmp_path / "long_term_index.json",
        vision_describer=lambda _path: SCREENSHOT_TEXT,
        vision_enabled=lambda: False,
    )
    image = attachments.upload(
        "thread-x", "shot.png", PNG_BYTES, content_type="image/png"
    )
    assert image.status == "ready"
    # Vision off: the attachment is stored but contributes no research material.
    assert attachments.attachment_material("thread-x", [image.id]) == []
