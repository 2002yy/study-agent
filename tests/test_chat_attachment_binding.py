"""Message-level attachment binding: A-protocol acceptance.

Plain-text turns stay unchanged; an attachment selection is validated against
the session, bound to the turn with server-owned identity, and survives a
reload. Retries never silently replace an existing binding.
"""

from __future__ import annotations

import pytest

from src.api.models.chat import ChatRequest
from src.api.routes.chat_routes import _chat_command
from src.application.chat_service import (
    ATTACHMENT_BLOCK_HEADING,
    ATTACHMENT_BLOCK_MAX_CHARS,
    _turn_attachment_material,
    attachment_context_block,
)
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


def _model_service(repository, sent, service_class="base"):
    from src.application.chat_service import ChatDependencies, ChatService
    from src.application.policy_chat_service import ExternalDataPolicyChatService
    from src.context_builder import build_messages
    from src.mode_manager import RuntimeModes
    from src.task_contract import TaskAwarePedagogyEngine, TaskAwarePedagogyEvaluationService
    from src.tools.web_agent import WebToolTrace

    def fake_chat(messages, **_kwargs):
        sent.extend(messages)
        return "Attached material acknowledged"

    class EmptyRag:
        def to_dict(self):
            return {"status": "empty", "context": "", "result_count": 0, "results": []}

    deps = ChatDependencies(
        load_runtime_modes=lambda: RuntimeModes(memory_mode="preview", performance_mode="standard"),
        read_memory_bundle=lambda _mode: {},
        build_role_prompt=lambda _role, **_kw: "role prompt",
        route_request=lambda **_kw: {"role": "nahida", "mode": "普通", "model_profile": "flash"},
        retrieve_local_knowledge=lambda *_args, **_kw: EmptyRag(),
        build_messages=build_messages,
        chat=fake_chat,
        resolve_web_tools=lambda *_args, **_kw: WebToolTrace(enabled=False),
        pedagogy_engine=TaskAwarePedagogyEngine(),
        pedagogy_evaluation=TaskAwarePedagogyEvaluationService(),
    )
    service = ChatService if service_class == "base" else ExternalDataPolicyChatService
    return service(repository, deps)


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


def test_ready_image_without_vision_cannot_silently_reach_the_model(tmp_path):
    _, attachments = _context(tmp_path)
    image = attachments.upload("thread-a", "diagram.png", b"\x89PNG\r\nimage", content_type="image/png")
    assert image.status == "ready"  # Stored successfully, but no description exists.
    assert attachments.attachment_material("thread-a", [image.id]) == []

    with pytest.raises(ValueError, match="图片尚未识别"):
        _chat_command(_request("thread-a", [image.id]), None, attachments)


def test_ready_document_without_its_index_cannot_silently_reach_the_model(tmp_path):
    _, attachments = _context(tmp_path)
    ready = _ready(attachments)
    attachments.temp_index_path.unlink()  # Simulate an index lost after upload.

    with pytest.raises(ValueError, match="附件正文无法读取"):
        _chat_command(_request("thread-a", [ready.id]), None, attachments)


def test_material_disappearing_between_validation_and_binding_is_rejected(tmp_path, monkeypatch):
    _, attachments = _context(tmp_path)
    ready = _ready(attachments)
    monkeypatch.setattr(attachments, "selection_refs", lambda *_args: [])

    with pytest.raises(ValueError, match="附件状态已变化"):
        _chat_command(_request("thread-a", [ready.id]), None, attachments)


@pytest.mark.parametrize("service_class", ["base", "policy"])
def test_bound_attachment_disappearing_before_preparation_fails_before_model(tmp_path, monkeypatch, service_class):
    repository, attachments = _context(tmp_path)
    ready = _ready(attachments)
    command = _chat_command(_request("thread-a", [ready.id]), None, attachments)
    attachments.temp_index_path.unlink()  # After binding, before model preparation.
    import src.application.runtime_repository as runtime_repository

    monkeypatch.setattr(runtime_repository, "get_session_attachment_service", lambda: attachments)
    sent = []
    service = _model_service(repository, sent, service_class)

    with pytest.raises(ValueError, match="本轮所选附件正文无法读取"):
        service.start_turn(command)
    assert sent == []
    turns = repository.list_chat_turns("thread-a")
    assert len(turns) == 1 and turns[0].status == "failed"


@pytest.mark.parametrize("service_class", ["base", "policy"])
def test_bound_attachment_hash_change_fails_before_model(tmp_path, monkeypatch, service_class):
    repository, attachments = _context(tmp_path)
    ready = _ready(attachments)
    command = _chat_command(_request("thread-a", [ready.id]), None, attachments)
    command.attachment_refs[0]["content_hash"] = "outdated"
    import src.application.runtime_repository as runtime_repository

    monkeypatch.setattr(runtime_repository, "get_session_attachment_service", lambda: attachments)
    sent = []
    service = _model_service(repository, sent, service_class)

    with pytest.raises(ValueError, match="本轮所选附件正文无法读取"):
        service.start_turn(command)
    assert sent == []
    assert repository.list_chat_turns("thread-a")[0].status == "failed"


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


def test_turn_material_reads_the_stored_binding(tmp_path, monkeypatch):
    repository, attachments = _context(tmp_path)
    ready = _ready(attachments)
    repository.add_chat_turn(
        ChatTurn(
            id="turn-1", thread_id="thread-a", user_message="q", status="pending",
            attachment_refs=(
                {"attachment_id": ready.id, "content_hash": ready.content_hash, "filename": "notes.md"},
            ),
        )
    )
    import src.application.runtime_repository as runtime_repository

    monkeypatch.setattr(runtime_repository, "get_session_attachment_service", lambda: attachments)

    material = _turn_attachment_material(repository, "turn-1")
    assert [item["attachment_id"] for item in material] == [ready.id]
    assert "attention" in material[0]["text"]
    assert _turn_attachment_material(repository, "turn-missing") == []


def test_prompt_block_carries_attachment_text_for_a_plain_turn(tmp_path, monkeypatch):
    """A just-uploaded file must reach the model even with local RAG off.

    Attachment text used to join the prompt only through retrieval, so a plain
    turn answered "I cannot see any attachment" while the file was ready.
    """
    repository, attachments = _context(tmp_path)
    ready = _ready(attachments)
    repository.add_chat_turn(
        ChatTurn(
            id="turn-block", thread_id="thread-a", user_message="q", status="pending",
            attachment_refs=(
                {"attachment_id": ready.id, "content_hash": ready.content_hash, "filename": "notes.md"},
            ),
        )
    )
    import src.application.runtime_repository as runtime_repository

    monkeypatch.setattr(runtime_repository, "get_session_attachment_service", lambda: attachments)

    block = attachment_context_block(repository, "turn-block")

    assert block.startswith(ATTACHMENT_BLOCK_HEADING)
    assert "notes.md" in block
    assert "attention" in block
    assert len(block) <= ATTACHMENT_BLOCK_MAX_CHARS + 400
    assert attachment_context_block(repository, None) == ""
    assert attachment_context_block(repository, "turn-without-attachments") == ""


@pytest.mark.parametrize("service_class", ["base", "policy"])
def test_five_selected_attachments_all_reach_the_model_with_a_bounded_excerpt(tmp_path, monkeypatch, service_class):
    repository, attachments = _context(tmp_path)
    selected = [
        attachments.upload(
            "thread-a", f"part-{index}.md",
            (f"FILE_{index}_PRESENT\n" + "details " * 850).encode(),
            content_type="text/markdown",
        )
        for index in range(5)
    ]
    command = _chat_command(_request("thread-a", [item.id for item in selected]), None, attachments)
    assert len(command.attachment_refs) == 5
    import src.application.runtime_repository as runtime_repository

    monkeypatch.setattr(runtime_repository, "get_session_attachment_service", lambda: attachments)
    sent: list[dict] = []
    service = _model_service(repository, sent, service_class)
    prepared = service.start_turn(command)
    service.generate(prepared)

    model_input = "\n".join(str(item["content"]) for item in sent)
    for index in range(5):
        assert f"FILE_{index}_PRESENT" in model_input
    block = attachment_context_block(repository, prepared.turn.id)
    assert len(block) <= ATTACHMENT_BLOCK_MAX_CHARS + 600
    assert "截断" in block  # Do not imply the entire original was included.


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


@pytest.mark.parametrize("service_class", [
    "src.application.chat_service.ChatService",
    "src.application.policy_chat_service.ExternalDataPolicyChatService",
])
def test_retry_preserves_server_owned_attachment_refs(tmp_path, monkeypatch, service_class):
    from importlib import import_module
    from src.application.chat_service import ChatCommand

    repository, attachments = _context(tmp_path)
    ready = _ready(attachments, "thread-a", "original.md")
    original = {"attachment_id": ready.id, "content_hash": ready.content_hash,
                "filename": "original.md"}
    repository.add_chat_turn(ChatTurn(
        id="original-turn", thread_id="thread-a", user_message="original question",
        status="failed", attachment_refs=(original,),
    ))
    module, name = service_class.rsplit(".", 1)
    service = getattr(import_module(module), name)(repository)
    command, existing, parent = service._validate_turn_command(ChatCommand(
        user_input="untrusted new question", thread_id="thread-a",
        retry_of_turn_id="original-turn",
        attachment_refs=[{"attachment_id": "client-swapped"}],
    ))
    assert existing is None and parent is not None
    assert command.user_input == "original question"
    assert command.attachment_refs == [original]

    repository.add_chat_turn(ChatTurn(
        id="retried-turn", thread_id="thread-a", user_message=command.user_input,
        status="pending", attachment_refs=tuple(command.attachment_refs),
    ))
    import src.application.runtime_repository as runtime_repository
    monkeypatch.setattr(runtime_repository, "get_session_attachment_service", lambda: attachments)
    material = _turn_attachment_material(repository, "retried-turn")
    assert len(material) == 1 and material[0]["attachment_id"] == ready.id
