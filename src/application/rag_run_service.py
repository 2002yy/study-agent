"""Server-owned RAG query/upload/rebuild workflows and KB lifecycle."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.domain.runtime_entities import RagRun
from src.rag.eval import RagEvalCase, evaluate_case
from src.rag.index import load_rag_index
from src.rag.service import (
    append_documents_to_index_with_stages,
    build_rag_context,
    build_rag_debug,
    delete_knowledge_document,
    format_rag_sources,
    index_documents_with_stages,
    list_knowledge_documents,
    search_documents,
)
from src.repositories.rag_repository import RagRepository


class RagRunService:
    def __init__(self, repository: RagRepository):
        self.repository = repository

    def query(self, request: dict[str, Any], *, index_path: Path) -> RagRun:
        frozen = dict(request)
        frozen["index_path"] = str(index_path)
        run = self.repository.create(RagRun(kind="query", request=frozen))
        try:
            index = load_rag_index(index_path)
            results = search_documents(
                index,
                str(frozen["query"]),
                top_k=int(frozen.get("top_k", 5)),
                min_score=float(frozen.get("min_score", 0.01)),
                retrieval_mode=str(frozen.get("retrieval_mode", "hybrid")),
            )
            debug = build_rag_debug(
                index,
                str(frozen["query"]),
                results,
                retrieval_mode=str(frozen.get("retrieval_mode", "hybrid")),
                top_k=int(frozen.get("top_k", 5)),
                min_score=float(frozen.get("min_score", 0.01)),
            )
            evaluation = None
            if frozen.get("expected_sources"):
                evaluation = evaluate_case(
                    index,
                    RagEvalCase(
                        query=str(frozen["query"]),
                        expected_sources=tuple(frozen.get("expected_sources") or ()),
                        expected_terms=tuple(frozen.get("expected_terms") or ()),
                        top_k=int(frozen.get("top_k", 5)),
                        retrieval_mode=str(frozen.get("retrieval_mode", "hybrid")),
                    ),
                    min_score=float(frozen.get("min_score", 0.01)),
                ).to_dict()
            payload = {
                "query": frozen["query"],
                "retrieval_mode": frozen.get("retrieval_mode", "hybrid"),
                "result_count": len(results),
                "context": build_rag_context(
                    results,
                    max_chars=int(frozen.get("context_max_chars", 3000)),
                ),
                "sources": format_rag_sources(results),
                "results": [result.to_dict() for result in results],
                "debug": debug,
                "evaluation": evaluation,
            }
            return self.repository.complete(
                run.id, result=payload, index_version=index.version
            )
        except Exception as exc:
            self.repository.fail(run.id, str(exc))
            raise

    def index(
        self,
        paths: list[Path],
        *,
        mode: str,
        index_path: Path,
        max_chars: int,
        overlap_chars: int,
    ) -> RagRun:
        if mode not in {"upload", "rebuild"}:
            raise ValueError(f"Unsupported RAG write mode: {mode}")
        request = {
            "paths": [str(path) for path in paths],
            "index_path": str(index_path),
            "max_chars": max_chars,
            "overlap_chars": overlap_chars,
        }
        run = self.repository.create(RagRun(kind=mode, request=request))
        expected_version = _index_version(index_path)
        staging_version = expected_version + 1
        try:
            state = self.repository.begin_index_write(
                str(index_path.resolve()),
                expected_version=expected_version,
            )
            staging_version = int(state["staging_version"])
            if mode == "rebuild":
                write = index_documents_with_stages(
                    paths,
                    index_path=index_path,
                    max_chars=max_chars,
                    overlap_chars=overlap_chars,
                    target_version=staging_version,
                )
            else:
                write = append_documents_to_index_with_stages(
                    paths,
                    index_path=index_path,
                    max_chars=max_chars,
                    overlap_chars=overlap_chars,
                    target_version=staging_version,
                )
            payload = {
                "documents": len(write.index.documents),
                "chunks": len(write.index.chunks),
                "index_path": str(index_path),
                "index_version": write.active_version,
                "staging_version": staging_version,
                "activated": write.activated,
                "stages": write.stages,
            }
            if not write.activated:
                detail = _failed_stage_detail(write.stages)
                self.repository.fail_index_write(
                    str(index_path.resolve()),
                    staging_version=staging_version,
                    error=detail,
                )
                return self.repository.partial_success(
                    run.id,
                    result=payload,
                    error=detail,
                    index_version=write.active_version,
                )
            self.repository.activate_index(
                str(index_path.resolve()),
                staging_version=staging_version,
                document_count=len(write.index.documents),
                chunk_count=len(write.index.chunks),
            )
            return self.repository.complete(
                run.id,
                result=payload,
                index_version=write.active_version,
            )
        except Exception as exc:
            current_state = self.repository.get_index_state(
                str(index_path.resolve())
            )
            if (
                current_state is not None
                and current_state.get("staging_version") == staging_version
            ):
                self.repository.fail_index_write(
                    str(index_path.resolve()),
                    staging_version=staging_version,
                    error=str(exc),
                )
            self.repository.fail(run.id, str(exc))
            raise

    def get(self, run_id: str) -> RagRun:
        run = self.repository.get(run_id)
        if run is None:
            raise ValueError(f"RagRun not found: {run_id}")
        return run

    def list(self, *, kind: str | None = None, limit: int = 20) -> list[RagRun]:
        return self.repository.list(kind=kind, limit=limit)

    def documents(self, *, index_path: Path) -> dict[str, Any]:
        return list_knowledge_documents(index_path)

    def delete_document(
        self, document_id: str, *, index_path: Path
    ) -> dict[str, Any]:
        expected_version = _index_version(index_path)
        state = self.repository.begin_index_write(
            str(index_path.resolve()),
            expected_version=expected_version,
        )
        staging_version = int(state["staging_version"])
        try:
            result = delete_knowledge_document(
                document_id,
                index_path=index_path,
                target_version=staging_version,
            )
            if not result["activated"]:
                detail = _failed_stage_detail(result["stages"])
                self.repository.fail_index_write(
                    str(index_path.resolve()),
                    staging_version=staging_version,
                    error=detail,
                )
                raise RuntimeError(
                    f"Knowledge document deletion was not activated: {detail}"
                )
            self.repository.activate_index(
                str(index_path.resolve()),
                staging_version=staging_version,
                document_count=int(result["documents"]),
                chunk_count=int(result["chunks"]),
            )
            return result
        except Exception as exc:
            current = self.repository.get_index_state(str(index_path.resolve()))
            if (
                current is not None
                and current.get("staging_version") == staging_version
            ):
                self.repository.fail_index_write(
                    str(index_path.resolve()),
                    staging_version=staging_version,
                    error=str(exc),
                )
            raise


def _index_version(index_path: Path) -> int:
    if not index_path.is_file():
        return 0
    return load_rag_index(index_path).version


def _failed_stage_detail(stages: list[dict[str, Any]]) -> str:
    failed = next(
        (stage for stage in stages if stage.get("status") == "failed"),
        None,
    )
    return str((failed or {}).get("detail") or "required RAG index stage failed")
