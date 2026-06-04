from __future__ import annotations

import re
from pathlib import Path

import streamlit as st

from src.rag import build_rag_context, format_rag_sources, index_documents, query_documents

ROOT = Path(__file__).resolve().parent.parent.parent
RAG_UPLOAD_DIR = ROOT / "logs" / "rag_uploads"
UPLOAD_TYPES = ["md", "markdown", "txt", "docx", "pdf"]


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


def render_rag_panel() -> None:
    with st.expander("本地资料检索", expanded=False):
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
            options=["lexical", "hybrid", "vector"],
            format_func=lambda value: {
                "lexical": "关键词",
                "hybrid": "混合",
                "vector": "本地向量",
            }.get(value, value),
            index=["lexical", "hybrid", "vector"].index(
                st.session_state.get("rag_retrieval_mode", "hybrid")
            )
            if st.session_state.get("rag_retrieval_mode", "hybrid")
            in {"lexical", "hybrid", "vector"}
            else 1,
            key="rag_retrieval_mode",
        )

        query_cols = st.columns([3, 1])
        with query_cols[0]:
            query = st.text_input("检索问题", key="rag_query")
        with query_cols[1]:
            top_k = st.number_input("条数", min_value=1, max_value=8, value=3, step=1, key="rag_top_k")

        if st.button("检索", key="rag_search", use_container_width=True):
            if not query.strip():
                st.warning("先输入检索问题。")
            else:
                try:
                    results = query_documents(
                        query,
                        top_k=int(top_k),
                        retrieval_mode=st.session_state.get("rag_retrieval_mode", "hybrid"),
                    )
                    st.session_state.rag_results = results
                    st.session_state.rag_context = build_rag_context(results)
                    st.session_state.rag_source_block = format_rag_sources(results)
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
