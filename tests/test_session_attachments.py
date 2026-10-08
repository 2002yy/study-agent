"""G14 temporary session attachment lifecycle tests.

Contract: docs/PROJECT_STATUS.md section 12 (decisions 1-16, acceptance
gates v2). These tests run the real pipeline against a temporary SQLite
database and temporary storage/index paths; only the vision describer is
faked.
"""

from __future__ import annotations

import pytest

from src.application.session_attachment_service import (
    AttachmentLimitError,
    SessionAttachmentService,
)
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.rag.index import load_rag_index
from src.repositories.session_attachment_repository import (
    SessionAttachmentRepository,
)


SAMPLE_TEXT = (
    "# 临时附件样例\n\n"
    "注意力机制通过查询、键、值三组向量计算上下文相关性。\n\n"
    "多头注意力允许模型在不同的表示子空间中并行关注信息。\n"
)


def _service(tmp_path, *, describer=None, vision_enabled=None):
    database = RuntimeDatabase(tmp_path / "runtime.db")
    repository = SessionAttachmentRepository(database)
    return SessionAttachmentService(
        repository,
        attachment_root=tmp_path / "attachments",
        temp_index_path=tmp_path / "temp_attachments_index.json",
        long_term_index_path=tmp_path / "long_term_index.json",
        vision_describer=describer,
        vision_enabled=vision_enabled,
    )


def _upload_sample(service: SessionAttachmentService, thread_id: str):
    return service.upload(
        thread_id,
        "attention.md",
        SAMPLE_TEXT.encode("utf-8"),
        content_type="text/markdown",
    )


def test_upload_reaches_ready_with_stage_history(tmp_path):
    service = _service(tmp_path)
    attachment = _upload_sample(service, "thread_a")

    assert attachment.status == "ready"
    stages = [entry["stage"] for entry in attachment.stage_history]
    assert stages == ["upload", "parsing", "chunking", "indexing"]
    indexing_entry = attachment.stage_history[-1]
    assert indexing_entry["retrievable"] is True
    assert indexing_entry["chunks"] >= 1


def test_thread_isolated_retrieval(tmp_path):
    service = _service(tmp_path)
    _upload_sample(service, "thread_a")

    hits_a = service.retrieve_for_thread("注意力机制", "thread_a")
    hits_b = service.retrieve_for_thread("注意力机制", "thread_b")

    assert hits_a, "attachment chunk must be retrievable inside its thread"
    assert hits_b == [], "other threads must never see the attachment"
    # Every hit resolves back to a document tagged with this thread.
    snapshot = service.temp_index_snapshot()
    assert snapshot is not None
    docs_by_id = {
        doc.document_id or doc.content_hash: doc for doc in snapshot.documents
    }
    for hit in hits_a:
        owner = docs_by_id[
            hit.chunk.document_id or hit.chunk.document_hash
        ]
        assert owner.metadata.get("thread_id") == "thread_a"
        assert hit.chunk.metadata["thread_id"] == "thread_a"
        assert hit.chunk.metadata["attachment_id"] == owner.metadata["attachment_id"]
        assert hit.chunk.revision_id == owner.revision_id


def test_legacy_chunk_citation_binding_does_not_write_index_or_change_ids(tmp_path):
    service = _service(tmp_path)
    attachment = _upload_sample(service, "thread_a")
    before = service.temp_index_path.read_bytes()
    index = load_rag_index(service.temp_index_path)
    assert "attachment_id" not in index.chunks[0].metadata
    hits = service.retrieve_for_thread("注意力机制", "thread_a")
    assert hits and hits[0].chunk.metadata["attachment_id"] == attachment.id
    assert hits[0].chunk.chunk_id == index.chunks[0].chunk_id
    assert service.temp_index_path.read_bytes() == before
    service.repository.delete(attachment.id)
    assert service.retrieve_for_thread("注意力机制", "thread_a") == []


def test_upload_limit_and_size_guard(tmp_path):
    service = _service(tmp_path)
    for index in range(10):
        service.upload(
            "thread_x",
            f"doc{index}.txt",
            f"document number {index} with unique words {index * 7}".encode(),
        )
    with pytest.raises(AttachmentLimitError):
        service.upload("thread_x", "doc11.txt", b"one document too many")
    with pytest.raises(ValueError):
        service.upload(
            "thread_y", "huge.bin"[:0] or "huge.txt", b"x" * (21 * 1024 * 1024)
        )


def test_unsupported_type_rejected(tmp_path):
    service = _service(tmp_path)
    with pytest.raises(ValueError):
        service.upload("thread_a", "script.exe", b"MZ fake binary")


def test_corrupt_pdf_fails_then_manual_retry(tmp_path):
    service = _service(tmp_path)
    corrupt = b"%PDF-1.4 broken payload without real structure"
    attachment = service.upload("thread_a", "broken.pdf", corrupt)

    assert attachment.status == "failed"
    assert attachment.retry_count == 1
    assert attachment.stage_error

    # Failed files must not contribute fragments to any question context.
    hits = service.retrieve_for_thread("注意力机制", "thread_a")
    assert hits == []

    retried = service.retry(attachment.id)
    assert retried.status == "failed"
    assert retried.retry_count == 2


def test_delete_attachment_removes_file_row_and_chunks(tmp_path):
    service = _service(tmp_path)
    attachment = _upload_sample(service, "thread_a")
    before = service.retrieve_for_thread("注意力机制", "thread_a")
    assert before

    service.delete_attachment(attachment.id)

    assert service.repository.get(attachment.id) is None
    import pathlib

    assert not pathlib.Path(attachment.storage_path).is_file()
    snapshot = service.temp_index_snapshot()
    remaining = [
        doc
        for doc in (snapshot.documents if snapshot else ())
        if doc.metadata.get("attachment_id") == attachment.id
    ]
    assert remaining == []
    assert service.retrieve_for_thread("注意力机制", "thread_a") == []


def test_purge_thread_cleans_everything(tmp_path):
    service = _service(tmp_path)
    first = _upload_sample(service, "thread_p")
    second = service.upload(
        "thread_p",
        "notes.txt",
        "# 笔记\n\n本地向量索引说明。".encode("utf-8"),
    )

    summary = service.purge_thread("thread_p")

    assert summary["attachments_deleted"] == 2
    assert summary["storage_directory_removed"] is True
    assert service.repository.list_by_thread("thread_p") == []
    for attachment in (first, second):
        import pathlib

        assert not pathlib.Path(attachment.storage_path).is_file()
    snapshot = service.temp_index_snapshot()
    assert snapshot is None or not snapshot.documents


def _expected_document_hash(attachment) -> str:
    from src.rag.loader import load_document

    return load_document(attachment.storage_path).content_hash


def test_promote_appends_to_long_term_index_once(tmp_path):
    service = _service(tmp_path)
    attachment = _upload_sample(service, "thread_a")

    first = service.promote(attachment.id)
    second = service.promote(attachment.id)

    assert first["status"] == "promoted"
    assert second["status"] == "already_promoted"
    promoted_index = load_rag_index(tmp_path / "long_term_index.json")
    expected = _expected_document_hash(attachment)
    matching = [
        doc
        for doc in promoted_index.documents
        if doc.content_hash == expected
    ]
    assert len(matching) == 1


def test_duplicate_content_hashes_dedup_on_promotion(tmp_path):
    service = _service(tmp_path)
    original = _upload_sample(service, "thread_a")
    duplicate = service.upload(
        "thread_b", "copy.md", SAMPLE_TEXT.encode("utf-8")
    )

    result = service.promote(duplicate.id)

    assert result["status"] == "promoted"
    marked = service.repository.get(duplicate.id)
    assert marked is not None and marked.promoted_rag_run_id
    # The long-term index gains exactly one copy of the shared content,
    # even though two threads each held the same bytes.
    index = load_rag_index(tmp_path / "long_term_index.json")
    expected = _expected_document_hash(original)
    matches = [
        doc for doc in index.documents if doc.content_hash == expected
    ]
    assert len(matches) == 1


_PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000"
    "001f15c4890000000a49444154789c63000100000500010d0a2db400"
    "00000049454e44ae426082"
)


def test_image_without_describer_is_stored_not_indexed(tmp_path):
    service = _service(tmp_path)
    attachment = service.upload(
        "thread_a", "diagram.png", _PNG_BYTES, content_type="image/png"
    )

    assert attachment.status == "ready"
    parsing_entry = next(
        entry
        for entry in attachment.stage_history
        if entry["stage"] == "parsing"
    )
    assert parsing_entry["detail"] == "image_stored_without_description"
    assert service.retrieve_for_thread("diagram", "thread_a") == []


def test_image_with_describer_indexes_description(tmp_path):
    service = _service(
        tmp_path,
        describer=lambda path: "流程图：用户上传附件后系统解析并建立临时索引。",
    )
    attachment = service.upload(
        "thread_a", "diagram.png", _PNG_BYTES, content_type="image/png"
    )

    assert attachment.status == "ready"
    hits = service.retrieve_for_thread("临时索引", "thread_a")
    assert hits, "description text must be retrievable"
    snapshot = service.temp_index_snapshot()
    assert snapshot is not None
    described = [
        doc
        for doc in snapshot.documents
        if doc.metadata.get("attachment_id") == attachment.id
    ]
    assert described, "description document must carry attachment metadata"
    assert described[0].metadata.get("origin") == "session_attachment"

def test_vision_switch_off_stores_without_describing(tmp_path):
    service = _service(
        tmp_path,
        describer=lambda path: "should never be called",
        vision_enabled=lambda: False,
    )
    attachment = service.upload(
        "thread_a", "diagram.png", _PNG_BYTES, content_type="image/png"
    )

    assert attachment.status == "ready"
    refreshed = service.repository.get(attachment.id)
    assert refreshed is not None
    assert refreshed.external_calls == (), "disabled gate must not send or audit"


def test_vision_switch_on_audits_cloud_send(tmp_path):
    calls = []

    def describe(path):
        calls.append(path)
        return "流程图描述：临时索引构建过程。"

    service = _service(
        tmp_path, describer=describe, vision_enabled=lambda: True
    )
    attachment = service.upload(
        "thread_a", "diagram.png", _PNG_BYTES, content_type="image/png"
    )

    assert attachment.status == "ready"
    assert len(calls) == 1
    refreshed = service.repository.get(attachment.id)
    assert refreshed is not None
    statuses = [entry["status"] for entry in refreshed.external_calls]
    assert statuses == ["attempted", "completed"]
    first = refreshed.external_calls[0]
    assert first["purpose"] == "image_description"
    assert first["provider"] == "deepseek"
    assert first["data_categories"] == ["image_content"]


def test_vision_failure_records_audit_then_fails(tmp_path):
    def broken(_path):
        raise RuntimeError("vision api down")

    service = _service(
        tmp_path, describer=broken, vision_enabled=lambda: True
    )
    attachment = service.upload(
        "thread_a", "diagram.png", _PNG_BYTES, content_type="image/png"
    )

    # Auto-retry-once (decision 9) exhausts both attempts, then failed.
    assert attachment.status == "failed"
    refreshed = service.repository.get(attachment.id)
    assert refreshed is not None
    statuses = [entry["status"] for entry in refreshed.external_calls]
    assert statuses == ["attempted", "failed", "attempted", "failed"]

def test_chat_turn_retrieves_thread_attachments_with_priority(
    tmp_path, monkeypatch
):
    from dataclasses import dataclass
    from typing import Any

    from src.application.chat_service import ChatDependencies
    from src.application.policy_chat_service import (
        ExternalDataPolicyChatService,
        PolicyChatCommand,
    )
    from src.infrastructure.sqlite.database import RuntimeDatabase as _DB
    from src.repositories.runtime_repository import RuntimeRepository
    from src.task_contract import (
        TaskAwarePedagogyEngine,
        TaskAwarePedagogyEvaluationService,
        route_request_with_task_contract,
    )
    from src.tools.web_agent import WebToolTrace
    import src.application.runtime_repository as runtime_repo_module

    service = _service(tmp_path)
    attachment = _upload_sample(service, "thread_chat")

    class _FailingEvaluator:
        def evaluate(self, **kwargs):
            raise AssertionError("semantic evaluation must not run here")

    @dataclass
    class _LocalRag:
        enabled: bool

        def to_dict(self) -> dict[str, Any]:
            return {
                "status": "not_found" if self.enabled else "skipped",
                "query": "",
                "retrieval_mode": "hybrid",
                "reason": "test",
                "context": "",
                "sources": "",
                "result_count": 0,
                "results": [],
                "debug": {},
                "attempts": [],
                "rewritten_query": "",
            }

    repository = RuntimeRepository(_DB(tmp_path / "chat.db"))
    dependencies = ChatDependencies(
        route_request=route_request_with_task_contract,
        retrieve_local_knowledge=lambda query, **kwargs: _LocalRag(
            enabled=bool(kwargs["enabled"])
        ),
        resolve_web_tools=lambda *args, **kwargs: WebToolTrace(enabled=False),
        build_messages=lambda **kwargs: [
            {"role": "system", "content": kwargs["rag_context"]},
            {"role": "user", "content": kwargs["user_input"]},
        ],
        pedagogy_engine=TaskAwarePedagogyEngine(),
        pedagogy_evaluation=TaskAwarePedagogyEvaluationService(
            _FailingEvaluator()
        ),
        build_role_prompt=lambda role, **kwargs: "ROLE",
        stream_chat=lambda *args, **kwargs: iter(("ok",)),
    )
    monkeypatch.setattr(
        runtime_repo_module,
        "get_session_attachment_service",
        lambda: service,
    )
    chat = ExternalDataPolicyChatService(repository, dependencies)
    prepared = chat.start_turn(
        PolicyChatCommand(
            user_input="多头注意力是怎么工作的",
            thread_id="thread_chat",
            rag_enabled=True,
        )
    )

    snapshot = prepared.turn.rag_snapshot
    provenance = snapshot.get("session_attachments")
    assert provenance is not None and provenance["count"] >= 1
    assert attachment.id in provenance["attachment_ids"]
    first_chunk = snapshot["results"][0]["chunk"]
    assert first_chunk["title"] == "attention.md"
    # Attachment hits rank above long-term results (which are empty here,
    # so the attachment must simply be present and first).
    assert any("注意力" in chunk["text"] for chunk in
               [result["chunk"] for result in snapshot["results"]])


def test_other_thread_cannot_retrieve_attachment_in_chat(
    tmp_path, monkeypatch
):
    from dataclasses import dataclass
    from typing import Any

    from src.application.chat_service import ChatDependencies
    from src.application.policy_chat_service import (
        ExternalDataPolicyChatService,
        PolicyChatCommand,
    )
    from src.infrastructure.sqlite.database import RuntimeDatabase as _DB
    from src.repositories.runtime_repository import RuntimeRepository
    from src.task_contract import (
        TaskAwarePedagogyEngine,
        TaskAwarePedagogyEvaluationService,
        route_request_with_task_contract,
    )
    from src.tools.web_agent import WebToolTrace
    import src.application.runtime_repository as runtime_repo_module

    service = _service(tmp_path)
    _upload_sample(service, "thread_owner")

    class _FailingEvaluator:
        def evaluate(self, **kwargs):
            raise AssertionError("semantic evaluation must not run here")

    @dataclass
    class _LocalRag:
        enabled: bool

        def to_dict(self) -> dict[str, Any]:
            return {
                "status": "skipped", "query": "", "retrieval_mode": "hybrid",
                "reason": "test", "context": "", "sources": "",
                "result_count": 0, "results": [], "debug": {},
                "attempts": [], "rewritten_query": "",
            }

    repository = RuntimeRepository(_DB(tmp_path / "chat2.db"))
    dependencies = ChatDependencies(
        route_request=route_request_with_task_contract,
        retrieve_local_knowledge=lambda query, **kwargs: _LocalRag(
            enabled=bool(kwargs["enabled"])
        ),
        resolve_web_tools=lambda *args, **kwargs: WebToolTrace(enabled=False),
        build_messages=lambda **kwargs: [
            {"role": "system", "content": kwargs["rag_context"]},
            {"role": "user", "content": kwargs["user_input"]},
        ],
        pedagogy_engine=TaskAwarePedagogyEngine(),
        pedagogy_evaluation=TaskAwarePedagogyEvaluationService(
            _FailingEvaluator()
        ),
        build_role_prompt=lambda role, **kwargs: "ROLE",
        stream_chat=lambda *args, **kwargs: iter(("ok",)),
    )
    monkeypatch.setattr(
        runtime_repo_module,
        "get_session_attachment_service",
        lambda: service,
    )
    chat = ExternalDataPolicyChatService(repository, dependencies)
    prepared = chat.start_turn(
        PolicyChatCommand(
            user_input="多头注意力是怎么工作的",
            thread_id="thread_intruder",
            rag_enabled=True,
        )
    )

    provenance = prepared.turn.rag_snapshot.get("session_attachments")
    assert provenance is not None and provenance["status"] == "none"
    assert provenance["count"] == 0

def test_archive_success_purges_attachments_failure_keeps_them(tmp_path):
    """Gate 3: purge binds to archive SUCCESS, not the archive click."""
    from src.application.session_service import SessionService
    from src.repositories.runtime_repository import RuntimeRepository

    repository = RuntimeRepository(RuntimeDatabase(tmp_path / "arch.db"))
    service = _service(tmp_path)
    attachment = _upload_sample(service, "thread_arch")

    # Seed a turn so the thread is archivable (empty threads refuse).
    from src.domain.runtime_entities import ChatTurn

    repository.ensure_chat_thread("thread_arch")
    repository.add_chat_turn(
        ChatTurn(
            id="turn_seed",
            thread_id="thread_arch",
            user_message="hi",
            assistant_message="hello",
            status="completed",
        )
    )

    calls: list[str] = []
    session_service = SessionService(
        repository,
        current_dir=tmp_path / "current",
        archive_dir=tmp_path / "archive",
        attachment_purger=lambda session_id: (
            calls.append(session_id) or service.purge_thread(session_id)
        ),
    )
    archived = session_service.archive_session("thread_arch")

    assert archived is not None and archived.status == "archived"
    assert calls == ["thread_arch"]
    assert service.repository.get(attachment.id) is None
    import pathlib

    assert not pathlib.Path(attachment.storage_path).is_file()

    # A purger failure must NOT roll back the durable archive.
    repository2 = RuntimeRepository(RuntimeDatabase(tmp_path / "arch2.db"))
    repository2.ensure_chat_thread("thread_b")
    repository2.add_chat_turn(
        ChatTurn(
            id="turn_seed2",
            thread_id="thread_b",
            user_message="hi",
            assistant_message="hello",
            status="completed",
        )
    )

    def broken_purge(_session_id):
        raise RuntimeError("purge exploded")

    session_service2 = SessionService(
        repository2,
        current_dir=tmp_path / "current",
        archive_dir=tmp_path / "archive",
        attachment_purger=broken_purge,
    )
    archived2 = session_service2.archive_session("thread_b")
    assert archived2 is not None and archived2.status == "archived"

