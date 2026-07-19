from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from src.rag import build_rag_index, save_rag_index
from src.rag.answer_eval import RagAnswerEvalCase, load_answer_eval_fixture
from src.rag.provider_replay import (
    OpenAICompatibleReplayProvider,
    ReplayRetrieval,
    provider_unavailable_report,
    run_provider_answer_replay,
)
from src.rag.eval import load_eval_cases
from src.tools.local_knowledge import retrieve_local_knowledge
from tools.run_rag_quality_baseline import (
    FIXTURE_DOCS,
    _apply_evidence_manifest,
    _corpus_fingerprint,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the K1e source-grounded answer benchmark through Study Agent's "
            "configured real LLM provider."
        )
    )
    parser.add_argument(
        "--fixture-dir",
        default="tests/fixtures/rag_eval",
        help="Directory containing the fixed K1 RAG corpus and gold cases.",
    )
    parser.add_argument(
        "--output",
        default="rag-provider-replay.json",
        help="JSON report path.",
    )
    parser.add_argument(
        "--provider-profile",
        default=None,
        help="Study Agent provider profile. Defaults to LLM_PROVIDER_PROFILE/openai.",
    )
    parser.add_argument(
        "--model-profile",
        choices=("flash", "pro"),
        default="pro",
    )
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=700)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument(
        "--case-id",
        action="append",
        default=[],
        help="Run only selected case IDs. Repeat for multiple cases.",
    )
    return parser


def _fixture_paths(fixture_dir: Path) -> tuple[list[Path], list[Path]]:
    documents = [fixture_dir / name for name in FIXTURE_DOCS]
    metadata = [
        fixture_dir / "cases.json",
        fixture_dir / "answer_cases.json",
        fixture_dir / "evidence_manifest.json",
    ]
    return documents, metadata


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _resolved_provider_profile(value: str | None) -> str:
    return (value or os.getenv("LLM_PROVIDER_PROFILE") or "openai").strip().lower()


def main() -> int:
    args = _parser().parse_args()
    fixture_dir = Path(args.fixture_dir)
    document_paths, metadata_paths = _fixture_paths(fixture_dir)
    corpus_paths = [*document_paths, *metadata_paths]
    missing = [str(path) for path in corpus_paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            f"Missing K1e replay fixture files: {', '.join(missing)}"
        )

    corpus_fingerprint = _corpus_fingerprint(corpus_paths, fixture_dir)
    answer_cases, _ = load_answer_eval_fixture(fixture_dir / "answer_cases.json")
    if args.case_id:
        selected = set(args.case_id)
        answer_cases = tuple(case for case in answer_cases if case.case_id in selected)
        missing_case_ids = sorted(selected - {case.case_id for case in answer_cases})
        if missing_case_ids:
            raise ValueError(
                "Unknown K1e case IDs: " + ", ".join(missing_case_ids)
            )
    retrieval_cases = load_eval_cases(fixture_dir / "cases.json")
    retrieval_by_id = {case.case_id: case for case in retrieval_cases}

    provider_profile = _resolved_provider_profile(args.provider_profile)
    try:
        provider = OpenAICompatibleReplayProvider(
            provider_profile=provider_profile,
            model_profile=args.model_profile,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
            timeout=args.timeout,
        )
    except Exception as exc:
        report = provider_unavailable_report(
            corpus_fingerprint=corpus_fingerprint,
            provider_profile=provider_profile,
            reason=f"provider_initialization_failed:{type(exc).__name__}",
        )
        _write_report(Path(args.output), report)
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 2

    index = build_rag_index(document_paths, max_chars=700, overlap_chars=80)
    index = _apply_evidence_manifest(index, fixture_dir / "evidence_manifest.json")

    with tempfile.TemporaryDirectory(prefix="study-agent-k1e-") as temp_dir:
        index_path = Path(temp_dir) / "rag_index.json"
        save_rag_index(index, index_path)

        def retrieve_case(case: RagAnswerEvalCase) -> ReplayRetrieval:
            retrieval_case = retrieval_by_id.get(case.case_id)
            top_k = retrieval_case.top_k if retrieval_case is not None else 4
            retrieval_mode = (
                retrieval_case.retrieval_mode
                if retrieval_case is not None
                else "hybrid"
            )
            result = retrieve_local_knowledge(
                case.query,
                enabled=True,
                force=True,
                index_path=index_path,
                top_k=top_k,
                min_score=0.01,
                retrieval_mode=retrieval_mode,
                allow_rewrite=True,
            )
            return ReplayRetrieval(
                status=result.status,
                reason=result.reason,
                context=result.context,
                results=tuple(result.results),
            )

        report = run_provider_answer_replay(
            cases=answer_cases,
            retrieve_case=retrieve_case,
            provider=provider,
            corpus_fingerprint=corpus_fingerprint,
        )

    report["scope"] = {
        "case_ids": [case.case_id for case in answer_cases],
        "full_gold_suite": not bool(args.case_id),
    }
    _write_report(Path(args.output), report)
    compact = {
        "replay_kind": report["replay_kind"],
        "status": report["status"],
        "corpus_fingerprint": report["corpus_fingerprint"],
        "provider": report["provider"],
        "cases": report["cases"],
        "completed_cases": report["completed_cases"],
        "latency": report["latency"],
        "usage": report["usage"],
        "answer_quality": report["answer_quality"],
    }
    print(json.dumps(compact, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "completed" else 3


if __name__ == "__main__":
    raise SystemExit(main())
