from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from src.rag import build_rag_index
from src.rag.answer_eval import (
    RagAnswerAssertion,
    RagAnswerCandidate,
    evaluate_answer_suite,
    load_answer_eval_fixture,
)
from src.rag.eval import evaluate_retrieval_profiles, load_eval_cases
from src.rag.schema import RagIndex
from src.rag.service import normalize_evidence_status, retrievable_rag_index
from src.rag.source_coverage import search_documents_with_adaptive_source_coverage
from src.rag.source_coverage_eval import evaluate_adaptive_source_coverage
from src.rag.sufficiency import assess_evidence_sufficiency


FIXTURE_DOCS = (
    "python_requests.md",
    "memory_routing.md",
    "news_pipeline.md",
    "fastapi_rag_runs.md",
    "frontend_workspace.md",
    "chinese_vector.md",
    "http_client_pooling.md",
    "memory_routing_legacy.md",
    "rag_upload_rebuild.md",
    "frontend_legacy_sidebar.md",
    "citation_policy.md",
    "learning_recovery.md",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the deterministic local RAG-K1 retrieval and answer-quality baseline."
    )
    parser.add_argument(
        "--fixture-dir",
        default="tests/fixtures/rag_eval",
        help="Directory containing the checked-in RAG quality corpus.",
    )
    parser.add_argument(
        "--output",
        default="rag-quality-baseline.json",
        help="JSON report path.",
    )
    return parser


def _unique_sources(sources: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for source in sources:
        normalized = source.replace("\\", "/")
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(source)
    return tuple(result)


def _corpus_fingerprint(paths: list[Path], fixture_dir: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: item.relative_to(fixture_dir).as_posix()):
        relative = path.relative_to(fixture_dir).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        content = path.read_bytes()
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _apply_evidence_manifest(index: RagIndex, path: Path) -> RagIndex:
    data = json.loads(path.read_text(encoding="utf-8"))
    raw_documents = data.get("documents", {})
    if not isinstance(raw_documents, dict):
        raise ValueError("RAG evidence manifest requires a 'documents' object")

    document_ids_by_name = {
        Path(document.source_path).name: document.document_id
        for document in index.documents
    }
    status_by_document_id: dict[str, tuple[str, str]] = {}
    for source_name, raw_config in raw_documents.items():
        if source_name not in document_ids_by_name:
            raise ValueError(f"Evidence manifest source is not in corpus: {source_name}")
        if not isinstance(raw_config, dict):
            raise ValueError(f"Evidence manifest entry must be an object: {source_name}")
        status = normalize_evidence_status(str(raw_config.get("evidence_status", "active")))
        replacement_name = str(raw_config.get("superseded_by", "")).strip()
        replacement_id = ""
        if replacement_name:
            replacement_id = document_ids_by_name.get(replacement_name, "")
            if not replacement_id:
                raise ValueError(
                    f"Evidence manifest superseding source is not in corpus: {replacement_name}"
                )
        status_by_document_id[document_ids_by_name[source_name]] = (status, replacement_id)

    documents = tuple(
        replace(
            document,
            evidence_status=status_by_document_id[document.document_id][0],
            superseded_by_document_id=status_by_document_id[document.document_id][1],
        )
        if document.document_id in status_by_document_id
        else document
        for document in index.documents
    )
    chunks = tuple(
        replace(
            chunk,
            evidence_status=status_by_document_id[chunk.document_id][0],
            superseded_by_document_id=status_by_document_id[chunk.document_id][1],
        )
        if chunk.document_id in status_by_document_id
        else chunk
        for chunk in index.chunks
    )
    return RagIndex(version=index.version, documents=documents, chunks=chunks)


def _search_for_case(index: RagIndex, case) -> list:
    return search_documents_with_adaptive_source_coverage(
        index,
        case.query,
        top_k=case.top_k,
        min_score=0.01,
        retrieval_mode=case.retrieval_mode,
        configured_max_chunks_per_source=case.max_chunks_per_source,
        reranker=case.reranker,
    ).results


def _evaluate_sufficiency(index: RagIndex, retrieval_cases) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    correct = 0
    answerable_total = 0
    answerable_supported = 0
    unanswerable_total = 0
    unanswerable_blocked = 0
    status_counts = {"supported": 0, "uncertain": 0, "insufficient": 0}

    for case in retrieval_cases:
        retrieved = _search_for_case(index, case)
        decision = assess_evidence_sufficiency(index, case.query, retrieved)
        predicted_answerable = decision.status == "supported"
        expected_answerable = bool(case.answerable)
        correct += int(predicted_answerable == expected_answerable)
        status_counts[decision.status] += 1
        if expected_answerable:
            answerable_total += 1
            answerable_supported += int(predicted_answerable)
        else:
            unanswerable_total += 1
            unanswerable_blocked += int(not predicted_answerable)
        results.append(
            {
                "case_id": case.case_id,
                "scenario": case.scenario,
                "expected_answerable": expected_answerable,
                **decision.to_dict(),
            }
        )

    total = len(retrieval_cases)
    return {
        "total_cases": total,
        "answerable_cases": answerable_total,
        "unanswerable_cases": unanswerable_total,
        "answerability_accuracy": round(correct / total, 6) if total else 0.0,
        "answerable_supported_rate": round(
            answerable_supported / answerable_total, 6
        ) if answerable_total else 0.0,
        "unanswerable_block_rate": round(
            unanswerable_blocked / unanswerable_total, 6
        ) if unanswerable_total else 0.0,
        "supported_rate": round(status_counts["supported"] / total, 6) if total else 0.0,
        "uncertain_rate": round(status_counts["uncertain"] / total, 6) if total else 0.0,
        "insufficient_rate": round(status_counts["insufficient"] / total, 6) if total else 0.0,
        "status_counts": status_counts,
        "results": results,
    }


def _build_extractive_candidates(
    index: RagIndex,
    answer_cases,
    retrieval_cases,
) -> tuple[RagAnswerCandidate, ...]:
    retrieval_by_id = {case.case_id: case for case in retrieval_cases}
    candidates: list[RagAnswerCandidate] = []
    for answer_case in answer_cases:
        retrieval_case = retrieval_by_id.get(answer_case.case_id)
        top_k = retrieval_case.top_k if retrieval_case is not None else 4
        diagnostics = search_documents_with_adaptive_source_coverage(
            index,
            answer_case.query,
            top_k=top_k,
            min_score=0.01,
            retrieval_mode=(
                retrieval_case.retrieval_mode if retrieval_case is not None else "hybrid"
            ),
            configured_max_chunks_per_source=(
                retrieval_case.max_chunks_per_source if retrieval_case is not None else 0
            ),
            reranker=(retrieval_case.reranker if retrieval_case is not None else "disabled"),
        )
        results = diagnostics.results
        decision = assess_evidence_sufficiency(index, answer_case.query, results)
        if decision.status != "supported":
            candidates.append(
                RagAnswerCandidate(
                    case_id=answer_case.case_id,
                    answer="",
                    cited_sources=(),
                    refused=True,
                    assertions=(),
                )
            )
            continue
        assertions = tuple(
            RagAnswerAssertion(
                text=result.chunk.text,
                cited_sources=(result.chunk.source_path,),
            )
            for result in results
        )
        cited_sources = _unique_sources(
            [result.chunk.source_path for result in results]
        )
        candidates.append(
            RagAnswerCandidate(
                case_id=answer_case.case_id,
                answer="\n\n".join(result.chunk.text for result in results),
                cited_sources=cited_sources,
                refused=False,
                assertions=assertions,
            )
        )
    return tuple(candidates)


def run_baseline(fixture_dir: Path) -> dict[str, Any]:
    document_paths = [fixture_dir / name for name in FIXTURE_DOCS]
    retrieval_case_path = fixture_dir / "cases.json"
    answer_case_path = fixture_dir / "answer_cases.json"
    evidence_manifest_path = fixture_dir / "evidence_manifest.json"
    corpus_paths = [
        *document_paths,
        retrieval_case_path,
        answer_case_path,
        evidence_manifest_path,
    ]
    missing = [str(path) for path in corpus_paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing RAG quality corpus files: {', '.join(missing)}")

    index = build_rag_index(document_paths, max_chars=700, overlap_chars=80)
    index = _apply_evidence_manifest(index, evidence_manifest_path)
    active_index = retrievable_rag_index(index)
    retrieval_cases = load_eval_cases(retrieval_case_path)
    retrieval_profiles = evaluate_retrieval_profiles(index, retrieval_cases)
    adaptive_source_coverage = evaluate_adaptive_source_coverage(
        active_index,
        retrieval_cases,
    )
    sufficiency_summary = _evaluate_sufficiency(active_index, retrieval_cases)
    answer_cases, _ = load_answer_eval_fixture(answer_case_path)
    extractive_candidates = _build_extractive_candidates(
        active_index,
        answer_cases,
        retrieval_cases,
    )
    answer_summary = evaluate_answer_suite(answer_cases, extractive_candidates)

    status_counts: dict[str, int] = {}
    for document in index.documents:
        status_counts[document.evidence_status] = status_counts.get(document.evidence_status, 0) + 1

    return {
        "schema_version": 4,
        "baseline_kind": "deterministic_local_extractive_lower_bound",
        "gating": "record_only",
        "corpus": {
            "fingerprint_sha256": _corpus_fingerprint(corpus_paths, fixture_dir),
            "documents": len(document_paths),
            "retrieval_cases": len(retrieval_cases),
            "answer_cases": len(answer_cases),
            "evidence_status_counts": status_counts,
            "document_paths": [str(path).replace("\\", "/") for path in document_paths],
        },
        "retrieval_profiles": {
            name: summary.to_dict() for name, summary in retrieval_profiles.items()
        },
        "adaptive_source_coverage": adaptive_source_coverage.to_dict(),
        "evidence_sufficiency": sufficiency_summary,
        "answer_quality": answer_summary.to_dict(),
    }


def main() -> int:
    args = _parser().parse_args()
    report = run_baseline(Path(args.fixture_dir))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    hybrid = dict(report["retrieval_profiles"]["hybrid"])
    hybrid.pop("results", None)
    adaptive = dict(report["adaptive_source_coverage"])
    adaptive.pop("results", None)
    answer_quality = dict(report["answer_quality"])
    answer_quality.pop("results", None)
    sufficiency = dict(report["evidence_sufficiency"])
    sufficiency.pop("results", None)
    compact = {
        "baseline_kind": report["baseline_kind"],
        "gating": report["gating"],
        "corpus": report["corpus"],
        "hybrid": hybrid,
        "adaptive_source_coverage": adaptive,
        "evidence_sufficiency": sufficiency,
        "answer_quality": answer_quality,
    }
    print(json.dumps(compact, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
