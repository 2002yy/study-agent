"""Read-only windows of full parsed text, with no evidence write authority."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from src.rag.index import load_rag_index
from src.rag.schema import RagDocument

MAX_WINDOW_LINES = 200
MAX_WINDOW_BYTES = 64 * 1024
READABLE_TYPES = frozenset({"md", "markdown", "txt", "pdf", "docx"})


class ReadingUnavailable(ValueError):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code


class DocumentReadingResponse(BaseModel):
    model_config = {"extra": "forbid"}

    schema_version: Literal["document-reading-v1"] = "document-reading-v1"
    representation: Literal["indexed_text", "saved_web_text"] = "indexed_text"
    scope: Literal["knowledge", "session", "web"]
    document_id: str
    revision_id: str
    content_hash: str
    parser_version: str
    title: str
    source_path: str
    file_type: str
    evidence_status: str
    start_line: int
    end_line: int
    total_lines: int
    text: str
    pdf_pages: int = 0
    pdf_page_map: list[dict[str, int]] = Field(default_factory=list)
    content_truncated: bool = False


def indexed_documents(path: Path) -> tuple[RagDocument, ...]:
    try:
        return load_rag_index(path).documents
    except FileNotFoundError as exc:
        raise ReadingUnavailable(404, "资料正文不存在或已删除") from exc


def document_window(
    document: RagDocument,
    *,
    scope: Literal["knowledge", "session", "web"],
    start_line: int = 1,
    limit: int = 100,
    expected_revision: str = "",
) -> DocumentReadingResponse:
    revision = document.revision_id or document.content_hash
    if expected_revision and expected_revision != revision:
        raise ReadingUnavailable(409, "资料版本已变化，请重新打开资料")
    if (
        scope != "web" and document.file_type not in READABLE_TYPES
    ) or not document.text:
        raise ReadingUnavailable(409, "此资料暂无可阅读的解析正文")
    lines = document.text.splitlines()
    if start_line < 1 or start_line > len(lines) or not 1 <= limit <= MAX_WINDOW_LINES:
        raise ReadingUnavailable(422, "正文行号或阅读窗口超出范围")
    end_line = min(start_line + limit - 1, len(lines))
    text = "\n".join(lines[start_line - 1 : end_line])
    if len(text.encode("utf-8")) > MAX_WINDOW_BYTES:
        raise ReadingUnavailable(413, "此段正文过长，请缩小阅读窗口")
    page_count = (
        int(document.metadata.get("pdf_pages") or 0)
        if document.file_type == "pdf"
        else 0
    )
    page_map: list[dict[str, int]] = []
    if page_count:
        # Only loader-authored offsets authorize page navigation. Literal page
        # labels inside a PDF cannot impersonate its page structure.
        for item in document.metadata.get("pdf_page_map", []):
            if not isinstance(item, dict):
                page_map = []
                break
            page, line = item.get("page"), item.get("line")
            if (
                type(page) is not int
                or type(line) is not int
                or not 1 <= page <= page_count
                or not 1 <= line <= len(lines)
                or (
                    page_map
                    and (page <= page_map[-1]["page"] or line <= page_map[-1]["line"])
                )
            ):
                page_map = []
                break
            page_map.append({"page": page, "line": line})
    return DocumentReadingResponse(
        scope=scope,
        document_id=document.document_id or document.content_hash,
        revision_id=revision,
        content_hash=document.content_hash,
        parser_version=document.parser_version,
        title=document.title,
        source_path=document.source_path,
        file_type=document.file_type,
        evidence_status=document.evidence_status,
        start_line=start_line,
        end_line=end_line,
        total_lines=len(lines),
        text=text,
        representation="saved_web_text" if scope == "web" else "indexed_text",
        pdf_pages=page_count,
        pdf_page_map=page_map,
        content_truncated=bool(document.metadata.get("content_truncated")),
    )


def read_knowledge_document(
    path: Path,
    document_id: str,
    *,
    start_line: int = 1,
    limit: int = 100,
    expected_revision: str = "",
) -> DocumentReadingResponse:
    for document in indexed_documents(path):
        if (document.document_id or document.content_hash) == document_id:
            return document_window(
                document,
                scope="knowledge",
                start_line=start_line,
                limit=limit,
                expected_revision=expected_revision,
            )
    raise ReadingUnavailable(404, "资料正文不存在或已删除")


def read_session_document(
    service,
    thread_id: str,
    attachment_id: str,
    *,
    start_line: int = 1,
    limit: int = 100,
    expected_revision: str = "",
) -> DocumentReadingResponse:
    attachment = service.repository.get(attachment_id)
    if attachment is None or attachment.thread_id != thread_id:
        raise ReadingUnavailable(404, "当前会话没有此附件")
    if attachment.status != "ready":
        raise ReadingUnavailable(409, "附件尚未完成解析，请稍后重试")
    for document in indexed_documents(service.temp_index_path):
        if (
            document.metadata.get("thread_id") == thread_id
            and document.metadata.get("attachment_id") == attachment_id
        ):
            return document_window(
                document,
                scope="session",
                start_line=start_line,
                limit=limit,
                expected_revision=expected_revision,
            )
    raise ReadingUnavailable(404, "附件解析正文不存在或已删除")
