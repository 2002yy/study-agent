"""§40 Gate-pass answer formation probe: freeze the answer call, replay it.

Two modes (both diagnostic-only; the production default path is untouched):

``capture`` runs the Node case on the raw driver with the §38b/§39 diagnostic
flags (model selection + atomic routing), wraps the chat dependency exactly
where the qualification guard wraps it, and records the answer-stage request:
messages, kwargs (timeout / profile / retries / thinking extra_body) and the
raw reply (chars, sha256, excerpt, exception type, elapsed ms). The artifact
also carries claims/brief/sources so a gate-pass state is identifiable.

``replay`` takes a captured answer call and re-runs it N times with the same
messages, recording the diagnostics contract from the plan
(model/status/elapsed/thinking/raw chars/candidate sha/publish decision) and
classifying the empty-answer mechanism:

    A model_empty      completed call that honestly returned an empty string
    B parse_loss       raw text present but the candidate came out empty
    C call_unavailable timeout / exception / attempts exhausted

Optional ``--policy`` selects which generation policy to replay:
``captured`` (default), ``thinking_off`` (BLOCK's bounded config) or ``both``
for the single-variable A/B on the same frozen input.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

SCHEMA_VERSION = "answer-formation-probe-v1"
DEFAULT_CASE = "rq1c-historical-current-node-modules"
THINKING_OFF_EXTRA_BODY: dict[str, Any] = {"thinking": {"type": "disabled"}}
MESSAGE_CAP = 16000


def _bounded_messages(messages: Any) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for message in messages if isinstance(messages, list) else []:
        if not isinstance(message, Mapping):
            continue
        rows.append(
            {
                "role": str(message.get("role") or ""),
                "content": str(message.get("content") or "")[:MESSAGE_CAP],
            }
        )
    return rows[:8]


def _bounded_kwargs(kwargs: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {
        "temperature",
        "model_profile",
        "max_tokens",
        "timeout",
        "response_format",
        "provider_profile",
        "task_name",
        "request_max_retries",
        "extra_body",
    }
    return {
        key: value
        for key, value in kwargs.items()
        if key in allowed and isinstance(value, (str, int, float, bool, type(None), dict))
    }


def classify_reply_outcome(record: Mapping[str, Any]) -> str:
    """A/B/C classification for one answer attempt."""

    exception_type = str(record.get("exception_type") or "")
    if exception_type:
        return "C_call_unavailable"
    if not bool(record.get("completed")):
        return "C_call_unavailable"
    reply_chars = int(record.get("reply_chars") or 0)
    candidate_chars = int(record.get("candidate_chars", reply_chars) or 0)
    if reply_chars == 0:
        return "A_model_empty"
    if candidate_chars == 0:
        return "B_parse_loss"
    return "ok"


def capture_chat_records(artifact: Mapping[str, Any]) -> list[Any]:
    records = artifact.get("answer_calls")
    return [row for row in records if isinstance(row, Mapping)] if isinstance(records, list) else []


def replay(
    call: Mapping[str, Any],
    *,
    chat_fn: Callable[..., str],
    runs: int,
    policy: str = "captured",
) -> list[dict[str, Any]]:
    """Replay one captured answer call; returns per-run diagnostics."""

    messages = _bounded_messages(call.get("messages"))
    captured_kwargs = dict(call.get("kwargs") or {})
    results: list[dict[str, Any]] = []
    for index in range(max(1, int(runs))):
        kwargs = dict(captured_kwargs)
        if policy == "thinking_off":
            kwargs["extra_body"] = dict(THINKING_OFF_EXTRA_BODY)
        elif policy == "captured":
            pass
        else:
            raise ValueError(f"unknown replay policy: {policy}")
        started = time.monotonic()
        record: dict[str, Any] = {
            "run_index": index + 1,
            "policy": policy,
            "model_profile": str(kwargs.get("model_profile") or ""),
            "provider_profile": str(kwargs.get("provider_profile") or ""),
            "task_name": str(kwargs.get("task_name") or ""),
            "timeout_seconds": kwargs.get("timeout"),
            "request_max_retries": kwargs.get("request_max_retries"),
            "thinking_mode": "off" if "extra_body" in kwargs else "on",
            "message_count": len(messages),
            "message_chars": sum(len(item["content"]) for item in messages),
            "completed": False,
        }
        try:
            reply = chat_fn(messages, **kwargs)
        except Exception as exc:  # diagnostics never fatal
            record["exception_type"] = type(exc).__name__
            record["exception_message"] = str(exc)[:300]
            record["elapsed_ms"] = int((time.monotonic() - started) * 1000)
            record["reply_chars"] = 0
            record["candidate_chars"] = 0
            record["candidate_sha256"] = hashlib.sha256(b"").hexdigest()
            record["publish_decision"] = "fail_closed_empty_candidate"
            record["classification"] = classify_reply_outcome(record)
            results.append(record)
            continue
        reply_text = str(reply or "")
        record["completed"] = True
        record["elapsed_ms"] = int((time.monotonic() - started) * 1000)
        record["raw_response_present"] = bool(reply_text)
        record["raw_response_chars"] = len(reply_text)
        record["reply_chars"] = len(reply_text)
        record["candidate_chars"] = len(reply_text)
        record["candidate_sha256"] = hashlib.sha256(reply_text.encode("utf-8")).hexdigest()
        record["reply_excerpt"] = reply_text[:600]
        record["candidate_text"] = reply_text[:4000]
        record["publish_decision"] = (
            "publish_candidate" if reply_text else "fail_closed_empty_candidate"
        )
        record["classification"] = classify_reply_outcome(record)
        results.append(record)
    return results


def summarize_attempts(attempts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    total = len(attempts)
    if total == 0:
        return {"attempts": 0}
    non_empty = sum(1 for row in attempts if int(row.get("candidate_chars") or 0) > 0)
    ok = sum(1 for row in attempts if row.get("classification") == "ok")
    latencies = sorted(int(row.get("elapsed_ms") or 0) for row in attempts)
    return {
        "attempts": total,
        "classification_counts": {
            key: sum(1 for row in attempts if row.get("classification") == key)
            for key in sorted({str(row.get("classification")) for row in attempts})
        },
        "non_empty_candidate_rate": round(non_empty / total, 3),
        "substantive_answer_rate": round(ok / total, 3),
        "fail_closed_rate": round((total - non_empty) / total, 3),
        "latency_ms_p50": latencies[len(latencies) // 2],
        "latency_ms_max": latencies[-1],
    }


def run_capture(
    *,
    manifest_path: Path,
    output_path: Path,
    case_id: str,
) -> dict[str, Any]:
    """One raw-driver run that captures every chat-dependency call."""

    from dataclasses import replace

    import hashlib as _hashlib

    from src.llm_client import chat as production_chat
    from src.infrastructure.sqlite.database import RuntimeDatabase
    from src.repositories.web_lookup_repository import WebLookupRepository
    from tools import run_rq1c_bounded_qualification as _public  # noqa: F401
    from tools import run_rq1c_bounded_qualification_core as _core

    import tempfile

    case = _load_case(manifest_path, case_id)
    captured: list[dict[str, Any]] = []

    def capture_chat(messages: list[dict], **kwargs: Any) -> str:
        started = time.monotonic()
        record: dict[str, Any] = {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "messages": _bounded_messages(messages),
            "kwargs": _bounded_kwargs(kwargs),
        }
        try:
            reply = production_chat(messages, **kwargs)
        except Exception as exc:
            record["exception_type"] = type(exc).__name__
            record["elapsed_ms"] = int((time.monotonic() - started) * 1000)
            record["reply_chars"] = 0
            record["reply_sha256"] = _hashlib.sha256(b"").hexdigest()
            captured.append(record)
            raise
        reply_text = str(reply or "")
        record["completed"] = True
        record["elapsed_ms"] = int((time.monotonic() - started) * 1000)
        record["reply_chars"] = len(reply_text)
        record["reply_sha256"] = _hashlib.sha256(reply_text.encode("utf-8")).hexdigest()
        record["reply_excerpt"] = reply_text[:600]
        captured.append(record)
        return reply

    git_sha = _core._git_sha()
    if not git_sha:
        raise RuntimeError("diagnostic probe requires an exact git head")
    artifact: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "mode": "capture",
        "diagnostic_only": True,
        "qualification_evidence": False,
        "git_sha": git_sha,
        "started_at": _core._utc_now(),
        "completed_at": None,
        "case": case_id,
        "answer_calls": [],
        "chain": {},
        "summary": {},
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="answer_probe_")
    try:
        database = RuntimeDatabase(Path(tmp) / "probe.sqlite")
        repository = WebLookupRepository(database)
        service = _core.ClaimEngineDispatchWebLookupService(
            repository,
            active_runtime_factory=_core._qualification_active_runtime_factory,
        )
        chat_service = _core._build_chat_service(database)
        chat_service.dependencies = replace(
            chat_service.dependencies, chat=capture_chat
        )
        record = _core.raw_run_case(
            case=case,
            repository=repository,
            service=service,
            chat_service=chat_service,
            reference_date=datetime.now(timezone.utc).date().isoformat(),
        )
        artifact["chain"] = {
            "gate": record.get("gate"),
            "brief": record.get("brief"),
            "sources": record.get("sources"),
            "evidence_path": record.get("evidence_path"),
            "answer": record.get("answer"),
            "metrics": {
                "atomic_routing": (record.get("metrics") or {}).get("atomic_routing"),
                "atomic_routing_extractions": (record.get("metrics") or {}).get(
                    "atomic_routing_extractions"
                ),
            },
        }
        artifact["answer_calls"] = captured
    finally:
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)
    artifact["completed_at"] = _core._utc_now()
    artifact["summary"] = {
        "answer_call_count": len(captured),
        "gate_status": ((artifact["chain"].get("gate") or {}).get("status") or ""),
        "answer_call_shapes": [
            {
                "task_name": row.get("kwargs", {}).get("task_name"),
                "message_chars": sum(
                    len(item["content"]) for item in row.get("messages") or []
                ),
                "reply_chars": row.get("reply_chars"),
                "elapsed_ms": row.get("elapsed_ms"),
                "exception_type": row.get("exception_type"),
            }
            for row in captured
        ],
    }
    output_path.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return artifact


def _load_case(manifest_path: Path, case_id: str) -> dict[str, str]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    for row in payload.get("cases") or []:
        if str(row.get("id")) == case_id:
            return {
                "id": case_id,
                "category": str(row.get("category") or ""),
                "question": str(row.get("question") or ""),
            }
    raise ValueError(f"case is not in the manifest: {case_id}")


def select_calls(
    calls: list[Any], task: str
) -> list[Mapping[str, Any]]:
    if task == "all":
        return list(calls)
    selected = [
        row
        for row in calls
        if str((row.get("kwargs") or {}).get("task_name") or "") == task
    ]
    return selected or [calls[-1]]


def run_replay(
    *,
    capture_path: Path,
    output_path: Path,
    runs: int,
    policy: str,
    task: str,
) -> dict[str, Any]:
    from src.llm_client import chat as production_chat

    artifact = json.loads(capture_path.read_text(encoding="utf-8"))
    calls = capture_chat_records(artifact)
    if not calls:
        raise ValueError("capture artifact contains no answer calls")
    target_calls = select_calls(calls, task)
    policies = ["captured", "thinking_off"] if policy == "both" else [policy]
    results: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "mode": "replay",
        "diagnostic_only": True,
        "qualification_evidence": False,
        "source_capture": str(capture_path).replace("\\", "/"),
        "gate_status": ((artifact.get("chain") or {}).get("gate") or {}).get("status"),
        "task_filter": task,
        "runs_per_policy": max(1, int(runs)),
        "attempts": [],
        "summaries": {},
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    for call in target_calls:
        call_task = str((call.get("kwargs") or {}).get("task_name") or "unknown")
        for selected_policy in policies:
            attempts = replay(
                call,
                chat_fn=production_chat,
                runs=max(1, int(runs)),
                policy=selected_policy,
            )
            results["attempts"].extend(attempts)
            results["summaries"][f"{call_task}:{selected_policy}"] = summarize_attempts(
                attempts
            )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return results


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["capture", "replay"], required=True)
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--capture", type=Path, default=None)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case", default=DEFAULT_CASE)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument(
        "--policy",
        choices=["captured", "thinking_off", "both"],
        default="captured",
    )
    parser.add_argument(
        "--task",
        default="all",
        help="answer call to replay: task_name, or 'all'",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    load_dotenv(REPO_ROOT / ".env")
    if args.mode == "capture":
        from tools import run_rq1c_bounded_qualification_core as _core

        manifest = args.manifest or _core.DEFAULT_MANIFEST
        artifact = run_capture(
            manifest_path=manifest.resolve(),
            output_path=args.output.resolve(),
            case_id=args.case,
        )
        print(json.dumps(artifact["summary"], ensure_ascii=False, sort_keys=True))
        return 0
    if args.capture is None:
        raise SystemExit("--capture is required in replay mode")
    results = run_replay(
        capture_path=args.capture.resolve(),
        output_path=args.output.resolve(),
        runs=args.runs,
        policy=args.policy,
        task=args.task,
    )
    print(json.dumps(results["summaries"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
