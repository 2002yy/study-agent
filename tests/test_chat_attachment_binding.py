"""Message-level attachment binding: A-protocol acceptance.

Plain-text turns stay unchanged; an attachment selection is validated against
the session, bound to the turn with server-owned identity, and survives a
reload. Retries never silently replace an existing binding.
"""

from __future__ import annotations

import pytest

from src.api.models.chat import ChatRequest
from src.api.routes.chat_routes import _chat_command
from src.application.session_attachment_service import SessionAttachmentService
from src.domain.runtime_entities import ChatThread, ChatTurn
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.runtime_repository import RuntimeRepository
from src.repositories.session_attachment_repository import SessionAttachmentRepository


def _context(tmp_path):
    database = RuntimeDatabase(tmp_path / "runtime.db")
    database.initialize()
    repository = RuntimeRepository(database)
    attachments = SessionAttachmentService(
        SessionAttachmentRepository(database),
        attachment_root=tmp_path / "attachments",
        temp_index_path=tmp_path / "temp_attachments_index.json",
        long_term_index_path=tmp_path / "long_term_index.json",
        vision_describer=None,
        vision_enabled=None,
    )
    for thread_id in ("thread-a", "thread-b"):
        repository.create_chat_thread(ChatThread(id=thread_id, status="active"))
    return repository, attachments


def _ready(attachments: SessionAttachmentService, thread_id: str = "thread-a", name: str = "notes.md"):
    return attachments.upload(
        thread_id, name, b"# notes\n\nattention and memory.", content_type="text/markdown"
    )


def _request(session_id, attachment_ids):
    return ChatRequest(user_input="比较两个配置", session_id=session_id, attachment_ids=attachment_ids)


def test_plain_text_turn_carries_no_attachment_refs(tmp_path):
    _, attachments = _context(tmp_path)
    command = _chat_command(_request("thread-a", []), None, attachments)
    assert command.attachment_refs == []


def test_selection_is_bound_with_server_owned_identity(tmp_path):
    _, attachments = _context(tmp_path)
    ready = _ready(attachments)
    command = _chat_command(_request("thread-a", [ready.id, ready.id]), None, attachments)
    assert command.attachment_refs == [
        {
            "attachment_id": ready.id,
            "content_hash": ready.content_hash,
            "filename": "notes.md",
        }
    ]


def test_foreign_and_unknown_attachments_are_refused_before_research(tmp_path):
    _, attachments = _context(tmp_path)
    foreign = _ready(attachments, "thread-b", "other.md")
    with pytest.raises(ValueError, match="附件不可用"):
        _chat_command(_request("thread-a", [foreign.id]), None, attachments)
    with pytest.raises(ValueError, match="附件不可用"):
        _chat_command(_request("thread-a", ["att_missing"]), None, attachments)


def test_not_ready_attachment_is_refused(tmp_path):
    _, attachments = _context(tmp_path)
    from src.domain.runtime_entities import SessionAttachment

    pending = attachments.repository.create(
        SessionAttachment(
            thread_id="thread-a", filename="pending.md", content_hash="h", status="parsing"
        )
    )
    with pytest.raises(ValueError, match="attachment_not_ready"):
        _chat_command(_request("thread-a", [pending.id]), None, attachments)


def test_selection_requires_a_session(tmp_path):
    _, attachments = _context(tmp_path)
    with pytest.raises(ValueError, match="先有会话"):
        _chat_command(ChatRequest(user_input="hi", attachment_ids=["att_x"]), None, attachments)


def test_binding_is_persisted_and_survives_reload(tmp_path):
    repository, attachments = _context(tmp_path)
    ready = _ready(attachments)
    command = _chat_command(_request("thread-a", [ready.id]), None, attachments)
    repository.add_chat_turn(
        ChatTurn(
            id="turn-1",
            thread_id="thread-a",
            user_message=command.user_input,
            status="pending",
            attachment_refs=tuple(command.attachment_refs),
        )
    )
    reloaded = repository.get_chat_turn("turn-1")
    assert reloaded is not None
    assert reloaded.attachment_refs == tuple(command.attachment_refs)


def test_retry_does_not_replace_a_stored_binding(tmp_path):
    repository, attachments = _context(tmp_path)
    first = _ready(attachments, "thread-a", "first.md")
    second = _ready(attachments, "thread-a", "second.md")
    repository.add_chat_turn(
        ChatTurn(
            id="turn-1",
            thread_id="thread-a",
            user_message="q",
            status="pending",
            attachment_refs=({"attachment_id": first.id, "content_hash": first.content_hash, "filename": "first.md"},),
        )
    )
    # The continuation reuses the stored turn; re-binding must be explicit.
    stored = repository.get_chat_turn("turn-1")
    assert stored is not None and stored.attachment_refs[0]["attachment_id"] == first.id
    rebound = repository.bind_turn_attachments("turn-1", [{"attachment_id": second.id}])
    assert rebound.attachment_refs[0]["attachment_id"] == second.id
