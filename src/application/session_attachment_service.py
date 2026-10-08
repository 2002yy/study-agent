"""G14 temporary session attachment lifecycle service.

Contract: PROJECT_STATUS section 12. Attachments live with their thread,
are physically isolated from the long-term RAG index (shared temp index
with hard thread_id filtering), and are purged only after archive/delete
success. Only `ready` files contribute chunks to retrieval; failed files
never leak fragments into question context.
"""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from src.domain.runtime_entities import (
    SESSION_ATTACHMENT_EXTENSIONS,
    SessionAttachment,
    utc_now,
)
from src.rag.chunker import chunk_document
from src.rag.index import load_rag_index
from src.rag.loader import load_document
from src.rag.schema import RagChunk, RagDocument, RagIndex, RagSearchResult
from src.rag.service import (
    attach_document_to_index_with_stages,
    remove_documents_from_index,
    search_documents_with_debug,
)
from src.repositories.session_attachment_repository import (
    SessionAttachmentRepository,
)

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_ATTACHMENT_ROOT = ROOT / "logs" / "runtime" / "attachments"
DEFAULT_TEMP_INDEX_PATH = ROOT / "logs" / "runtime" / "temp_attachments_index.json"

MAX_FILES_PER_THREAD = 10
MAX_FILE_BYTES = 20 * 1024 * 1024
TEXT_EXTENSIONS = frozenset({".md", ".markdown", ".txt", ".pdf", ".docx"})
IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".gif", ".webp"})

PIPELINE_STATUSES = frozenset({"parsing", "chunking", "indexing"})


def _vision_model_name() -> str:
    from src.application.attachment_vision import vision_model_name

    return vision_model_name()


class AttachmentLimitError(ValueError):
    """Raised when thread count/size limits are exceeded."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _stage_entry(
    stage: str, status: str, **details: Any
) -> dict[str, Any]:
    entry: dict[str, Any] = {"stage": stage, "status": status, "at": utc_now()}
    entry.update(details)
    return entry


class SessionAttachmentService:
    def __init__(
        self,
        repository: SessionAttachmentRepository,
        *,
        attachment_root: Path | str = DEFAULT_ATTACHMENT_ROOT,
        temp_index_path: Path | str = DEFAULT_TEMP_INDEX_PATH,
        vision_describer: Callable[[Path], str] | None = None,
        vision_enabled: Callable[[], bool] | None = None,
        long_term_index_path: Path | str | None = None,
        max_chars: int = 900,
        overlap_chars: int = 120,
    ):
        self.repository = repository
        self.attachment_root = Path(attachment_root)
        self.temp_index_path = Path(temp_index_path)
        self.vision_describer = vision_describer
        # G14 gate 6: the independent vision switch is evaluated at upload
        # time so toggling the setting takes effect without a restart.
        self.vision_enabled = vision_enabled
        # Resolved lazily so production callers always follow the live
        # DEFAULT_RAG_INDEX_PATH while tests can inject a temporary path.
        self.long_term_index_path = (
            Path(long_term_index_path) if long_term_index_path else None
        )
        self.max_chars = max_chars
        self.overlap_chars = overlap_chars

    def _vision_active(self) -> bool:
        if self.vision_describer is None:
            return False
        if self.vision_enabled is not None and not self.vision_enabled():
            return False
        return True

    # ------------------------------------------------------------------
    # Upload + per-file pipeline

    def upload(
        self,
        thread_id: str,
        filename: str,
        data: bytes,
        *,
        content_type: str = "",
    ) -> SessionAttachment:
        if not thread_id:
            raise ValueError("thread_id is required")
        safe_name = Path(filename or "").name
        suffix = Path(safe_name).suffix.lower()
        if not safe_name or suffix not in SESSION_ATTACHMENT_EXTENSIONS:
            raise ValueError(f"Unsupported attachment type: {suffix or '<none>'}")
        if len(data) <= 0:
            raise ValueError(f"Attachment is empty: {safe_name}")
        if len(data) > MAX_FILE_BYTES:
            raise ValueError(
                f"Attachment is too large: {safe_name}"
                f" ({len(data)} > {MAX_FILE_BYTES})"
            )
        existing_count = self.repository.count_by_thread(thread_id)
        if existing_count >= MAX_FILES_PER_THREAD:
            raise AttachmentLimitError(
                f"Thread already has {existing_count} attachments"
                f" (limit {MAX_FILES_PER_THREAD})"
            )

        content_hash = sha256_bytes(data)
        target_dir = self.attachment_root / thread_id
        target_dir.mkdir(parents=True, exist_ok=True)
        storage_path = target_dir / f"{content_hash[:24]}_{safe_name}"
        storage_path.write_bytes(data)

        attachment = self.repository.create(
            SessionAttachment(
                thread_id=thread_id,
                filename=safe_name,
                content_hash=content_hash,
                mime_type=content_type,
                size_bytes=len(data),
                storage_path=str(storage_path),
                status="parsing",
                stage_history=(
                    _stage_entry("upload", "completed", bytes=len(data)),
                ),
            )
        )
        return self._process(attachment)

    def retry(self, attachment_id: str) -> SessionAttachment:
        current = self.repository.get(attachment_id)
        if current is None:
            raise ValueError(f"Session attachment not found: {attachment_id}")
        if current.status != "failed":
            raise ValueError(
                f"Only failed attachments can be retried: {current.status}"
            )
        reset = self.repository.transition_status(
            attachment_id,
            expected_statuses=frozenset({"failed"}),
            new_status="parsing",
            stage_entry=_stage_entry(
                "retry", "completed", attempt=current.retry_count + 1
            ),
            stage_error="",
        )
        return self._process(self._bump_retry(reset))

    # Auto-retry-once semantics from G14 decision 9: a first pipeline failure
    # re-runs once; a second failure lands the file in `failed` where manual
    # retry remains available and no fragments ever reach retrieval.
    def _process(self, attachment: SessionAttachment) -> SessionAttachment:
        try:
            return self._run_pipeline(attachment)
        except Exception as exc:
            error_text = str(exc)[:500]
            if attachment.retry_count == 0:
                marked = self.repository.transition_status(
                    attachment.id,
                    expected_statuses=PIPELINE_STATUSES | {"parsing"},
                    new_status="parsing",
                    stage_entry=_stage_entry(
                        "auto_retry", "completed", reason=error_text
                    ),
                )
                bumped = self._bump_retry(marked)
                return self._process(bumped)
            return self.repository.transition_status(
                attachment.id,
                expected_statuses=PIPELINE_STATUSES | {"failed"},
                new_status="failed",
                stage_entry=_stage_entry("pipeline", "failed", error=error_text),
                stage_error=error_text,
            )

    def _bump_retry(self, attachment: SessionAttachment) -> SessionAttachment:
        now = utc_now()
        with self.repository.database.connect() as connection:
            connection.execute(
                """
                UPDATE session_attachments
                SET retry_count = retry_count + 1, updated_at = ?,
                    version = version + 1
                WHERE id = ?
                """,
                (now, attachment.id),
            )
        refreshed = self.repository.get(attachment.id)
        if refreshed is None:
            raise ValueError(f"Session attachment not found: {attachment.id}")
        return refreshed

    def _run_pipeline(self, attachment: SessionAttachment) -> SessionAttachment:
        source = Path(attachment.storage_path)
        if not source.is_file():
            raise FileNotFoundError(attachment.storage_path)
        suffix = source.suffix.lower()

        if suffix in TEXT_EXTENSIONS:
            attachment = self.repository.transition_status(
                attachment.id,
                expected_statuses=frozenset({"parsing"}),
                new_status="chunking",
                stage_entry=_stage_entry("parsing", "completed"),
            )
            document = load_document(source)
            # Storage names carry a hash prefix for on-disk uniqueness;
            # evidence and citations must show the user-facing filename.
            document = replace(document, title=attachment.filename)
            chunks = chunk_document(
                document,
                max_chars=self.max_chars,
                overlap_chars=self.overlap_chars,
            )
            attachment = self.repository.transition_status(
                attachment.id,
                expected_statuses=frozenset({"chunking"}),
                new_status="indexing",
                stage_entry=_stage_entry("chunking", "completed"),
            )
        elif suffix in IMAGE_EXTENSIONS:
            document, chunks = self._describe_image(attachment, source)
            attachment = self.repository.transition_status(
                attachment.id,
                expected_statuses=frozenset({"parsing"}),
                new_status="indexing",
                stage_entry=_stage_entry(
                    "parsing",
                    "completed",
                    detail=(
                        "image_described"
                        if chunks
                        else "image_stored_without_description"
                    ),
                ),
            )
        else:
            raise ValueError(f"Unsupported attachment type: {suffix}")

        enriched = replace(
            document,
            metadata={
                **document.metadata,
                "thread_id": attachment.thread_id,
                "attachment_id": attachment.id,
                "origin": "session_attachment",
            },
        )
        write_result = attach_document_to_index_with_stages(
            enriched,
            chunks,
            index_path=self.temp_index_path,
        )
        vector_stage = next(
            (
                stage
                for stage in write_result.stages
                if stage.get("name") == "vector"
            ),
            {},
        )
        return self.repository.transition_status(
            attachment.id,
            expected_statuses=frozenset({"indexing"}),
            new_status="ready",
            stage_entry=_stage_entry(
                "indexing",
                "completed",
                chunks=len(chunks),
                vector_status=str(vector_stage.get("status", "unknown")),
                retrievable=bool(chunks),
                # Document-level (normalized-text) hash; promotion dedup
                # compares against long-term documents using this value.
                indexed_content_hash=document.content_hash,
            ),
        )

    def _describe_image(
        self, attachment: SessionAttachment, source: Path
    ) -> tuple[RagDocument, list[RagChunk]]:
        """Images index their description only when the switch allows it."""
        if not self._vision_active():
            stored = RagDocument(
                source_path=str(source),
                title=attachment.filename,
                text="",
                content_hash=attachment.content_hash,
                file_type=source.suffix.lower().lstrip("."),
                document_id=f"att_{attachment.id}",
            )
            return stored, []
        # Gate 6: every cloud send is audited on the attachment record.
        self.repository.record_external_call(
            attachment.id,
            {
                "purpose": "image_description",
                "provider": "deepseek",
                "model": _vision_model_name(),
                "data_categories": ["image_content"],
                "status": "attempted",
                "at": utc_now(),
            },
        )
        try:
            description = self.vision_describer(source).strip()  # type: ignore[misc]
        except Exception as exc:
            self.repository.record_external_call(
                attachment.id,
                {
                    "purpose": "image_description",
                    "provider": "deepseek",
                    "status": "failed",
                    "detail": str(exc)[:300],
                    "at": utc_now(),
                },
            )
            raise
        if not description:
            raise ValueError("vision describer returned an empty description")
        self.repository.record_external_call(
            attachment.id,
            {
                "purpose": "image_description",
                "provider": "deepseek",
                "status": "completed",
                "at": utc_now(),
            },
        )
        described = RagDocument(
            source_path=str(source),
            title=attachment.filename,
            text=description,
            content_hash=sha256_bytes(description.encode("utf-8")),
            file_type=f"{source.suffix.lower().lstrip('.')}_description",
            document_id=f"att_{attachment.id}",
        )
        chunk = RagChunk(
            chunk_id=f"attdesc_{attachment.content_hash[:20]}",
            document_hash=described.content_hash,
            source_path=str(source),
            title=attachment.filename,
            text=description,
            chunk_index=0,
            start_line=1,
            end_line=1,
            document_id=described.document_id,
        )
        return described, [chunk]

    # ------------------------------------------------------------------
    # Retrieval / deletion / promotion / purge

    def retrieve_for_thread(
        self,
        query: str,
        thread_id: str,
        *,
        top_k: int = 3,
        min_score: float = 0.01,
        retrieval_mode: str = "hybrid",
        should_cancel: Any = None,
    ) -> list[RagSearchResult]:
        """Search ready attachment chunks scoped to one thread.

        The thread_id filter is enforced via index metadata on every chunk;
        other threads' attachments can never surface here.
        """
        if should_cancel is not None and should_cancel():
            from src.rag.cancellation import RetrievalCancelled

            raise RetrievalCancelled(stage="attachment_retrieval")
        try:
            index = load_rag_index(self.temp_index_path)
        except FileNotFoundError:
            return []
        if should_cancel is not None and should_cancel():
            from src.rag.cancellation import RetrievalCancelled

            raise RetrievalCancelled(stage="attachment_search")
        diagnostics = search_documents_with_debug(
            index,
            query,
            top_k=top_k,
            min_score=min_score,
            retrieval_mode=retrieval_mode,
            metadata_filters={"thread_id": thread_id},
            suppress_duplicate_text=True,
        )
        # Older indexes put ownership only on documents. Bind citation metadata
        # at this boundary without changing chunk identities or search scores.
        results = []
        for hit in diagnostics.results:
            owners = [
                doc for doc in index.documents
                if (
                    (doc.document_id or doc.content_hash)
                    == (hit.chunk.document_id or hit.chunk.document_hash)
                    and doc.content_hash == hit.chunk.document_hash
                    and doc.revision_id == hit.chunk.revision_id
                    and doc.source_path == hit.chunk.source_path
                    and doc.metadata.get("thread_id") == thread_id
                )
            ]
            if len(owners) != 1:
                continue
            attachment_id = owners[0].metadata.get("attachment_id")
            attachment = self.repository.get(str(attachment_id or ""))
            if (
                not attachment
                or attachment.thread_id != thread_id
                or attachment.status != "ready"
            ):
                continue
            results.append(replace(
                hit,
                chunk=replace(hit.chunk, metadata={
                    **hit.chunk.metadata,
                    "attachment_id": attachment.id,
                    "thread_id": thread_id,
                    "origin": "session_attachment",
                }),
            ))
        return results

    def attachment_ids_in_results(
        self, results: list[RagSearchResult]
    ) -> list[str]:
        """Resolve which attachments produced the given hits.

        Chunk-level metadata does not carry the attachment tag (it lives on
        the document), so map each hit back through the temp index.
        """
        try:
            index = load_rag_index(self.temp_index_path)
        except FileNotFoundError:
            return []
        metadata_by_document = {
            document.document_id or document.content_hash: (
                document.metadata or {}
            )
            for document in index.documents
        }
        ids: list[str] = []
        for hit in results:
            document_metadata = metadata_by_document.get(
                hit.chunk.document_id or hit.chunk.document_hash
            ) or {}
            attachment_id = document_metadata.get("attachment_id")
            if attachment_id and str(attachment_id) not in ids:
                ids.append(str(attachment_id))
        return ids

    def _document_ids_for(
        self,
        *,
        attachment_id: str | None = None,
        thread_id: str | None = None,
    ) -> list[str]:
        try:
            index = load_rag_index(self.temp_index_path)
        except FileNotFoundError:
            return []

        def matches(document: RagDocument) -> bool:
            metadata = document.metadata or {}
            if attachment_id is not None:
                return metadata.get("attachment_id") == attachment_id
            return metadata.get("thread_id") == thread_id

        return [
            document.document_id or document.content_hash
            for document in index.documents
            if matches(document)
        ]

    def delete_attachment(self, attachment_id: str) -> None:
        attachment = self.repository.get(attachment_id)
        if attachment is None:
            raise ValueError(f"Session attachment not found: {attachment_id}")
        remove_documents_from_index(
            self._document_ids_for(attachment_id=attachment.id),
            index_path=self.temp_index_path,
        )
        storage = Path(attachment.storage_path)
        if storage.is_file():
            storage.unlink()
        self.repository.delete(attachment.id)

    def purge_thread(self, thread_id: str) -> dict[str, Any]:
        """Remove every attachment record, file, and index chunk for a thread.

        Called only after archive/delete success per G14 acceptance gate 3.
        """
        removed_documents = len(
            self._document_ids_for(thread_id=thread_id)
        )
        if removed_documents:
            remove_documents_from_index(
                self._document_ids_for(thread_id=thread_id),
                index_path=self.temp_index_path,
            )
        thread_dir = self.attachment_root / thread_id
        directory_removed = False
        if thread_dir.is_dir():
            shutil.rmtree(thread_dir, ignore_errors=True)
            directory_removed = True
        deleted_rows = self.repository.delete_by_thread(thread_id)
        return {
            "thread_id": thread_id,
            "attachments_deleted": deleted_rows,
            "index_documents_removed": removed_documents,
            "storage_directory_removed": directory_removed,
        }

    def promote(self, attachment_id: str) -> dict[str, Any]:
        """One-click promotion into the long-term knowledge base.

        Idempotent by content hash against the long-term index (G14 gate 5):
        promoting an already-promoted identical file does not create a second
        long-term document. The temporary copy always stays until thread end
        (copy mode).
        """
        from src.rag.service import append_documents_to_index_with_stages

        attachment = self.repository.get(attachment_id)
        if attachment is None:
            raise ValueError(f"Session attachment not found: {attachment_id}")
        if attachment.status != "ready":
            raise ValueError(
                f"Only ready attachments can be promoted: {attachment.status}"
            )
        if attachment.promoted_rag_run_id:
            return {
                "status": "already_promoted",
                "attachment_id": attachment.id,
                "rag_run_id": attachment.promoted_rag_run_id,
            }
        duplicate = self._find_long_term_duplicate(
            self._indexed_content_hash(attachment), self._long_term_index()
        )
        if duplicate is not None:
            marked = self.repository.mark_promoted(
                attachment.id, f"duplicate_of:{duplicate}"
            )
            return {
                "status": "duplicate_promoted",
                "attachment_id": marked.id,
                "long_term_document_id": duplicate,
                "promoted_rag_run_id": marked.promoted_rag_run_id,
            }
        result = append_documents_to_index_with_stages(
            [attachment.storage_path],
            index_path=self._long_term_index(),
        )
        run_marker = (
            f"index_version:{result.active_version}"
            if result.activated
            else "not_activated"
        )
        marked = self.repository.mark_promoted(attachment.id, run_marker)
        return {
            "status": "promoted" if result.activated else "activation_failed",
            "attachment_id": marked.id,
            "promoted_rag_run_id": marked.promoted_rag_run_id,
            "stages": list(result.stages),
        }

    def _long_term_index(self) -> Path:
        if self.long_term_index_path is not None:
            return self.long_term_index_path
        from src.rag.index import DEFAULT_RAG_INDEX_PATH

        return Path(DEFAULT_RAG_INDEX_PATH)

    @staticmethod
    def _indexed_content_hash(
        attachment: SessionAttachment,
    ) -> str | None:
        """Document-level hash recorded when the file was indexed."""
        for entry in reversed(attachment.stage_history):
            if entry.get("stage") == "indexing":
                value = entry.get("indexed_content_hash")
                if isinstance(value, str) and value:
                    return value
                return None
        return None

    @staticmethod
    def _find_long_term_duplicate(
        content_hash: str | None, long_term_index: Path
    ) -> str | None:
        if not content_hash:
            return None
        try:
            index = load_rag_index(long_term_index)
        except (FileNotFoundError, ValueError):
            return None
        for document in index.documents:
            if document.content_hash == content_hash:
                return document.document_id or document.content_hash
        return None

    def temp_index_snapshot(self) -> RagIndex | None:
        try:
            return load_rag_index(self.temp_index_path)
        except FileNotFoundError:
            return None
