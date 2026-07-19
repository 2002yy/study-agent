from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from src.rag import build_rag_context, format_rag_sources
from src.rag.index import DEFAULT_RAG_INDEX_PATH, load_rag_index
from src.rag.schema import RagSearchResult
from src.rag.service import retrievable_rag_index, search_documents_with_debug
from src.rag.sufficiency import assess_evidence_sufficiency

LocalKnowledgeStatus = Literal[
    "skipped",
    "found",
    "uncertain",
    "insufficient",
    "not_found",
    "index_missing",
    "error",
]

_SKIP_PATTERNS = (
    r"^\s*(hi|hello|hey|thanks|thank you|你好|您好|谢谢|早上好|晚上好)[!！。.[\s]*$",
    r"(讲个笑话|随便聊|你是谁|自我介绍|打招呼)",
)

_RETRIEVAL_HINTS = (
    "根据",
    "基于",
    "资料",
    "文档",
    "知识库",
    "本地",
    "引用",
    "来源",
    "笔记",
    "论文",
    "文件",
    "readme",
    "docs",
    "document",
    "source",
    "citation",
    "knowledge base",
    "local knowledge",
)

_STUDY_HINTS = (
    "解释",
    "说明",
    "总结",
    "对比",
    "怎么",
    "如何",
    "为什么",
    "机制",
    "架构",
    "代码",
    "rag",
    "api",
    "fastapi",
    "react",
    "embedding",
    "chroma",
    "explain",
    "summarize",
    "compare",
    "how",
    "why",
)

_REWRITE_PATTERNS = (
    r"请?(根据|基于|参考|从|在)(本地)?(知识库|资料|文档|笔记|来源|引用|docs|readme)?(中|里)?",
    r"(回答|说明|解释|总结|一下|一下这个|这个问题)",
    r"(according to|based on|from|in)\s+(the\s+)?(local\s+)?(knowledge base|documents|docs|notes|sources)",
    r"(please|can you|could you|explain|summarize|answer)",
)

NOT_FOUND_CONTEXT = (
    "Local knowledge retrieval was attempted, but no relevant local documents were found. "
    "When answering, explicitly state that the local knowledge base did not contain supporting evidence."
)
INSUFFICIENT_CONTEXT = (
    "Related local material was retrieved, but the active corpus does not contain enough support "
    "for the specific question. Do not present a direct answer as grounded in the user's materials. "
    "State the evidence limitation and ask for missing material when useful."
)
UNCERTAIN_CONTEXT = (
    "Local retrieval found related material, but evidence coverage is uncertain. Do not turn partial "
    "topical similarity into a confident factual claim from the user's materials."
)


@dataclass(frozen=True)
class RetrievalAttempt:
    query: str
    result_count: int
    top_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "result_count": self.result_count,
            "top_score": self.top_score,
        }


@dataclass(frozen=True)
class LocalKnowledgeResult:
    status: LocalKnowledgeStatus
    query: str
    retrieval_mode: str
    reason: str
    context: str = ""
    sources: str = ""
    results: list[RagSearchResult] = field(default_factory=list)
    debug: dict[str, Any] = field(default_factory=dict)
    attempts: tuple[RetrievalAttempt, ...] = ()
    rewritten_query: str = ""

    @property
    def retrieved(self) -> bool:
        return self.status == "found"

    @property
    def attempted(self) -> bool:
        return self.status in {
            "found",
            "uncertain",
            "insufficient",
            "not_found",
            "index_missing",
            "error",
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "query": self.query,
            "retrieval_mode": self.retrieval_mode,
            "reason": self.reason,
            "context": self.context,
            "sources": self.sources,
            "result_count": len(self.results),
            "results": [result.to_dict() for result in self.results],
            "debug": self.debug,
            "attempts": [attempt.to_dict() for attempt in self.attempts],
            "rewritten_query": self.rewritten_query,
        }


def should_retrieve_local_knowledge(query: str) -> tuple[bool, str]:
    normalized = " ".join((query or "").strip().lower().split())
    if not normalized:
        return False, "empty_query"
    if any(re.search(pattern, normalized, re.I) for pattern in _SKIP_PATTERNS):
        return False, "conversational_query"
    if any(hint in normalized for hint in _RETRIEVAL_HINTS):
        return True, "explicit_local_knowledge_hint"
    if any(hint in normalized for hint in _STUDY_HINTS) and len(normalized) >= 8:
        return True, "study_question_hint"
    return False, "no_retrieval_signal"


def rewrite_local_knowledge_query(query: str) -> str:
    rewritten = query or ""
    for pattern in _REWRITE_PATTERNS:
        rewritten = re.sub(pattern, " ", rewritten, flags=re.I)
    rewritten = re.sub(r"[？?。！!,，:：；;]+", " ", rewritten)
    rewritten = " ".join(rewritten.split())
    return rewritten or query.strip()


def _attempt_from_results(query: str, results: list[RagSearchResult]) -> RetrievalAttempt:
    return RetrievalAttempt(
        query=query,
        result_count=len(results),
        top_score=results[0].score if results else 0.0,
    )


def _is_weak_result(results: list[RagSearchResult], weak_score_threshold: float) -> bool:
    if not results:
        return True
    return results[0].score < weak_score_threshold


def retrieve_local_knowledge(
    query: str,
    *,
    enabled: bool = True,
    force: bool = False,
    index_path: str | Path = DEFAULT_RAG_INDEX_PATH,
    top_k: int = 3,
    min_score: float = 0.01,
    retrieval_mode: str = "hybrid",
    context_max_chars: int = 3000,
    allow_rewrite: bool = True,
    weak_score_threshold: float = 0.05,
) -> LocalKnowledgeResult:
    if not enabled:
        return LocalKnowledgeResult(
            status="skipped",
            query=query,
            retrieval_mode=retrieval_mode,
            reason="disabled",
        )

    should_retrieve, reason = should_retrieve_local_knowledge(query)
    if not force and not should_retrieve:
        return LocalKnowledgeResult(
            status="skipped",
            query=query,
            retrieval_mode=retrieval_mode,
            reason=reason,
        )

    try:
        index = load_rag_index(index_path)
    except FileNotFoundError:
        return LocalKnowledgeResult(
            status="index_missing",
            query=query,
            retrieval_mode=retrieval_mode,
            reason="index_missing",
        )
    except Exception as exc:
        return LocalKnowledgeResult(
            status="error",
            query=query,
            retrieval_mode=retrieval_mode,
            reason=f"index_load_failed: {exc}",
        )

    active_index = retrievable_rag_index(index)
    attempts: list[RetrievalAttempt] = []
    debug: dict[str, Any] = {}
    selected_query = query
    try:
        diagnostics = search_documents_with_debug(
            active_index,
            query,
            top_k=top_k,
            min_score=min_score,
            retrieval_mode=retrieval_mode,
        )
        results = diagnostics.results
        attempts.append(_attempt_from_results(query, results))
        debug = diagnostics.debug

        rewritten_query = ""
        if allow_rewrite and _is_weak_result(results, weak_score_threshold):
            candidate = rewrite_local_knowledge_query(query)
            if candidate and candidate != query.strip():
                rewritten_diagnostics = search_documents_with_debug(
                    active_index,
                    candidate,
                    top_k=top_k,
                    min_score=min_score,
                    retrieval_mode=retrieval_mode,
                )
                rewritten_results = rewritten_diagnostics.results
                attempts.append(_attempt_from_results(candidate, rewritten_results))
                if rewritten_results:
                    results = rewritten_results
                    rewritten_query = candidate
                    selected_query = candidate
                    debug = rewritten_diagnostics.debug
                else:
                    results = []
                    rewritten_query = candidate
                    selected_query = candidate
                    debug = rewritten_diagnostics.debug

        decision = assess_evidence_sufficiency(active_index, selected_query, results)
        debug = {**debug, "sufficiency": decision.to_dict()}

        if not results:
            return LocalKnowledgeResult(
                status="not_found",
                query=query,
                retrieval_mode=retrieval_mode,
                reason="no_relevant_local_documents",
                context=NOT_FOUND_CONTEXT,
                debug=debug,
                attempts=tuple(attempts),
                rewritten_query=rewritten_query,
            )

        if decision.status != "supported":
            return LocalKnowledgeResult(
                status=decision.status,
                query=query,
                retrieval_mode=retrieval_mode,
                reason=decision.reason,
                context=(
                    INSUFFICIENT_CONTEXT
                    if decision.status == "insufficient"
                    else UNCERTAIN_CONTEXT
                ),
                debug=debug,
                attempts=tuple(attempts),
                rewritten_query=rewritten_query,
            )

        return LocalKnowledgeResult(
            status="found",
            query=query,
            retrieval_mode=retrieval_mode,
            reason=reason,
            context=build_rag_context(results, max_chars=context_max_chars),
            sources=format_rag_sources(results),
            results=results,
            debug=debug,
            attempts=tuple(attempts),
            rewritten_query=rewritten_query,
        )
    except Exception as exc:
        return LocalKnowledgeResult(
            status="error",
            query=query,
            retrieval_mode=retrieval_mode,
            reason=f"retrieval_failed: {exc}",
            attempts=tuple(attempts),
        )
