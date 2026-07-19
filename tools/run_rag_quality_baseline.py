from __future__ import annotations

import argparse
import hashlib
import json
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
from src.rag.service import search_documents


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


def _build_extractive_candidates(
    index,
    answer_cases,
    retrieval_cases,
) -> tuple[RagAnswerCandidate, ...]:
    retrieval_by_id = {case.case_id: case for case in retrieval_cases}
    candidates: list[RagAnswerCandidate] = []
    for answer_case in answer_cases:
        retrieval_case = retrieval_by_id.get(answer_case.case_id)
        top_k = retrieval_case.top_k if retrieval_case is not None else 4
        results = search_documents(
            index,
            answer_case.query,
            top_k=top_k,
            min_score=0.01,
            retrieval_mode=(
                retrieval_case.retrieval_mode if retrieval_case is not None else "hybrid"
            ),
            reranker=(retrieval_case.reranker if retrieval_case is not None else "disabled"),
        )
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
                refused=not results,
                assertions=assertions,
            )
        )
    return tuple(candidates)


def run_baseline(fixture_dir: Path) -> dict[str, Any]:
    document_paths = [fixture_dir / name for name in FIXTURE_DOCS]
    retrieval_case_path = fixture_dir / "cases.json"
    answer_case_path = fixture_dir / "answer_cases.json"
    corpus_paths = [*document_paths, retrieval_case_path, answer_case_path]
    missing = [str(path) for path in corpus_paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing RAG quality corpus files: {', '.join(missing)}")

    index = build_rag_index(document_paths, max_chars=700, overlap_chars=80)
    retrieval_cases = load_eval_cases(retrieval_case_path)
    retrieval_profiles = evaluate_retrieval_profiles(index, retrieval_cases)
    answer_cases, _ = load_answer_eval_fixture(answer_case_path)
    extractive_candidates = _build_extractive_candidates(
        index,
        answer_cases,
        retrieval_cases,
    )
    answer_summary = evaluate_answer_suite(answer_cases, extractive_candidates)

    return {
        "schema_version": 1,
        "baseline_kind": "deterministic_local_extractive_lower_bound",
        "gating": "record_only",
        "corpus": {
            "fingerprint_sha256": _corpus_fingerprint(corpus_paths, fixture_dir),
            "documents": len(document_paths),
            "retrieval_cases": len(retrieval_cases),
            "answer_cases": len(answer_cases),
            "document_paths": [str(path).replace("\\", "/") for path in document_paths],
        },
        "retrieval_profiles": {
            name: summary.to_dict() for name, summary in retrieval_profiles.items()
        },
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
    answer_quality = dict(report["answer_quality"])
    answer_quality.pop("results", None)
    compact = {
        "baseline_kind": report["baseline_kind"],
        "gating": report["gating"],
        "corpus": report["corpus"],
        "hybrid": hybrid,
        "answer_quality": answer_quality,
    }
    print(json.dumps(compact, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
