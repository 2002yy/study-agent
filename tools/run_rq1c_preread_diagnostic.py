"""Diagnose the two RQ1-C cases that exhausted budget before any read.

This is non-qualification diagnostic evidence. It selects the two already-known
case IDs from the untouched 12-case manifest, executes the production active
Claim Engine with the unchanged bounded ResearchBudget, and projects only safe
runtime metadata. No model response text, prompts, page bodies, or query text are
written to the artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.application.active_research_runtime import ACTIVE_RESEARCH_METRICS_KEY  # noqa: E402
from src.application.research_web_lookup_dispatch import (  # noqa: E402
    ClaimEngineDispatchWebLookupService,
)
from src.domain.runtime_entities import WebLookupRun  # noqa: E402
from src.infrastructure.sqlite.database import RuntimeDatabase  # noqa: E402
from src.repositories.web_lookup_repository import WebLookupRepository  # noqa: E402
from tools.rq1c_git_identity import exact_checkout_git_sha  # noqa: E402
from tools.run_rq1c_bounded_qualification_core import (  # noqa: E402
    DEFAULT_MANIFEST,
    _active_context,
    _load_manifest,
)

SCHEMA_VERSION = "rq1c-preread-starvation-diagnostic-v1"
TARGET_CASE_IDS = (
    "rq1c-academic-primary-attention",
    "rq1c-unverifiable-python-security",
)
DEFAULT_OUTPUT = REPO_ROOT / "output" / "rq1c-preread-starvation-diagnostic.json"


def _bounded(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _count(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _duration(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed < 0 or parsed != parsed:
        return None
    return round(parsed, 6)


def _model_call_rows(runtime: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw_calls = runtime.get("model_calls")
    rows: list[dict[str, Any]] = []
    if not isinstance(raw_calls, list):
        return rows
    for raw in raw_calls:
        if not isinstance(raw, Mapping):
            continue
        rows.append(
            {
                "purpose": _bounded(raw.get("purpose"), 100),
                "attempt": _count(raw.get("attempt")),
                "status": _bounded(raw.get("status"), 80),
                "elapsed_seconds": _duration(raw.get("elapsed_seconds")),
                "error_type": _bounded(raw.get("error_type"), 120),
                "finish_reason": _bounded(raw.get("finish_reason"), 80),
                "input_tokens": _count(raw.get("input_tokens")),
                "output_tokens": _count(raw.get("output_tokens")),
                "total_tokens": _count(raw.get("total_tokens")),
            }
        )
    return rows


def _run_case(
    *,
    case: Mapping[str, str],
    repository: WebLookupRepository,
    service: ClaimEngineDispatchWebLookupService,
    reference_date: str,
) -> dict[str, Any]:
    case_id = case["id"]
    started = time.monotonic()
    run = repository.create(
        WebLookupRun(
            id=f"rq1c_preread_{case_id}",
            query=case["question"],
            stage="planned",
            status="pending",
            research_context=_active_context(reference_date),
            max_items=5,
        )
    )
    error_type = ""
    try:
        completed = service.execute(run.id, raise_on_error=False)
    except Exception as exc:
        error_type = type(exc).__name__[:120]
        completed = repository.get(run.id) or run

    context = completed.research_context if isinstance(completed.research_context, Mapping) else {}
    runtime = context.get("claim_engine_runtime")
    runtime = runtime if isinstance(runtime, Mapping) else {}
    metrics = context.get(ACTIVE_RESEARCH_METRICS_KEY)
    metrics = metrics if isinstance(metrics, Mapping) else {}
    candidates = runtime.get("candidates")
    reads = runtime.get("read_outcomes")
    planned_reads = runtime.get("planned_read_ids")
    model_calls = _model_call_rows(runtime)
    query_outcomes = runtime.get("query_outcomes")
    return {
        "case_id": case_id,
        "category": case["category"],
        "elapsed_seconds": round(max(0.0, time.monotonic() - started), 3),
        "runner_error_type": error_type,
        "run": {
            "status": _bounded(completed.status, 80),
            "provider_status": _bounded(completed.provider_status, 80),
            "stop_reason": _bounded(completed.stop_reason, 160),
            "stage": _bounded(completed.stage, 80),
        },
        "runtime": {
            "phase": _bounded(runtime.get("phase"), 80),
            "wave_index": _count(runtime.get("wave_index")),
            "candidate_count": len(candidates) if isinstance(candidates, list) else 0,
            "query_outcome_count": len(query_outcomes) if isinstance(query_outcomes, list) else 0,
            "planned_read_count": len(planned_reads) if isinstance(planned_reads, list) else 0,
            "read_attempt_count": len(reads) if isinstance(reads, list) else 0,
            "read_count": _count(metrics.get("read_count")) or 0,
            "model_call_count": len(model_calls),
            "model_calls": model_calls,
        },
        "stores_raw_model_text": False,
        "stores_query_text": False,
        "stores_page_bodies": False,
    }


def run_diagnostic(
    *,
    manifest_path: Path,
    output_path: Path,
    reference_date: str,
) -> dict[str, Any]:
    git_sha = exact_checkout_git_sha(REPO_ROOT)
    all_cases = _load_manifest(manifest_path)
    by_id = {case["id"]: case for case in all_cases}
    cases = [by_id[case_id] for case_id in TARGET_CASE_IDS]
    artifact: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "git_sha": git_sha,
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "reference_date": reference_date,
        "case_ids": list(TARGET_CASE_IDS),
        "configured_budget": {
            "max_candidates": 20,
            "max_reads": 8,
            "soft_timeout_seconds": 45,
            "hard_timeout_seconds": 60,
        },
        "cases": [],
        "stores_raw_model_text": False,
        "stores_query_text": False,
        "stores_page_bodies": False,
    }
    tmp = tempfile.mkdtemp(prefix="rq1c_preread_diag_")
    try:
        database = RuntimeDatabase(Path(tmp) / "diagnostic.sqlite")
        repository = WebLookupRepository(database)
        service = ClaimEngineDispatchWebLookupService(repository)
        for case in cases:
            record = _run_case(
                case=case,
                repository=repository,
                service=service,
                reference_date=reference_date,
            )
            artifact["cases"].append(record)
            print(
                json.dumps(
                    {
                        "case_id": record["case_id"],
                        "elapsed_seconds": record["elapsed_seconds"],
                        "phase": record["runtime"]["phase"],
                        "model_calls": record["runtime"]["model_call_count"],
                        "reads": record["runtime"]["read_count"],
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return artifact


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--reference-date", default="2026-09-05")
    return parser


def main() -> int:
    args = _parser().parse_args()
    artifact = run_diagnostic(
        manifest_path=args.manifest.resolve(),
        output_path=args.output.resolve(),
        reference_date=str(args.reference_date),
    )
    assert len(artifact["cases"]) == 2
    assert artifact["stores_raw_model_text"] is False
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
