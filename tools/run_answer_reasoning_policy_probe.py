"""Answer reasoning policy A/B (diagnostic only, never qualification).

Background (PROJECT_STATUS §30): the answer stage runs with thinking enabled,
and the 32-character visible answer hides 1775-4067 reasoning tokens, which is
29-60s of wall clock and the source of the 30s-timeout truncation. This tool
measures, on *frozen real production inputs*, what changes when thinking is
disabled:

* ``A_production``    the real production answer path (default thinking), which
                      also yields the binding/validation truth;
* ``A_sdk_default``   the same frozen messages through the SDK with default
                      thinking (reasoning tokens become observable);
* ``B_sdk_disabled``  the same frozen messages with thinking disabled.

Quality is compared with deterministic proxies computed from the answer text and
the frozen evidence context (length, conditional/fail-closed wording, and
numeric specifics that do not appear in the evidence). Raw texts are kept in the
diagnostic artifact so a human can review them; nothing here changes product
behaviour and every artifact is ``qualification_evidence = false``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
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
from src.application.active_research_runtime import (  # noqa: E402
    ACTIVE_RESEARCH_BRIEF_KEY,
)
from src.application.research_web_lookup_dispatch import (  # noqa: E402
    ClaimEngineDispatchWebLookupService,
)
from src.infrastructure.sqlite.database import RuntimeDatabase  # noqa: E402
from src.repositories.web_lookup_repository import WebLookupRepository  # noqa: E402

SCHEMA_VERSION = "rq1c-answer-reasoning-policy-v1"
DEFAULT_CASES = (
    "rq1c-numeric-uk-inflation",
    "rq1c-provenance-xz",
    "rq1c-current-support-postgresql",
    "rq1c-historical-current-node-modules",
)
THINKING_DISABLED_BODY = {"thinking": {"type": "disabled"}}

# Fail-closed / conditional wording markers (the visible surface of a blocked
# answer). Deliberately shallow: this is a proxy, not a semantic judgement.
_CONDITIONAL_MARKERS = (
    "未能",
    "不足",
    "无法",
    "尚无",
    "不能确认",
    "insufficient",
    "cannot",
    "unable",
    "not enough",
)
_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")


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
            raise ValueError(f"policy probe case is not in the manifest: {case_id}")
        selected.append(
            {
                "id": case_id,
                "category": str(row.get("category") or ""),
                "question": str(row.get("question") or ""),
            }
        )
    if not selected:
        raise ValueError("no policy probe case selected")
    return tuple(selected)


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(fraction * (len(ordered) - 1) + 0.5)))
    return round(ordered[index], 3)


def _quality_proxy(text: str, evidence_text: str) -> dict[str, Any]:
    """Deterministic answer-quality proxies (no LLM judging)."""

    stripped = text.strip()
    answer_numbers = set(_NUMBER_RE.findall(stripped))
    evidence_numbers = set(_NUMBER_RE.findall(evidence_text))
    unsupported = sorted(answer_numbers - evidence_numbers)
    conditional = [m for m in _CONDITIONAL_MARKERS if m in stripped]
    return {
        "chars": len(stripped),
        # Sentence-ish segments: split on sentence enders only, so decimals and
        # version numbers inside a sentence are not mis-counted.
        "sentences": len(
            [item for item in re.findall(r"[^。！？!?\n]+", stripped) if item.strip()]
        ),
        "numbers": sorted(answer_numbers),
        "unsupported_numbers": unsupported,
        "unsupported_number_count": len(unsupported),
        "conditional_markers": conditional,
        "conditional_wording": bool(conditional),
        "fail_closed_ok": bool(conditional) and not unsupported,
    }


def _sdk_call(
    *,
    messages: list[dict],
    variant: str,
    thinking_disabled: bool,
    timeout_seconds: float,
) -> dict[str, Any]:
    from src import llm_client

    client = llm_client.get_client()
    model = llm_client.get_model_name(None)
    request: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": 0.7,
        "timeout": timeout_seconds,
    }
    if thinking_disabled:
        request["extra_body"] = THINKING_DISABLED_BODY
    started = time.monotonic()
    entry: dict[str, Any] = {"variant": variant}
    try:
        response = client.with_options(max_retries=0).chat.completions.create(**request)
        usage = getattr(response, "usage", None)
        details = getattr(usage, "completion_tokens_details", None)
        choices = getattr(response, "choices", None) or []
        text = str(choices[0].message.content or "") if choices else ""
        entry.update(
            {
                "outcome": "ok",
                "text": text,
                "finish_reason": choices[0].finish_reason if choices else None,
                "prompt_tokens": getattr(usage, "prompt_tokens", None),
                "completion_tokens": getattr(usage, "completion_tokens", None),
                "reasoning_tokens": getattr(details, "reasoning_tokens", None),
            }
        )
    except Exception as exc:
        entry.update({"outcome": type(exc).__name__, "text": "", "error": str(exc)[:200]})
    entry["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return entry


class _Recorder:
    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.last_messages: list[dict] | None = None

    def __call__(self, messages: list[dict], **kwargs: Any) -> str:
        self.last_messages = [dict(item) for item in messages]
        return self._inner(messages, **kwargs)


def _production_answer(
    *,
    case: Mapping[str, str],
    run: Any,
    chat_service: Any,
    budget: _AnswerStageBudget,
    suffix: str,
) -> dict[str, Any]:
    command = _core._production_chat_command(case=case, run=run)
    command = replace(
        command,
        thread_id=f"{command.thread_id}-{suffix}",
        turn_id=f"{command.turn_id}-{suffix}",
    )
    before = len(budget.call_records)
    started = time.monotonic()
    entry: dict[str, Any] = {"variant": "A_production"}
    try:
        prepared = chat_service.start_turn(command)
        chat_service.generate(prepared)
        turn = chat_service.repository.get_chat_turn(prepared.turn.id)
        surface = _core._production_answer_surface(turn)
        entry.update(
            {
                "outcome": "ok",
                "text": str(surface.get("text") or ""),
                "answer_status": surface.get("status"),
                "answer_reason": surface.get("reason"),
                "binding": (
                    (surface.get("validation") or {}).get("phases") or {}
                ).get("answer_claim_binding"),
            }
        )
    except Exception as exc:
        entry.update(
            {
                "outcome": type(exc).__name__,
                "text": "",
                "answer_status": "unavailable",
                "answer_reason": "production_chat_failed",
            }
        )
    entry["elapsed_seconds"] = round(time.monotonic() - started, 3)
    if len(budget.call_records) > before:
        entry["call"] = budget.call_records[before]
    return entry


def run_probe(
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
    cases = _load_cases(manifest_path, case_ids)
    git_sha = _core._git_sha()
    if not git_sha:
        raise RuntimeError("policy probe requires an exact git head")
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
        },
        "variants": ["A_production", "A_sdk_default", "B_sdk_disabled"],
        "cases": [],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="rq1c_answer_policy_")
    categories: dict[str, int] = {"block": 0, "partial": 0, "pass": 0}
    try:
        for index, case in enumerate(cases, start=1):
            case_dir = Path(tmp) / case["id"]
            case_dir.mkdir(parents=True, exist_ok=True)
            database = RuntimeDatabase(case_dir / "policy.sqlite")
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
            recorder = _Recorder(budget.chat)
            chat_service = _core._build_chat_service(database)
            chat_service.dependencies = replace(chat_service.dependencies, chat=recorder)

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
            context = completed.research_context
            brief = context.get(ACTIVE_RESEARCH_BRIEF_KEY) or {}
            gate_status = str((brief or {}).get("gate_status") or "block")
            category = (
                "pass"
                if gate_status == "pass"
                else "partial"
                if gate_status == "partial"
                else "block"
            )
            categories[category] = categories.get(category, 0) + 1

            production = _production_answer(
                case=case,
                run=completed,
                chat_service=chat_service,
                budget=budget,
                suffix=f"policy{index}",
            )
            messages = recorder.last_messages or []
            evidence_text = str(completed.source_block or "")
            variants: dict[str, list[dict[str, Any]]] = {
                "A_production": [production],
                "A_sdk_default": [],
                "B_sdk_disabled": [],
            }
            for variant, disabled in (
                ("A_sdk_default", False),
                ("B_sdk_disabled", True),
            ):
                for repeat in range(1, repeats + 1):
                    entry = _sdk_call(
                        messages=messages,
                        variant=variant,
                        thinking_disabled=disabled,
                        timeout_seconds=answer_timeout_seconds,
                    )
                    entry["repeat"] = repeat
                    entry["quality"] = _quality_proxy(
                        str(entry.get("text") or ""), evidence_text
                    )
                    variants[variant].append(entry)
                    print(
                        f"[{index}/{len(cases)}] {case['id']} {variant} r{repeat}: "
                        f"{entry['outcome']} · {entry['elapsed_seconds']}s · "
                        f"reasoning={entry.get('reasoning_tokens')}",
                        flush=True,
                    )
            production["quality"] = _quality_proxy(
                str(production.get("text") or ""), evidence_text
            )
            variants["A_production"] = [production]

            def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
                elapsed = [
                    float(item["elapsed_seconds"])
                    for item in rows
                    if item.get("outcome") == "ok"
                ]
                reasoning = [
                    int(item["reasoning_tokens"])
                    for item in rows
                    if isinstance(item.get("reasoning_tokens"), int)
                ]
                texts = [str(item.get("text") or "") for item in rows]
                return {
                    "count": len(rows),
                    "ok": sum(1 for item in rows if item.get("outcome") == "ok"),
                    "p50_seconds": _percentile(elapsed, 0.5),
                    "p90_seconds": _percentile(elapsed, 0.9),
                    "max_seconds": max(elapsed) if elapsed else None,
                    "reasoning_tokens": reasoning or None,
                    "chars": [len(text) for text in texts],
                }

            artifact["cases"].append(
                {
                    "case_id": case["id"],
                    "category_hint": case["category"],
                    "gate_status": gate_status,
                    "policy_category": category,
                    "research_seconds": research_seconds,
                    "research_status": completed.status,
                    "evidence_row_count": len(_core.research_binding_rows(completed)),
                    "source_block_chars": len(evidence_text),
                    "prompt_sha256": (
                        hashlib.sha256(
                            json.dumps(messages, sort_keys=True).encode("utf-8")
                        ).hexdigest()
                        if messages
                        else None
                    ),
                    "prompt_message_chars": sum(
                        len(str(item.get("content") or "")) for item in messages
                    ),
                    "variants": variants,
                    "summaries": {
                        name: _summary(rows) for name, rows in variants.items()
                    },
                }
            )
            output_path.write_text(
                json.dumps(artifact, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    artifact["completed_at"] = _utc_now()
    artifact["policy_categories"] = categories
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
    parser.add_argument("--repeats", type=int, default=3)
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
        repeats=args.repeats,
        answer_timeout_seconds=args.answer_timeout_seconds,
        deadline_seconds=args.deadline_seconds,
    )
    summary = {
        "policy_categories": artifact["policy_categories"],
        "cases": [
            {
                "case_id": case["case_id"],
                "policy_category": case["policy_category"],
                "A_production": case["summaries"]["A_production"],
                "A_sdk_default": case["summaries"]["A_sdk_default"],
                "B_sdk_disabled": case["summaries"]["B_sdk_disabled"],
            }
            for case in artifact["cases"]
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
