"""Queued multimodal questions retain their own server-owned attachment binding."""

import json

import pytest
from fastapi import HTTPException

from src.api.models.chat import ChatRequest
from src.api.models.news import ResearchQueueRequest
from src.api.routes.chat_routes import _chat_command
from src.api.routes.web_lookup_routes import queue_research_followup
from src.application.web_lookup_service import WebLookupService
from src.domain.runtime_entities import ChatTurn
from src.repositories.web_lookup_repository import WebLookupRepository
from test_chat_attachment_binding import _context, _ready


@pytest.fixture
def queued_context(tmp_path, monkeypatch):
    runtime, attachments = _context(tmp_path)
    import src.application.runtime_repository as factories

    monkeypatch.setattr(factories, "get_session_attachment_service", lambda: attachments)
    repository = WebLookupRepository(runtime.database)
    service = WebLookupService(repository, object())
    run = service.create("first question", owner_thread_id="thread-a")
    return runtime, attachments, repository, service, run


def test_queue_binding_survives_checkpoint_reload_and_later_turn(queued_context):
    runtime, attachments, repository, service, run = queued_context
    ready = _ready(attachments)
    request = ResearchQueueRequest(content="use my notes later", request_id="queue1", attachment_ids=[ready.id])
    operation = service.begin_tool_trace(run.id)
    stale = service.get(run.id)
    queue_research_followup(run.id, request, service)
    queue_research_followup(run.id, request, service)
    repository.checkpoint(
        run.id, operation_id=operation, research_context=stale.research_context,
        query_attempts=[], selected_sources=[], rejected_sources=[], items=[], warnings=[],
    )
    reloaded = WebLookupRepository(runtime.database)
    pending = reloaded.pending_followups("thread-a")
    assert len(pending) == 1
    refs = pending[0]["attachment_refs"]
    assert refs == [{"attachment_id": ready.id, "content_hash": ready.content_hash, "filename": ready.filename}]
    assert reloaded.pending_followups("thread-b") == []
    command = _chat_command(ChatRequest(
        user_input="use my notes later", session_id="thread-a", attachment_ids=[ref["attachment_id"] for ref in refs],
    ), None, attachments)
    runtime.add_chat_turn(ChatTurn(
        id="turn_queue1", thread_id="thread-a", user_message=request.content,
        status="completed", attachment_refs=tuple(command.attachment_refs),
    ))
    assert reloaded.pending_followups("thread-a") == []
    delivered = reloaded.complete_followup(run.id, request_id="queue1", turn_id="turn_queue1")
    assert delivered.research_context["conversation_queue"][0]["status"] == "completed"


@pytest.mark.parametrize("invalid", ["foreign", "deleted", "not-ready", "unknown"])
def test_queue_rejects_invalid_selection_without_saving_text_only(queued_context, invalid):
    runtime, attachments, repository, service, run = queued_context
    ready = _ready(attachments, "thread-b" if invalid == "foreign" else "thread-a")
    if invalid == "deleted":
        attachments.delete_attachment(ready.id)
    if invalid == "not-ready":
        with runtime.database.connect() as connection:
            connection.execute("UPDATE session_attachments SET status = 'pending' WHERE id = ?", (ready.id,))
    with pytest.raises(HTTPException) as error:
        queue_research_followup(run.id, ResearchQueueRequest(
            content="use the file", request_id="queue1", attachment_ids=["missing" if invalid == "unknown" else ready.id],
        ), service)
    assert error.value.status_code == 409
    assert repository.pending_followups("thread-a") == []


def test_queue_identity_cannot_be_reused_for_other_attachments(queued_context):
    _, attachments, _, service, run = queued_context
    first = _ready(attachments)
    second = attachments.upload("thread-a", "second.txt", b"different content", content_type="text/plain")
    queue_research_followup(run.id, ResearchQueueRequest(content="same text", request_id="queue1", attachment_ids=[first.id]), service)
    with pytest.raises(HTTPException) as error:
        queue_research_followup(run.id, ResearchQueueRequest(content="same text", request_id="queue1", attachment_ids=[second.id]), service)
    assert error.value.status_code == 409


def test_attachment_disappearing_during_binding_does_not_queue_text_only(queued_context, monkeypatch):
    _, attachments, repository, service, run = queued_context
    ready = _ready(attachments)
    monkeypatch.setattr(attachments, "selection_refs", lambda *_: [])
    with pytest.raises(HTTPException) as error:
        queue_research_followup(run.id, ResearchQueueRequest(content="later", request_id="queue1", attachment_ids=[ready.id]), service)
    assert error.value.status_code == 409
    assert repository.pending_followups("thread-a") == []


def test_deleted_queued_file_is_rejected_at_delivery(queued_context):
    _, attachments, repository, service, run = queued_context
    ready = _ready(attachments)
    queue_research_followup(run.id, ResearchQueueRequest(content="later", request_id="queue1", attachment_ids=[ready.id]), service)
    attachments.delete_attachment(ready.id)
    refs = repository.pending_followups("thread-a")[0]["attachment_refs"]
    with pytest.raises(ValueError, match="附件不可用"):
        _chat_command(ChatRequest(user_input="later", session_id="thread-a", attachment_ids=[ref["attachment_id"] for ref in refs]), None, attachments)


@pytest.mark.parametrize("wrong_binding", ["none", "other-file", "other-version"])
def test_text_only_or_wrong_file_turn_does_not_complete_queued_file_question(queued_context, wrong_binding):
    runtime, attachments, repository, service, run = queued_context
    ready = _ready(attachments)
    wrong_refs = [] if wrong_binding == "none" else [{
        "attachment_id": ready.id if wrong_binding == "other-version" else "other",
        "content_hash": "other",
    }]
    queue_research_followup(run.id, ResearchQueueRequest(content="later", request_id="queue1", attachment_ids=[ready.id]), service)
    runtime.add_chat_turn(ChatTurn(id="turn_queue1", thread_id="thread-a", user_message="later", status="completed"))
    with runtime.database.connect() as connection:
        connection.execute("UPDATE chat_turns SET attachment_refs = ? WHERE id = 'turn_queue1'", (json.dumps(wrong_refs),))
    assert len(repository.pending_followups("thread-a")) == 1
    with pytest.raises(ValueError, match="matching attachments"):
        repository.complete_followup(run.id, request_id="queue1", turn_id="turn_queue1")
