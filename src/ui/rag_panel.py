from __future__ import annotations

import re
from pathlib import Path

import streamlit as st

from src.rag import (
    build_rag_context,
    build_rag_debug,
    format_rag_sources,
    get_vector_backend_from_env,
    index_documents,
    load_rag_index,
    search_documents,
)
from src.rag.index import DEFAULT_RAG_INDEX_PATH
from src.rag.schema import RagIndex

ROOT = Path(__file__).resolve().parent.parent.parent
RAG_UPLOAD_DIR = ROOT / "logs" / "rag_uploads"
UPLOAD_TYPES = ["md", "markdown", "txt", "docx", "pdf"]
RETRIEVAL_MODES = ["lexical", "hybrid", "vector", "backend_vector"]


def sanitize_upload_name(name: str) -> str:
    candidate = Path(name or "document").name
    candidate = re.sub(r"[^A-Za-z0-9._-]+", "_", candidate).strip("._")
    return candidate or "document"


def parse_path_lines(text: str) -> list[Path]:
    paths: list[Path] = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip().strip('"')
        if line:
            paths.append(Path(line).expanduser())
    return paths


def _save_uploads(uploaded_files: list) -> list[Path]:
    saved_paths: list[Path] = []
    RAG_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    for uploaded in uploaded_files:
        name = sanitize_upload_name(uploaded.name)
        target = RAG_UPLOAD_DIR / name
        target.write_bytes(uploaded.getvalue())
        saved_paths.append(target)
    return saved_paths


def _collect_document_paths(uploaded_files: list, path_text: str) -> list[Path]:
    paths = _save_uploads(uploaded_files) if uploaded_files else []
    paths.extend(parse_path_lines(path_text))
    return paths


def summarize_rag_index(index: RagIndex) -> dict:
    chunk_counts: dict[str, int] = {}
    for chunk in index.chunks:
        chunk_counts[chunk.document_hash] = chunk_counts.get(chunk.document_hash, 0) + 1

    documents = []
    for document in index.documents:
        documents.append(
            {
                "title": document.title,
                "file_type": document.file_type,
                "source_path": document.source_path,
                "size_bytes": int(document.metadata.get("size_bytes", 0)),
                "mtime_ns": int(document.metadata.get("mtime_ns", 0)),
                "content_hash": document.content_hash[:8],
                "chunk_count": chunk_counts.get(document.content_hash, 0),
            }
        )

    return {
        "documents": len(index.documents),
        "chunks": len(index.chunks),
        "document_rows": documents,
    }


def chunk_preview_rows(index: RagIndex, *, max_rows: int = 12) -> list[dict]:
    rows: list[dict] = []
    for chunk in index.chunks[:max_rows]:
        preview = " ".join(chunk.text.split())
        rows.append(
            {
                "title": chunk.title,
                "lines": f"L{chunk.start_line}-L{chunk.end_line}",
                "chars": int(chunk.metadata.get("char_count", len(chunk.text))),
                "source_path": chunk.source_path,
                "preview": preview[:180] + ("..." if len(preview) > 180 else ""),
            }
        )
    return rows


def format_rag_debug_summary(debug: dict) -> str:
    if not debug:
        return ""
    terms = ", ".join(sorted(debug.get("query_terms", []))) or "-"
    return (
        f"mode={debug.get('retrieval_mode', '-')}; "
        f"top_k={debug.get('top_k', '-')}; "
        f"min_score={debug.get('min_score', '-')}; "
        f"candidates={debug.get('candidate_count', 0)}; "
        f"returned={debug.get('returned_count', 0)}; "
        f"terms={terms}"
    )


def format_score_breakdown(result_debug: dict) -> str:
    breakdown = result_debug.get("score_breakdown", {})
    if not breakdown:
        return ""
    parts = []
    for key in [
        "fusion",
        "rrf_k",
        "lexical_rank",
        "lexical_rrf",
        "lexical_score",
        "lexical_normalized",
        "vector_rank",
        "vector_rrf",
        "vector_score",
        "combined_score",
        "backend_score",
    ]:
        if key in breakdown:
            value = breakdown[key]
            parts.append(f"{key}={value:.3f}" if isinstance(value, float) else f"{key}={value}")
    return "; ".join(parts)


def _render_result_cards(results) -> None:
    for index, result in enumerate(results, start=1):
        chunk = result.chunk
        with st.expander(
            f"[{index}] {chunk.title}  L{chunk.start_line}-L{chunk.end_line}  score={result.score:.3f}",
            expanded=index == 1,
        ):
            st.caption(chunk.source_path)
            if result.matched_terms:
                st.caption("matched: " + ", ".join(result.matched_terms))
            st.markdown(chunk.text)


def _load_current_index() -> RagIndex | None:
    try:
        return load_rag_index()
    except FileNotFoundError:
        return None


def _render_index_overview(index: RagIndex | None) -> None:
    if index is None:
        st.caption(f"当前索引：{DEFAULT_RAG_INDEX_PATH}（尚未建立）")
        return

    summary = summarize_rag_index(index)
    st.caption(
        f"当前索引：{DEFAULT_RAG_INDEX_PATH} · "
        f"{summary['documents']} documents / {summary['chunks']} chunks"
    )

    with st.expander("已索引资料", expanded=False):
        document_rows = summary["document_rows"]
        if document_rows:
            st.dataframe(document_rows, use_container_width=True, hide_index=True)
        else:
            st.caption("索引中没有文档。")

    with st.expander("Chunk 预览", expanded=False):
        rows = chunk_preview_rows(index)
        if rows:
            st.dataframe(rows, use_container_width=True, hide_index=True)
        else:
            st.caption("索引中没有 chunk。")


def _render_rag_debug(debug: dict) -> None:
    if not debug:
        return
    with st.expander("检索调试", expanded=False):
        st.caption(format_rag_debug_summary(debug))
        rows = []
        for item in debug.get("results", []):
            rows.append(
                {
                    "rank": item.get("rank"),
                    "title": item.get("title"),
                    "score": item.get("score"),
                    "matched": ", ".join(item.get("matched_terms", [])) or "-",
                    "breakdown": format_score_breakdown(item),
                    "source_path": item.get("source_path"),
                }
            )
        if rows:
            st.dataframe(rows, use_container_width=True, hide_index=True)


def _render_vector_backend_status() -> None:
    try:
        status = get_vector_backend_from_env().status()
    except ValueError as exc:
        st.caption(f"Vector backend: unavailable ({exc})")
        return
    availability = "available" if status.available else "unavailable"
    detail = f" · {status.detail}" if status.detail else ""
    location = f" · {status.path}/{status.collection}" if status.path or status.collection else ""
    st.caption(
        f"Vector backend: {status.name} / {status.embedding_provider} "
        f"({availability}){location}{detail}"
    )


def render_rag_panel() -> None:
    with st.expander("本地资料检索", expanded=False):
        current_index = _load_current_index()
        _render_index_overview(current_index)
        _render_vector_backend_status()

        uploaded_files = st.file_uploader(
            "上传资料",
            type=UPLOAD_TYPES,
            accept_multiple_files=True,
            key="rag_uploads",
        )
        path_text = st.text_area(
            "本地文件路径",
            value=st.session_state.get("rag_path_text", ""),
            height=88,
            key="rag_path_text",
        )

        build_cols = st.columns([1, 1, 2])
        with build_cols[0]:
            build_clicked = st.button("建立索引", key="rag_build_index", use_container_width=True)
        with build_cols[1]:
            clear_clicked = st.button("清空结果", key="rag_clear_results", use_container_width=True)

        if clear_clicked:
            st.session_state.rag_results = []
            st.session_state.rag_context = ""
            st.session_state.rag_source_block = ""
            st.session_state.rag_index_summary = ""
            st.session_state.rag_debug = {}

        if build_clicked:
            paths = _collect_document_paths(uploaded_files or [], path_text)
            if not paths:
                st.warning("没有可索引的资料。")
            else:
                try:
                    with st.spinner("正在建立索引..."):
                        index = index_documents(paths)
                    st.session_state.rag_index_summary = (
                        f"{len(index.documents)} documents / {len(index.chunks)} chunks"
                    )
                    st.session_state.rag_debug = {}
                    current_index = index
                    st.success("索引已更新。")
                except Exception as exc:
                    st.warning(f"索引失败：{exc}")

        if st.session_state.get("rag_index_summary"):
            st.caption(st.session_state.rag_index_summary)

        chat_cols = st.columns([2, 1])
        with chat_cols[0]:
            st.checkbox(
                "用于聊天回答",
                value=st.session_state.get("rag_chat_enabled", False),
                key="rag_chat_enabled",
            )
        with chat_cols[1]:
            st.number_input(
                "聊天引用数",
                min_value=1,
                max_value=6,
                value=int(st.session_state.get("rag_chat_top_k", 3)),
                step=1,
                key="rag_chat_top_k",
            )

        st.selectbox(
            "检索模式",
            options=RETRIEVAL_MODES,
            format_func=lambda value: {
                "lexical": "关键词",
                "hybrid": "混合",
                "vector": "本地向量",
                "backend_vector": "向量后端",
            }.get(value, value),
            index=RETRIEVAL_MODES.index(
                st.session_state.get("rag_retrieval_mode", "hybrid")
            )
            if st.session_state.get("rag_retrieval_mode", "hybrid") in set(RETRIEVAL_MODES)
            else 1,
            key="rag_retrieval_mode",
        )

        query_cols = st.columns([3, 1])
        with query_cols[0]:
            query = st.text_input("检索问题", key="rag_query")
        with query_cols[1]:
            top_k = st.number_input("条数", min_value=1, max_value=8, value=3, step=1, key="rag_top_k")

        min_score = st.number_input(
            "最低分",
            min_value=0.0,
            max_value=10.0,
            value=float(st.session_state.get("rag_min_score", 0.01)),
            step=0.01,
            key="rag_min_score",
        )
        st.checkbox(
            "显示调试",
            value=st.session_state.get("rag_debug_enabled", True),
            key="rag_debug_enabled",
        )

        if st.button("检索", key="rag_search", use_container_width=True):
            if not query.strip():
                st.warning("先输入检索问题。")
            else:
                try:
                    index = load_rag_index()
                    retrieval_mode = st.session_state.get("rag_retrieval_mode", "hybrid")
                    results = search_documents(
                        index,
                        query,
                        top_k=int(top_k),
                        min_score=float(min_score),
                        retrieval_mode=retrieval_mode,
                    )
                    debug = build_rag_debug(
                        index,
                        query,
                        results,
                        retrieval_mode=retrieval_mode,
                        top_k=int(top_k),
                        min_score=float(min_score),
                    )
                    st.session_state.rag_results = results
                    st.session_state.rag_context = build_rag_context(results)
                    st.session_state.rag_source_block = format_rag_sources(results)
                    st.session_state.rag_debug = debug
                except FileNotFoundError:
                    st.warning("先建立索引。")
                except Exception as exc:
                    st.warning(f"检索失败：{exc}")

        results = st.session_state.get("rag_results", [])
        if results:
            _render_result_cards(results)
            with st.expander("来源列表", expanded=False):
                st.code(st.session_state.get("rag_source_block", ""), language="text")
            with st.expander("引用上下文", expanded=False):
                st.code(st.session_state.get("rag_context", ""), language="text")
            if st.session_state.get("rag_debug_enabled", True):
                _render_rag_debug(st.session_state.get("rag_debug", {}))
