"""Small RQ1-C evidence-path trace (diagnostic, not qualification evidence).

Runs a couple of holdout cases through the production research runtime and dumps
the durable cursor as a bounded evidence path: candidate count/providers, which
candidates were planned for reading, read outcomes, gain history, saturation
counters, model-call purposes, and the stop reason. Raw page bodies, query text,
and provider messages are never written.

This tool exists to answer one question: where does the evidence chain stop?
(selection / reader / source assessment / claim binding / stop policy)
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

import tools.run_rq1c_bounded_qualification_core as core  # noqa: E402
from src.application.active_research_runtime import (  # noqa: E402
    ACTIVE_RESEARCH_BRIEF_KEY,
    ACTIVE_RESEARCH_METRICS_KEY,
)
from src.application.research_web_lookup_dispatch import (  # noqa: E402
    ClaimEngineDispatchWebLookupService,
)
from src.domain.runtime_entities import WebLookupRun  # noqa: E402
from src.infrastructure.sqlite.database import RuntimeDatabase  # noqa: E402
from src.repositories.web_lookup_repository import WebLookupRepository  # noqa: E402

DEFAULT_MANIFEST = (
    REPO_ROOT
    / "tests"
    / "fixtures"
    / "research_quality"
    / "rq1c_bounded_holdout_manifest.json"
)
DEFAULT_OUTPUT = (
    REPO_ROOT / "docs" / "research_quality" / "RQ1C_EVIDENCE_PATH_TRACE.json"
)
SCHEMA_VERSION = "rq1c-evidence-path-trace-v1"
DEFAULT_CASE_LIMIT = 3

_RANK_CAPTURE: list[dict[str, Any]] = []


def _install_rank_capture() -> None:
    import src.application.active_research_runtime as runtime_module

    original = runtime_module.rank_candidate_pool

    def recording_rank(*args: Any, **kwargs: Any) -> Any:
        ranked = original(*args, **kwargs)
        for item in ranked:
            _RANK_CAPTURE.append(
                {
                    "candidate_id": item.candidate.id,
                    "rank": item.rank,
                    "eligibility": item.eligibility,
                    "reason_codes": list(item.reason_codes),
                    "new_cluster": item.new_cluster,
                    "expected_information_gain": item.expected_information_gain,
                    "relevance": item.assessment.relevance,
                    "source_role": item.assessment.source_role,
                    "gain_signals": list(item.assessment.expected_gain_signals),
                    "cluster_id": item.assessment.cluster_id,
                }
            )
        return ranked

    runtime_module.rank_candidate_pool = recording_rank


def _bounded(value: Any, limit: int = 120) -> Any:
    if isinstance(value, str):
        return value[:limit]
    return value


def _candidate_row(candidate: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": candidate.get("id"),
        "providers": list(candidate.get("providers") or []),
        "intents": list(candidate.get("intents") or []),
        "first_seen_rank": candidate.get("first_seen_rank"),
        "published_at": candidate.get("published_at"),
        "source_chars": len(str(candidate.get("source") or "")),
        "title_chars": len(str(candidate.get("title") or "")),
        "snippet_chars": len(str(candidate.get("snippet") or "")),
    }


def _model_call_row(call: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "purpose": call.get("purpose"),
        "status": call.get("status"),
        "attempt": call.get("attempt"),
        "error_type": _bounded(call.get("error_type"), 80),
        "finish_reason": call.get("finish_reason"),
        "output_tokens": call.get("output_tokens"),
    }


def _trace_case(
    *,
    case: Mapping[str, str],
    repository: WebLookupRepository,
    service: ClaimEngineDispatchWebLookupService,
    reference_date: str,
) -> dict[str, Any]:
    run = repository.create(
        WebLookupRun(
            id=f"rq1c_trace_{case['id']}",
            query=case["question"],
            stage="planned",
            status="pending",
            research_context=core._active_context(reference_date),
            max_items=5,
        )
    )
    try:
        _RANK_CAPTURE.clear()
        completed = service.execute(run.id, raise_on_error=False)
    except Exception as exc:  # diagnostic taxonomy only
        return {
            "case_id": case["id"],
            "error_type": type(exc).__name__,
        }
    ranked_candidates = list(_RANK_CAPTURE)

    context = completed.research_context
    runtime = context.get("claim_engine_runtime")
    if not isinstance(runtime, Mapping):
        runtime = {}
    metrics = context.get(ACTIVE_RESEARCH_METRICS_KEY)
    if not isinstance(metrics, Mapping):
        metrics = {}
    brief = context.get(ACTIVE_RESEARCH_BRIEF_KEY)
    if not isinstance(brief, Mapping):
        brief = {}

    candidates = [c for c in (runtime.get("candidates") or []) if isinstance(c, Mapping)]
    read_outcomes = [
        o for o in (runtime.get("read_outcomes") or []) if isinstance(o, Mapping)
    ]
    model_calls = [m for m in (runtime.get("model_calls") or []) if isinstance(m, Mapping)]

    return {
        "case_id": case["id"],
        "category": case["category"],
        "run_status": completed.status,
        "provider_status": completed.provider_status,
        "stop_reason": completed.stop_reason,
        "phase": runtime.get("phase"),
        "wave_index": runtime.get("wave_index"),
        "candidate_count": len(candidates),
        "candidates": [_candidate_row(c) for c in candidates[:20]],
        "ranked_candidates": ranked_candidates[:30],
        "planned_read_ids": list(runtime.get("planned_read_ids") or []),
        "read_outcomes": [
            {
                "candidate_id": o.get("candidate_id"),
                "status": o.get("status"),
                "error_code": _bounded(o.get("error_code"), 80),
                "content_chars": o.get("content_chars"),
                "evidence_id_present": bool(o.get("evidence_id")),
            }
            for o in read_outcomes[:20]
        ],
        "model_calls": [_model_call_row(m) for m in model_calls[:20]],
        "no_gain_batches_by_claim": dict(runtime.get("no_gain_batches_by_claim") or {}),
        "no_gain_batches_by_gap": dict(runtime.get("no_gain_batches_by_gap") or {}),
        "gain_history": [
            {
                "new_eligible_evidence": g.get("new_eligible_evidence"),
                "new_independent_cluster": g.get("new_independent_cluster"),
                "claim_status_improvement": g.get("claim_status_improvement"),
                "gain_reasons_by_claim": g.get("gain_reasons_by_claim"),
            }
            for g in (runtime.get("gain_history") or [])[:10]
            if isinstance(g, Mapping)
        ],
        "failures": [
            {
                "code": f.get("code"),
                "phase": f.get("phase"),
                "detail": _bounded(f.get("detail"), 80),
            }
            for f in (runtime.get("failures") or [])[:20]
            if isinstance(f, Mapping)
        ],
        "metrics": {
            "candidate_count": metrics.get("candidate_count"),
            "cluster_count": metrics.get("cluster_count"),
            "read_count": metrics.get("read_count"),
            "open_critical_gap_count": metrics.get("open_critical_gap_count"),
            "phase": metrics.get("phase"),
        },
        "gate_status": brief.get("gate_status") or metrics.get("gate_status"),
        "brief_gate_reasons": list(brief.get("gate_reasons") or [])[:10],
        "eligible_evidence_count": len(brief.get("eligible_evidence") or []),
        "open_gap_ids": list(brief.get("open_gap_ids") or [])[:10],
    }


def run_trace(
    *,
    manifest_path: Path = DEFAULT_MANIFEST,
    case_ids: tuple[str, ...] = (),
    case_limit: int = DEFAULT_CASE_LIMIT,
    output_path: Path | None = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    load_dotenv(REPO_ROOT / ".env")
    _install_rank_capture()
    cases = core._load_manifest(manifest_path)
    if case_ids:
        selected = tuple(c for c in cases if c["id"] in set(case_ids))
    else:
        selected = cases[: max(1, case_limit)]
    reference_date = datetime.now(timezone.utc).date().isoformat()

    tmp = tempfile.mkdtemp(prefix="rq1c_evidence_trace_")
    try:
        database = RuntimeDatabase(Path(tmp) / "trace.sqlite")
        repository = WebLookupRepository(database)
        service = ClaimEngineDispatchWebLookupService(
            repository,
            active_runtime_factory=core._qualification_active_runtime_factory,
        )
        rows = [
            _trace_case(
                case=case,
                repository=repository,
                service=service,
                reference_date=reference_date,
            )
            for case in selected
        ]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    artifact = {
        "schema_version": SCHEMA_VERSION,
        "reference_date": reference_date,
        "case_count": len(rows),
        "cases": rows,
    }
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return artifact


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--limit", type=int, default=DEFAULT_CASE_LIMIT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main() -> int:
    args = _parser().parse_args()
    artifact = run_trace(
        manifest_path=args.manifest.resolve(),
        case_ids=tuple(str(item) for item in args.case_id),
        case_limit=max(1, min(int(args.limit), 12)),
        output_path=args.output.resolve() if args.output else None,
    )
    print(
        json.dumps(
            {
                "case_count": artifact["case_count"],
                "stop_reasons": [c.get("stop_reason") for c in artifact["cases"]],
                "candidate_counts": [c.get("candidate_count") for c in artifact["cases"]],
                "planned_reads": [
                    len(c.get("planned_read_ids") or []) for c in artifact["cases"]
                ],
                "read_outcomes": [
                    len(c.get("read_outcomes") or []) for c in artifact["cases"]
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
