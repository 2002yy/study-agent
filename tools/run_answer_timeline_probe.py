"""Timeline-position and reasoning-token probe for the answer stage.

Open question (PROJECT_STATUS §29): the *same* production answer generation is
12/12 successful in a replay with a 30s cap, yet in-situ runs hit the 30s
request timeout at 30.11s in 2/4 (and 7/12 in an earlier batch), with essentially
equal prompt sizes. This tool exists only to explain that difference.

Modes:

* ``position``      one real research run, then the same frozen answer input is
                    generated at three timeline positions (immediate, +delay,
                    +2x delay) to test a time/position effect.
* ``insitu-replay``  one real in-situ case run (production limits), then the same
                    frozen input is replayed twice immediately in the same
                    process, to test "in-situ slow, replay fast" directly.
* ``thinking``      on the frozen production prompt, compare the production call
                    against the same request with 0 extra_body (baseline) and
                    with thinking disabled, using the SDK directly, so hidden
                    reasoning tokens can be observed.

Nothing here changes product behaviour: the production client, prompts, budgets
and timeouts are untouched, and every artifact is diagnostic-only
(``qualification_evidence = false``). The reasoning probe talks to the SDK
directly on purpose - it must not become a product code path.
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
from tools.rq1c_qualification_guardrails import (  # noqa: E402
    _AnswerStageBudget,
    make_guarded_run_case,
)
from src.application.research_web_lookup_dispatch import (  # noqa: E402
    ClaimEngineDispatchWebLookupService,
)
from src.infrastructure.sqlite.database import RuntimeDatabase  # noqa: E402
from src.repositories.web_lookup_repository import WebLookupRepository  # noqa: E402

SCHEMA_VERSION = "rq1c-answer-timeline-probe-v1"
DEFAULT_CASES = (
    "rq1c-academic-primary-attention",
    "rq1c-provenance-xz",
)
THINKING_DISABLED_BODY = {"thinking": {"type": "disabled"}}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_cases(manifest_path: Path, case_ids: Iterable[str]) -> tuple[dict[str, str], ...]:
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
            raise ValueError(f"probe case is not in the manifest: {case_id}")
        selected.append(
            {
                "id": case_id,
                "category": str(row.get("category") or ""),
                "question": str(row.get("question") or ""),
            }
        )
    if not selected:
        raise ValueError("no probe case selected")
    return tuple(selected)


class _MessageRecorder:
    """Wrap a production chat callable and keep the last messages in memory."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.last_messages: list[dict] | None = None

    def __call__(self, messages: list[dict], **kwargs: Any) -> str:
        self.last_messages = [dict(item) for item in messages]
        return self._inner(messages, **kwargs)


def _call_record(
    *,
    budget: _AnswerStageBudget,
    before: int,
    elapsed_seconds: float,
    answer_status: str,
    answer_reason: str,
    answer_text_chars: int,
) -> dict[str, Any]:
    call: Mapping[str, Any] = {}
    if len(budget.call_records) > before:
        call = budget.call_records[before]
    return {
        "elapsed_seconds": round(elapsed_seconds, 3),
        "outcome": call.get("outcome") or "unknown",
        "timeout_seconds": call.get("timeout_seconds"),
        "remaining_at_dispatch_seconds": call.get("remaining_at_dispatch_seconds"),
        "remaining_after_call_seconds": call.get("remaining_after_call_seconds"),
        "request_max_retries": call.get("request_max_retries"),
        "prompt_message_count": call.get("message_count"),
        "prompt_message_chars": call.get("message_chars"),
        "answer_status": answer_status,
        "answer_reason": answer_reason,
        "answer_text_chars": answer_text_chars,
    }


def _generate_once(
    *,
    case: Mapping[str, str],
    run: Any,
    chat_service: Any,
    budget: _AnswerStageBudget,
    suffix: str,
    recorder: _MessageRecorder,
) -> dict[str, Any]:
    command = _core._production_chat_command(case=case, run=run)
    command = replace(
        command,
        thread_id=f"{command.thread_id}-{suffix}",
        turn_id=f"{command.turn_id}-{suffix}",
    )
    before = len(budget.call_records)
    started = time.monotonic()
    try:
        prepared = chat_service.start_turn(command)
        chat_service.generate(prepared)
        turn = chat_service.repository.get_chat_turn(prepared.turn.id)
        surface = _core._production_answer_surface(turn)
        status = str(surface.get("status") or "")
        reason = str(surface.get("reason") or "")
        chars = len(str(surface.get("text") or ""))
    except Exception as exc:
        status, reason, chars = "unavailable", f"production_chat_failed:{type(exc).__name__}", 0
    return _call_record(
        budget=budget,
        before=before,
        elapsed_seconds=time.monotonic() - started,
        answer_status=status,
        answer_reason=reason,
        answer_text_chars=chars,
    )


def _reasoning_probe(
    *,
    messages: list[dict],
    repeats: int,
    timeout_seconds: float,
) -> list[dict[str, Any]]:
    """Compare production settings against thinking-disabled, via the SDK.

    Diagnostic only: the SDK is used directly so hidden reasoning tokens become
    observable. No product code path is touched.
    """

    from src import llm_client

    client = llm_client.get_client()
    # Diagnostics measure the model the product answer path uses (flash).
    model = llm_client.get_model_name("flash")
    results: list[dict[str, Any]] = []
    for variant, extra_body in (
        ("production_default", None),
        ("thinking_disabled", THINKING_DISABLED_BODY),
    ):
        for repeat in range(1, repeats + 1):
            started = time.monotonic()
            entry: dict[str, Any] = {"variant": variant, "repeat": repeat}
            try:
                request: dict[str, Any] = {
                    "model": model,
                    "messages": messages,
                    "temperature": 0.7,
                    "timeout": timeout_seconds,
                }
                if extra_body is not None:
                    request["extra_body"] = extra_body
                response = client.with_options(max_retries=0).chat.completions.create(
                    **request
                )
                usage = getattr(response, "usage", None)
                details = getattr(usage, "completion_tokens_details", None)
                entry.update(
                    {
                        "outcome": "ok",
                        "finish_reason": (
                            response.choices[0].finish_reason
                            if getattr(response, "choices", None)
                            else None
                        ),
                        "answer_text_chars": len(
                            str(
                                response.choices[0].message.content or ""
                            )
                            if getattr(response, "choices", None)
                            else ""
                        ),
                        "prompt_tokens": getattr(usage, "prompt_tokens", None),
                        "completion_tokens": getattr(usage, "completion_tokens", None),
                        "reasoning_tokens": getattr(
                            details, "reasoning_tokens", None
                        ),
                    }
                )
            except Exception as exc:
                entry.update(
                    {"outcome": type(exc).__name__, "error": str(exc)[:200]}
                )
            entry["elapsed_seconds"] = round(time.monotonic() - started, 3)
            results.append(entry)
            print(
                f"  thinking[{variant} r{repeat}]: {entry['outcome']} · "
                f"{entry['elapsed_seconds']}s · reasoning={entry.get('reasoning_tokens')}",
                flush=True,
            )
    return results


def run_probe(
    *,
    manifest_path: Path,
    output_path: Path,
    case_ids: Iterable[str],
    mode: str,
    repeats: int,
    delay_seconds: float,
    answer_timeout_seconds: float,
    deadline_seconds: float,
) -> dict[str, Any]:
    load_dotenv(REPO_ROOT / ".env")
    if repeats < 1:
        raise ValueError("repeats must be >= 1")
    cases = _load_cases(manifest_path, case_ids)
    git_sha = _core._git_sha()
    if not git_sha:
        raise RuntimeError("probe requires an exact git head")
    reference_date = datetime.now(timezone.utc).date().isoformat()
    artifact: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "diagnostic_only": True,
        "qualification_evidence": False,
        "git_sha": git_sha,
        "started_at": _utc_now(),
        "completed_at": None,
        "mode": mode,
        "diagnostic_limits": {
            "deadline_seconds": deadline_seconds,
            "answer_timeout_seconds": answer_timeout_seconds,
        },
        "delay_seconds": delay_seconds,
        "cases": [],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="rq1c_timeline_")
    try:
        for index, case in enumerate(cases, start=1):
            case_dir = Path(tmp) / case["id"]
            case_dir.mkdir(parents=True, exist_ok=True)
            database = RuntimeDatabase(case_dir / "probe.sqlite")
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
            recorder = _MessageRecorder(budget.chat)
            chat_service = _core._build_chat_service(database)
            chat_service.dependencies = replace(
                chat_service.dependencies, chat=recorder
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

            case_record: dict[str, Any] = {
                "case_id": case["id"],
                "category": case["category"],
                "research_seconds": research_seconds,
                "research_status": completed.status,
                "evidence_row_count": len(_core.research_binding_rows(completed)),
                "source_block_chars": len(str(completed.source_block or "")),
                "generations": [],
            }

            if mode == "insitu-replay":
                guarded = make_guarded_run_case(
                    raw_run_case=_core.raw_run_case,
                    build_chat_service=_core._build_chat_service,
                    binding_rows_provider=_core.research_binding_rows,
                    answer_stage_model_calls=_core._answer_stage_model_calls,
                    exact_git_check=_core._git_sha,
                )
                guarded_database = RuntimeDatabase(case_dir / "insitu.sqlite")
                guarded_repository = WebLookupRepository(guarded_database)
                guarded_service = ClaimEngineDispatchWebLookupService(
                    guarded_repository,
                    active_runtime_factory=_core._qualification_active_runtime_factory,
                )
                guarded_chat = _core._build_chat_service(guarded_database)
                started = time.monotonic()
                record = guarded(
                    case=case,
                    repository=guarded_repository,
                    service=guarded_service,
                    chat_service=guarded_chat,
                    reference_date=reference_date,
                )
                breakdown = record.get("finalization_breakdown") or {}
                call = (breakdown.get("answer_stage_calls") or [{}])[0]
                case_record["generations"].append(
                    {
                        "position": "in_situ",
                        "elapsed_seconds": breakdown.get("answer_generation_seconds"),
                        "outcome": call.get("outcome"),
                        "timeout_seconds": call.get("timeout_seconds"),
                        "remaining_at_dispatch_seconds": call.get(
                            "remaining_at_dispatch_seconds"
                        ),
                        "request_max_retries": call.get("request_max_retries"),
                        "prompt_message_count": call.get("message_count"),
                        "prompt_message_chars": call.get("message_chars"),
                        "answer_status": (record.get("answer") or {}).get("status"),
                        "answer_reason": (record.get("answer") or {}).get("reason"),
                        "answer_text_chars": len(
                            str((record.get("answer") or {}).get("text") or "")
                        ),
                        "case_total_seconds": round(time.monotonic() - started, 3),
                    }
                )
                frozen_run = guarded_repository.get(f"rq1c_{case['id']}")
                if frozen_run is None:
                    raise RuntimeError("in-situ probe lost its persisted run")
                for repeat in range(1, repeats + 1):
                    case_record["generations"].append(
                        {
                            "position": f"immediate_replay_{repeat}",
                            **_generate_once(
                                case=case,
                                run=frozen_run,
                                chat_service=chat_service,
                                budget=budget,
                                suffix=f"replay{repeat}",
                                recorder=recorder,
                            ),
                        }
                    )
            else:
                for position in ("immediate", "delayed", "delayed2"):
                    case_record["generations"].append(
                        {
                            "position": position,
                            **_generate_once(
                                case=case,
                                run=completed,
                                chat_service=chat_service,
                                budget=budget,
                                suffix=f"{position}{index}",
                                recorder=recorder,
                            ),
                        }
                    )
                    if position != "delayed2" and delay_seconds > 0:
                        time.sleep(delay_seconds)

            if recorder.last_messages:
                case_record["prompt_sha256"] = hashlib.sha256(
                    json.dumps(recorder.last_messages, sort_keys=True).encode("utf-8")
                ).hexdigest()
                if mode == "thinking":
                    case_record["reasoning_probe"] = _reasoning_probe(
                        messages=recorder.last_messages,
                        repeats=repeats,
                        timeout_seconds=answer_timeout_seconds,
                    )
            artifact["cases"].append(case_record)
            output_path.write_text(
                json.dumps(artifact, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(
                f"[{index}/{len(cases)}] {case['id']} mode={mode} done",
                flush=True,
            )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    artifact["completed_at"] = _utc_now()
    output_path.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return artifact


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=_core.DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cases", default=",".join(DEFAULT_CASES))
    parser.add_argument(
        "--mode",
        choices=("position", "insitu-replay", "thinking"),
        default="position",
    )
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--delay-seconds", type=float, default=25.0)
    parser.add_argument("--answer-timeout-seconds", type=float, default=90.0)
    parser.add_argument("--deadline-seconds", type=float, default=240.0)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    case_ids = [item.strip() for item in args.cases.split(",") if item.strip()]
    artifact = run_probe(
        manifest_path=args.manifest.resolve(),
        output_path=args.output.resolve(),
        case_ids=case_ids,
        mode=args.mode,
        repeats=args.repeats,
        delay_seconds=args.delay_seconds,
        answer_timeout_seconds=args.answer_timeout_seconds,
        deadline_seconds=args.deadline_seconds,
    )
    print(
        json.dumps(
            {
                "mode": artifact["mode"],
                "cases": [
                    {
                        "case_id": case["case_id"],
                        "generations": [
                            {
                                "position": item.get("position"),
                                "elapsed_seconds": item.get("elapsed_seconds"),
                                "outcome": item.get("outcome"),
                                "reasoning_tokens": item.get("reasoning_tokens"),
                            }
                            for item in case["generations"]
                        ],
                    }
                    for case in artifact["cases"]
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
