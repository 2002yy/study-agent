"""Answer-stage replay calibration (diagnostic only, never qualification).

The qualification contract times answer generation out at the production LLM
timeout (``LLM_TIMEOUT_SECONDS``, default 30s), so the measured finalization
p90 was a *truncated* distribution: 7 of 12 generation calls ended at
30.09-30.13s with an error and produced no answer. This tool measures the
untruncated distribution without paying for research every time:

    one real research run per case
      -> many real production answer generations against that frozen run

Nothing is simplified: the prompt is built by the same
``_production_chat_command`` + production chat service the qualification runner
uses, from the persisted ResearchRun. Only the diagnostic limits differ
(``--answer-timeout-seconds`` / ``--deadline-seconds``), and they exist purely
to observe the tail.

Two boundaries are deliberately preserved:

* ``qualification_evidence = false`` in the artifact: widening a timeout for
  diagnostics is not, and must never become, a qualification configuration;
* the deadline invariant stays intact - every generation is dispatched with
  ``min(configured_or_floor, remaining_seconds)``, so a 120s diagnostic answer
  budget can never overrun the diagnostic deadline either.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

from tools import run_rq1c_bounded_qualification as _public  # noqa: E402,F401
from tools import run_rq1c_bounded_qualification_core as _core  # noqa: E402
from tools.rq1c_qualification_guardrails import _AnswerStageBudget  # noqa: E402
from src.application.research_web_lookup_dispatch import (  # noqa: E402
    ClaimEngineDispatchWebLookupService,
)
from src.infrastructure.sqlite.database import RuntimeDatabase  # noqa: E402
from src.repositories.web_lookup_repository import WebLookupRepository  # noqa: E402

SCHEMA_VERSION = "rq1c-answer-stage-replay-v1"
DEFAULT_CASES = (
    "rq1c-numeric-uk-inflation",
    "rq1c-unverifiable-python-security",
    "rq1c-academic-primary-attention",
    "rq1c-provenance-xz",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_cases(
    manifest_path: Path, case_ids: Iterable[str]
) -> tuple[dict[str, str], ...]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = payload.get("cases")
    if not isinstance(rows, list):
        raise ValueError("holdout manifest must contain a cases list")
    by_id = {
        str(row.get("id")): row
        for row in rows
        if isinstance(row, Mapping) and row.get("id")
    }
    selected: list[dict[str, str]] = []
    for case_id in case_ids:
        row = by_id.get(case_id)
        if row is None:
            raise ValueError(f"replay case is not in the manifest: {case_id}")
        selected.append(
            {
                "id": case_id,
                "category": str(row.get("category") or ""),
                "question": str(row.get("question") or ""),
            }
        )
    if not selected:
        raise ValueError("no replay case selected")
    return tuple(selected)


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(fraction * (len(ordered) - 1) + 0.5)))
    return round(ordered[index], 3)


def _generation_outcome(
    *,
    call: Mapping[str, Any] | None,
    answer_status: str,
    answer_reason: str,
    answer_text_chars: int,
    elapsed_seconds: float,
    binding_phase: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return {
        "elapsed_seconds": round(elapsed_seconds, 3),
        "outcome": (call or {}).get("outcome") or "unknown",
        "answer_status": answer_status,
        "answer_reason": answer_reason,
        "answer_text_chars": answer_text_chars,
        "timeout_seconds": (call or {}).get("timeout_seconds"),
        "remaining_seconds": (call or {}).get("remaining_seconds"),
        "prompt_message_count": (call or {}).get("message_count"),
        "prompt_message_chars": (call or {}).get("message_chars"),
        "binding_outcome": (binding_phase or {}).get("outcome"),
        "binding_error_type": (binding_phase or {}).get("error_type"),
    }


def _answer_phases(turn: Any) -> tuple[str, str, int, Mapping[str, Any]]:
    surface = _core._production_answer_surface(turn)
    status = str(surface.get("status") or "")
    reason = str(surface.get("reason") or "")
    chars = len(str(surface.get("text") or ""))
    validation = surface.get("validation")
    phases: Mapping[str, Any] = {}
    if isinstance(validation, Mapping):
        raw = validation.get("phases")
        if isinstance(raw, Mapping):
            phases = raw
    binding = phases.get("answer_claim_binding")
    return (
        status,
        reason,
        chars,
        binding if isinstance(binding, Mapping) else {},
    )


def run_replay(
    *,
    manifest_path: Path,
    output_path: Path,
    case_ids: Iterable[str],
    repeats: int,
    answer_timeout_seconds: float,
    deadline_seconds: float,
) -> dict[str, Any]:
    load_dotenv(REPO_ROOT / ".env")
    if repeats < 1:
        raise ValueError("repeats must be >= 1")
    if answer_timeout_seconds <= 0 or deadline_seconds <= 0:
        raise ValueError("diagnostic limits must be positive")
    cases = _load_cases(manifest_path, case_ids)
    git_sha = _core._git_sha()
    if not git_sha:
        raise RuntimeError("replay requires an exact git head")
    reference_date = datetime.now(timezone.utc).date().isoformat()
    artifact: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "diagnostic_only": True,
        "qualification_evidence": False,
        "git_sha": git_sha,
        "started_at": _utc_now(),
        "completed_at": None,
        "diagnostic_limits": {
            "deadline_seconds": deadline_seconds,
            "answer_timeout_seconds": answer_timeout_seconds,
            "production_llm_timeout_seconds": 30.0,
            "note": (
                "widened only to observe the untruncated generation distribution; "
                "never a qualification or product configuration - each call still "
                "runs with min(configured, remaining)"
            ),
        },
        "repeats": repeats,
        "cases": [],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="rq1c_answer_replay_")
    try:
        for index, case in enumerate(cases, start=1):
            case_dir = Path(tmp) / case["id"]
            case_dir.mkdir(parents=True, exist_ok=True)
            database = RuntimeDatabase(case_dir / "replay.sqlite")
            repository = WebLookupRepository(database)
            service = ClaimEngineDispatchWebLookupService(
                repository,
                active_runtime_factory=_core._qualification_active_runtime_factory,
            )
            budget = _AnswerStageBudget(
                started_at=time.monotonic(),
                hard_timeout_seconds=deadline_seconds,
                answer_timeout_floor_seconds=answer_timeout_seconds,
                binding_rows_provider=lambda run: _core.research_binding_rows(run),
            )
            chat_service = _core._build_chat_service(database)
            chat_service.dependencies = replace(
                chat_service.dependencies, chat=budget.chat
            )

            run = repository.create(
                _core.WebLookupRun(
                    id=f"rq1c_{case['id']}",
                    query=case["question"],
                    stage="planned",
                    status="pending",
                    research_context=_core._active_context(reference_date),
                    max_items=5,
                )
            )
            research_started = time.monotonic()
            completed = service.execute(run.id, raise_on_error=False)
            research_seconds = round(time.monotonic() - research_started, 3)
            evidence_rows = len(_core.research_binding_rows(completed))
            source_block_chars = len(str(completed.source_block or ""))

            generations: list[dict[str, Any]] = []
            for repeat in range(1, repeats + 1):
                command = _core._production_chat_command(case=case, run=completed)
                command = replace(
                    command,
                    thread_id=f"{command.thread_id}-replay{repeat}",
                    turn_id=f"{command.turn_id}-replay{repeat}",
                )
                recorded_before = len(budget.call_records)
                generation_started = time.monotonic()
                try:
                    prepared = chat_service.start_turn(command)
                    chat_service.generate(prepared)
                    turn = chat_service.repository.get_chat_turn(prepared.turn.id)
                    status, reason, chars, binding = _answer_phases(turn)
                    outcome_call = (
                        budget.call_records[recorded_before]
                        if len(budget.call_records) > recorded_before
                        else None
                    )
                except Exception as exc:  # measurement records the failure mode
                    status, reason, chars, binding = (
                        "unavailable",
                        "production_chat_failed",
                        0,
                        {},
                    )
                    outcome_call = (
                        budget.call_records[-1]
                        if len(budget.call_records) > recorded_before
                        else None
                    )
                    reason = f"production_chat_failed:{type(exc).__name__}"
                generations.append(
                    {
                        "repeat": repeat,
                        **_generation_outcome(
                            call=outcome_call,
                            answer_status=status,
                            answer_reason=reason,
                            answer_text_chars=chars,
                            elapsed_seconds=time.monotonic() - generation_started,
                            binding_phase=binding,
                        ),
                    }
                )
                print(
                    f"[{index}/{len(cases)}] {case['id']} r{repeat}: "
                    f"{generations[-1]['outcome']} · "
                    f"{generations[-1]['elapsed_seconds']}s · "
                    f"{generations[-1]['answer_status']}",
                    flush=True,
                )

            elapsed_values = [float(item["elapsed_seconds"]) for item in generations]
            success = sum(
                1 for item in generations if item["answer_status"] == "available"
            )
            artifact["cases"].append(
                {
                    "case_id": case["id"],
                    "category": case["category"],
                    "question_sha256": hashlib.sha256(
                        case["question"].encode("utf-8")
                    ).hexdigest(),
                    "research_seconds": research_seconds,
                    "research_status": completed.status,
                    "research_stop_reason": completed.stop_reason,
                    "evidence_row_count": evidence_rows,
                    "source_block_chars": source_block_chars,
                    "generations": generations,
                    "generation_summary": {
                        "count": len(generations),
                        "available": success,
                        "unavailable": len(generations) - success,
                        "p50_seconds": _percentile(elapsed_values, 0.5),
                        "p90_seconds": _percentile(elapsed_values, 0.9),
                        "max_seconds": max(elapsed_values) if elapsed_values else None,
                    },
                }
            )
            artifact["cases"] = list(artifact["cases"])
            output_path.write_text(
                json.dumps(artifact, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    all_generations = [
        item for case in artifact["cases"] for item in case["generations"]
    ]
    elapsed_values = [float(item["elapsed_seconds"]) for item in all_generations]
    artifact["completed_at"] = _utc_now()
    artifact["summary"] = {
        "case_count": len(artifact["cases"]),
        "generation_count": len(all_generations),
        "available": sum(
            1 for item in all_generations if item["answer_status"] == "available"
        ),
        "p50_seconds": _percentile(elapsed_values, 0.5),
        "p90_seconds": _percentile(elapsed_values, 0.9),
        "max_seconds": max(elapsed_values) if elapsed_values else None,
    }
    output_path.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return artifact


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=_core.DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--cases",
        default=",".join(DEFAULT_CASES),
        help="comma separated holdout case ids",
    )
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument(
        "--answer-timeout-seconds",
        type=float,
        default=90.0,
        help="diagnostic answer timeout floor (production default is 30s)",
    )
    parser.add_argument(
        "--deadline-seconds",
        type=float,
        default=240.0,
        help="diagnostic total deadline so a natural completion can be observed",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    case_ids = [item.strip() for item in args.cases.split(",") if item.strip()]
    artifact = run_replay(
        manifest_path=args.manifest.resolve(),
        output_path=args.output.resolve(),
        case_ids=case_ids,
        repeats=args.repeats,
        answer_timeout_seconds=args.answer_timeout_seconds,
        deadline_seconds=args.deadline_seconds,
    )
    print(json.dumps(artifact["summary"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
