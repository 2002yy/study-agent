"""Original PDF bytes and already-saved web reads; never fetch or mutate."""

from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader

from src.application.document_reading import (
    ReadingUnavailable,
    document_window,
    indexed_documents,
)
from src.rag.loader import (
    DEFAULT_MAX_PDF_BYTES,
    DEFAULT_MAX_PDF_PAGES,
    DEFAULT_MAX_PDF_CHARS,
    _normalize_text,
)
from src.rag.schema import RagDocument


def knowledge_original(path, document_id, expected_revision):
    matches = [
        doc
        for doc in indexed_documents(path)
        if (doc.document_id or doc.content_hash) == document_id
    ]
    if len(matches) != 1:
        raise ReadingUnavailable(404, "资料原件不存在或已删除")
    return validated_pdf(matches[0], expected_revision)


def session_original(service, thread_id, attachment_id, expected_revision):
    attachment = service.repository.get(attachment_id)
    if not attachment or attachment.thread_id != thread_id:
        raise ReadingUnavailable(404, "当前会话没有此附件")
    if attachment.status != "ready":
        raise ReadingUnavailable(409, "附件尚未完成解析")
    matches = [
        doc
        for doc in indexed_documents(service.temp_index_path)
        if (
            doc.metadata.get("thread_id") == thread_id
            and doc.metadata.get("attachment_id") == attachment_id
            and Path(doc.source_path).resolve()
            == Path(attachment.storage_path).resolve()
        )
    ]
    if len(matches) != 1:
        raise ReadingUnavailable(404, "附件原件不存在或已删除")
    return validated_pdf(matches[0], expected_revision, attachment.content_hash)


def validated_pdf(document, expected_revision, binary_hash=""):
    if not expected_revision or expected_revision != (
        document.revision_id or document.content_hash
    ):
        raise ReadingUnavailable(409, "资料版本已变化，请重新打开资料")
    if document.file_type != "pdf":
        raise ReadingUnavailable(409, "此资料不是 PDF 原件")
    try:
        with Path(document.source_path).open("rb") as source:
            data = source.read(DEFAULT_MAX_PDF_BYTES + 1)
    except OSError as exc:
        raise ReadingUnavailable(404, "PDF 原件不存在，可继续阅读解析文字") from exc
    if len(data) > DEFAULT_MAX_PDF_BYTES:
        raise ReadingUnavailable(413, "PDF 原件过大")
    binary_hash = binary_hash or document.metadata.get("source_sha256", "")
    if binary_hash and sha256(data).hexdigest() != binary_hash:
        raise ReadingUnavailable(409, "PDF 原件已变化，请重新上传")
    # Legacy knowledge indexes store a parsed-text digest, not a binary digest.
    # Parse these exact bytes so replaced files cannot display unrelated text.
    try:
        pdf = PdfReader(BytesIO(data))
        if pdf.is_encrypted or len(pdf.pages) > DEFAULT_MAX_PDF_PAGES:
            raise ValueError("unsupported PDF")
        parts = []
        for number, page in enumerate(pdf.pages, 1):
            text = page.extract_text() or ""
            if text.strip():
                parts.append(f"[Page {number}]\n{text.strip()}")
            if sum(len(part) for part in parts) > DEFAULT_MAX_PDF_CHARS:
                raise ValueError("PDF text exceeds limit")
        if _normalize_text("\n\n".join(parts)) != document.text:
            raise ValueError("changed PDF")
    except Exception as exc:
        raise ReadingUnavailable(409, "PDF 原件与已索引版本不一致，请重新上传") from exc
    return data


def saved_web_document(service, thread_id, run_id, url):
    try:
        run = service.get(run_id)
    except ValueError as exc:
        raise ReadingUnavailable(404, "网页阅读记录不存在或已删除") from exc
    if not run or not thread_id or run.owner_thread_id != thread_id:
        raise ReadingUnavailable(404, "当前会话没有此网页阅读记录")
    sources = []
    for record in run.selected_sources:
        if not isinstance(record, dict):
            continue
        item, read = record.get("item", {}), record.get("read", {})
        if isinstance(item, dict) and isinstance(read, dict) and item.get("url") == url:
            sources.append((item.get("title") or url, read))
    trace = run.research_context.get("tool_trace") or {}
    for call in trace.get("evidence_calls", []) if isinstance(trace, dict) else []:
        if not isinstance(call, dict) or call.get("name") != "web_read":
            continue
        args, read = call.get("arguments") or {}, call.get("result") or {}
        if (
            isinstance(args, dict)
            and isinstance(read, dict)
            and (read.get("url") or args.get("url")) == url
        ):
            sources.append((read.get("title") or url, read))
    valid = [
        (title, read)
        for title, read in sources
        if (
            read.get("ok") in (True, "true")
            and isinstance(read.get("content"), str)
            and read["content"].strip()
        )
    ]
    if not valid or len({read["content"] for _, read in valid}) != 1:
        raise ReadingUnavailable(409, "此来源没有唯一已保存的网页正文，请打开原网站")
    title, read = valid[0]
    content = read["content"]
    return RagDocument(
        source_path=url,
        title=str(title),
        text=content,
        content_hash=sha256(content.encode()).hexdigest(),
        file_type="web",
        document_id=f"{run.id}:{sha256(url.encode()).hexdigest()[:24]}",
        revision_id=f"{run.id}:{run.version}",
        parser_version="saved_web_read",
        metadata={
            "content_truncated": any(
                bool(result.get("content_truncated")) for _, result in valid
            )
        },
    )


def read_saved_web(service, thread_id, run_id, url, **window):
    return document_window(
        saved_web_document(service, thread_id, run_id, url), scope="web", **window
    )
