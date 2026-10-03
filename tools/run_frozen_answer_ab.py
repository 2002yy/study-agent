"""Frozen-artifact PARTIAL/PASS answer A/B - with a refusal path.

PROJECT_STATUS §31 asked for a real PARTIAL artifact A/B (default thinking vs
thinking disabled, judged on supported-claim retention, unsupported leakage,
uncertainty preservation and binding outcome). Inspecting every historical
qualification artifact showed why that experiment cannot run yet:

    across 6 artifacts x 12 cases (~70 real case runs), the answer stage never
    produced a substantive answer - every published text was the 32-character
    fail-closed copy with answer_claim_binding rejected/missing_evidence_brief,
    including the three gate=partial runs, because their eligible evidence rows
    were all relation="lead" while research_binding_rows only accepts "supports".

So this tool does the honest thing instead of faking a PARTIAL A/B:

* it classifies a frozen artifact case by its *answer input* (are there binding
  rows at all?), which is the same predicate the production release gate uses;
* for ``blocked_no_binding_rows`` it records the classification and refuses to
  run the A/B unless explicitly forced (``--allow-blocked-replay``), because
  that would only re-measure the BLOCK policy that already shipped;
* for a future substantive artifact it reconstructs the production answer input
  from the stored case (question, eligible evidence rows, bounded source rows),
  runs both arms through the real production chat service and reports the four
  quality criteria plus binding outcome.

Fidelity note: the artifact stores bounded source rows, not page bodies, so a
reconstructed ``web_context`` cannot be byte-identical to the original run. The
artifact records that explicitly and marks such a run as diagnostic, never
qualification evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import time
from collections.abc import Iterable, Mapping
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

from tools import run_rq1c_bounded_qualification as _public  # noqa: E402,F401
from tools import run_rq1c_bounded_qualification_core as _core  # noqa: E402
from tools.run_answer_reasoning_policy_probe import _quality_proxy  # noqa: E402
from src.application.policy_chat_service import PolicyChatCommand  # noqa: E402
from src.infrastructure.sqlite.database import RuntimeDatabase  # noqa: E402

SCHEMA_VERSION = "rq1c-frozen-answer-ab-v1"
THINKING_DISABLED_EXTRA_BODY = {"thinking": {"type": "disabled"}}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_frozen_case(artifact_path: Path, case_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    data = json.loads(artifact_path.read_text(encoding="utf-8"))
    cases = data.get("cases")
    if not isinstance(cases, list):
        raise ValueError("artifact must contain a cases list")
    case = next(
        (item for item in cases if str(item.get("case_id")) == case_id),
        None,
    )
    if case is None:
        raise ValueError(f"case not found in artifact: {case_id}")
    return data, case


def classify_answer_input(case: Mapping[str, Any]) -> dict[str, Any]:
    """Classify the case by the binding rows the release gate would see."""

    brief_raw = case.get("brief")
    brief: Mapping[str, Any] = brief_raw if isinstance(brief_raw, Mapping) else {}
    eligible_raw = brief.get("eligible_evidence")
    eligible: list[Any] = eligible_raw if isinstance(eligible_raw, list) else []
    binding_rows = [
        row
        for row in eligible
        if isinstance(row, Mapping) and str(row.get("relation") or "") == "supports"
    ]
    leads = [
        row
        for row in eligible
        if isinstance(row, Mapping) and str(row.get("relation") or "") != "supports"
    ]
    gate_raw = case.get("gate")
    gate: Mapping[str, Any] = gate_raw if isinstance(gate_raw, Mapping) else {}
    answer_raw = case.get("answer")
    answer: Mapping[str, Any] = answer_raw if isinstance(answer_raw, Mapping) else {}
    validation_raw = answer.get("validation")
    validation: Mapping[str, Any] = (
        validation_raw if isinstance(validation_raw, Mapping) else {}
    )
    phases_raw = validation.get("phases")
    phases: Mapping[str, Any] = phases_raw if isinstance(phases_raw, Mapping) else {}
    binding_raw = phases.get("answer_claim_binding")
    binding: Mapping[str, Any] = binding_raw if isinstance(binding_raw, Mapping) else {}
    return {
        "gate_status": gate.get("status"),
        "eligible_evidence_count": len(eligible),
        "binding_row_count": len(binding_rows),
        "lead_row_count": len(leads),
        "answer_input_class": "substantive" if binding_rows else "blocked_no_binding_rows",
        "published_answer_chars": len(str(answer.get("text") or "")),
        "binding_outcome": binding.get("outcome"),
    }


def _reconstruct_web_context(case: Mapping[str, Any]) -> tuple[str, bool]:
    """Best-effort source block from bounded stored rows (never byte-identical)."""

    sources = case.get("sources")
    if not isinstance(sources, list):
        return "", False
    lines: list[str] = []
    for row in sources:
        if not isinstance(row, Mapping):
            continue
        title = str(row.get("title") or "").strip()
        url = str(row.get("url") or "").strip()
        role = str(row.get("source_role") or "").strip()
        if not url:
            continue
        lines.append(f"- {title or url} ({role or 'unknown'}) {url}")
    return "\n".join(lines), bool(lines)


def _sources_snapshot(case: Mapping[str, Any]) -> dict[str, Any]:
    sources = case.get("sources")
    count = len(sources) if isinstance(sources, list) else 0
    return {"run_id": "frozen_artifact", "source_count": count}


def _production_ab(
    *,
    case: Mapping[str, Any],
    repeats: int,
    answer_timeout_seconds: float,
    deadline_seconds: float,
    arm_extra_body: dict[str, dict[str, str]] | None,
) -> list[dict[str, Any]]:
    """Run one arm through the real production chat service."""

    from tools.rq1c_qualification_guardrails import _AnswerStageBudget

    brief_raw = case.get("brief")
    brief: Mapping[str, Any] = brief_raw if isinstance(brief_raw, Mapping) else {}
    eligible_raw = brief.get("eligible_evidence")
    rows: list[dict[str, Any]] = [
        dict(row)
        for row in (eligible_raw if isinstance(eligible_raw, list) else [])
        if isinstance(row, Mapping)
    ]
    web_context, _ = _reconstruct_web_context(case)
    question = str(case.get("question") or "").strip()
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="rq1c_frozen_ab_") as tmp:
        database = RuntimeDatabase(Path(tmp) / "frozen.sqlite")
        budget = _AnswerStageBudget(
            started_at=time.monotonic(),
            hard_timeout_seconds=deadline_seconds,
            answer_timeout_floor_seconds=answer_timeout_seconds,
            binding_rows_provider=lambda run: rows,
        )
        chat_service = _core._build_chat_service(database)

        def arm_chat(messages: list[dict], **kwargs: Any) -> str:
            if kwargs.get("task_name") == "single_chat" and arm_extra_body is not None:
                kwargs["extra_body"] = arm_extra_body
            return budget.chat(messages, **kwargs)

        chat_service.dependencies = replace(chat_service.dependencies, chat=arm_chat)
        for repeat in range(1, repeats + 1):
            command = PolicyChatCommand(
                user_input=question,
                thread_id=f"frozen-thread-{case['case_id']}-r{repeat}",
                turn_id=f"frozen-turn-{case['case_id']}-r{repeat}",
                web_context=web_context,
                web_context_run_id="frozen_artifact",
                web_policy="auto",
                cloud_context_policy="question_only",
                memory_policy="off",
                rag_enabled=False,
                task_intent="research",
                research_sources=_sources_snapshot(case),
                answer_validation={"evidence_rows": rows, "allowed_attempts": 1},
            )
            started = time.monotonic()
            entry: dict[str, Any] = {"repeat": repeat}
            try:
                prepared = chat_service.start_turn(command)
                reply = chat_service.generate(prepared)
                turn = chat_service.repository.get_chat_turn(prepared.turn.id)
                validation = (
                    ((turn.rag_snapshot or {}).get("answer_validation_audit") or {})
                    .get("phases", {})
                    if turn is not None
                    else {}
                )
                entry.update(
                    {
                        "outcome": "ok",
                        "text": reply,
                        "binding_outcome": (validation.get("answer_claim_binding") or {}).get(
                            "outcome"
                        ),
                        "binding_error_type": (
                            validation.get("answer_claim_binding") or {}
                        ).get("error_type"),
                    }
                )
            except Exception as exc:
                entry.update(
                    {"outcome": type(exc).__name__, "text": "", "binding_outcome": None}
                )
            entry["elapsed_seconds"] = round(time.monotonic() - started, 3)
            entry["quality"] = _quality_proxy(entry["text"], web_context + json.dumps(rows))
            results.append(entry)
    return results


def run_ab(
    *,
    artifact_path: Path,
    case_id: str,
    output_path: Path,
    repeats: int,
    answer_timeout_seconds: float,
    deadline_seconds: float,
    allow_blocked_replay: bool,
) -> dict[str, Any]:
    load_dotenv(REPO_ROOT / ".env")
    if repeats < 1:
        raise ValueError("repeats must be >= 1")
    data, case = load_frozen_case(artifact_path, case_id)
    classification = classify_answer_input(case)
    artifact: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "diagnostic_only": True,
        "qualification_evidence": False,
        "started_at": _utc_now(),
        "completed_at": None,
        "frozen_input": {
            "artifact_path": str(artifact_path).replace("\\", "/"),
            "artifact_sha256": hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
            "artifact_git_sha": str(data.get("git_sha") or ""),
            "case_id": case_id,
            "question_sha256": hashlib.sha256(
                str(case.get("question") or "").encode("utf-8")
            ).hexdigest(),
        },
        "classification": classification,
        "web_context_source": "reconstructed_from_bounded_sources",
        "web_context_fidelity_note": (
            "the artifact stores bounded source rows, not page bodies, so a "
            "reconstructed web_context is not byte-identical to the original run; "
            "quality comparisons are diagnostic, never qualification evidence"
        ),
        "repeats": repeats,
        "arms": {},
        "status": "",
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if classification["answer_input_class"] != "substantive" and not allow_blocked_replay:
        artifact["status"] = "refused_not_substantive"
        artifact["refusal_reason"] = (
            "no eligible evidence row with relation='supports' exists, so the "
            "release gate would replace any generated text with the fail-closed "
            "copy; running an A/B here would only re-measure the BLOCK policy"
        )
        artifact["completed_at"] = _utc_now()
        output_path.write_text(
            json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return artifact

    artifact["arms"]["A_default_thinking"] = _production_ab(
        case=case,
        repeats=repeats,
        answer_timeout_seconds=answer_timeout_seconds,
        deadline_seconds=deadline_seconds,
        arm_extra_body=None,
    )
    artifact["arms"]["B_thinking_disabled"] = _production_ab(
        case=case,
        repeats=repeats,
        answer_timeout_seconds=answer_timeout_seconds,
        deadline_seconds=deadline_seconds,
        arm_extra_body=THINKING_DISABLED_EXTRA_BODY,
    )
    artifact["status"] = "completed"
    artifact["completed_at"] = _utc_now()
    output_path.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return artifact


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--answer-timeout-seconds", type=float, default=90.0)
    parser.add_argument("--deadline-seconds", type=float, default=240.0)
    parser.add_argument(
        "--allow-blocked-replay",
        action="store_true",
        help="force the A/B even when there are no binding rows (diagnostic only)",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    artifact = run_ab(
        artifact_path=args.artifact.resolve(),
        case_id=args.case_id,
        output_path=args.output.resolve(),
        repeats=args.repeats,
        answer_timeout_seconds=args.answer_timeout_seconds,
        deadline_seconds=args.deadline_seconds,
        allow_blocked_replay=args.allow_blocked_replay,
    )
    print(
        json.dumps(
            {
                "status": artifact["status"],
                "classification": artifact["classification"],
                "refusal_reason": artifact.get("refusal_reason"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
