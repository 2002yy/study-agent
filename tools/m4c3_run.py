"""Run the frozen M4-C3 batch through ChatService; offline fake HTTP by default.

Paid execution requires both --allow-paid and a matching authorization file.
Each SDK request is reserved by the existing guard with an added transactional
batch bound. No second ledger, retries, refunds or hidden continuation calls.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx
from openai import OpenAI

from src import llm_client, llm_spend_guard as spend
from src.application.chat_service import ChatCommand, ChatDependencies, ChatService
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.mode_manager import RuntimeModes
from src.repositories.runtime_repository import RuntimeRepository
from tools.m4c3_budget import EXPERIMENT, PREFIX
from tools.m4c3_prepare import ROOT, build_manifest, ledger_snapshot


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def validate_authorization(authorization: dict | None) -> None:
    required = {
        "authorized": True,
        "model": "deepseek-flash",
        "experiment": EXPERIMENT,
        "max_calls": 12,
        "per_call_cny": 1,
        "batch_cny": 12,
        "shared_cny": 30,
    }
    if not authorization or any(authorization.get(k) != v for k, v in required.items()):
        raise ValueError("explicit matching paid authorization is required")
    if not str(authorization.get("approval_reference", "")).strip():
        raise ValueError("approval_reference is required")


def run_batch(
    out: Path,
    ledger: Path,
    pricing: dict,
    *,
    allow_paid: bool = False,
    authorization: dict | None = None,
    fake_reply: str | None = None,
) -> dict:
    if allow_paid:
        validate_authorization(authorization)
        shared_ledger = Path(
            "D:/study-agent-validation/live-20261102/spend.db"
        ).resolve()
        if ledger.resolve() != shared_ledger:
            raise ValueError("paid execution must use the canonical shared ledger")
        today = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
        if (
            pricing.get("verified_at") != today
            or pricing.get("source")
            != "https://api-docs.deepseek.com/zh-cn/quick_start/pricing/"
        ):
            raise ValueError(
                "verify the official pricing snapshot on the execution date first"
            )
        ledger_snapshot(ledger, EXPERIMENT)
    elif fake_reply is None:
        raise ValueError("offline execution requires an explicit fake reply")
    if pricing["input_cny_per_mtok"] != 9 or pricing["output_cny_per_mtok"] != 27:
        raise ValueError(
            "preserve the shared ledger's reviewed conservative pricing 9/27"
        )
    # The SDK secret is never saved to any artifact.
    key = os.environ.get("DEEPSEEK_API_KEY", "") if allow_paid else "offline-fake-key"
    if not key:
        raise ValueError("DEEPSEEK_API_KEY is required")
    out.mkdir(parents=True, exist_ok=False)
    if not allow_paid:
        if ledger.exists():
            raise ValueError("offline mode requires a fresh temporary ledger")
        RuntimeDatabase(ledger).initialize()
    config = {
        "LLM_PROVIDER_PROFILE": "deepseek",
        "DEEPSEEK_API_KEY": key,
        "DEEPSEEK_BASE_URL": "https://api.deepseek.com/v1",
        "DEEPSEEK_MODEL_FLASH_NAME": "deepseek-flash",
        "DEEPSEEK_MODEL_PRO_NAME": "deepseek-flash",
        "LLM_MAX_RETRIES": "0",
        "DEEPSEEK_MAX_RETRIES": "0",
        "LLM_SPEND_LEDGER_DB": str(ledger.resolve()),
        "LLM_SPEND_EXPERIMENT_ID": EXPERIMENT,
        "LLM_SPEND_EXPERIMENT_CAP_CNY": "30",
        "LLM_SPEND_CAP_CNY": "30",
        "LLM_SPEND_INPUT_CNY_PER_MTOK": "9",
        "LLM_SPEND_OUTPUT_CNY_PER_MTOK": "27",
        "LLM_SPEND_DEFAULT_MAX_TOKENS": "1400",
        "LLM_MAX_TOKENS": "9000",
        "LLM_EXPERIMENT_ALLOWED_MODELS": "deepseek-flash",
        spend.SETTLEMENT_ASSEMBLY_FLAG: "off",
    }
    context_source = (
        ROOT / "frontend/src/features/answer-ui/interactiveRuntime.ts"
    ).read_text(encoding="utf-8")
    capability = re.search(
        r"export const INTERACTIVE_CONTEXT = `([\s\S]*?)`;", context_source
    )
    if capability is None:
        raise ValueError("product capability context missing")
    report: dict[str, Any] = {
        "schema_version": "m4c3-execution-v1",
        "execution": "running",
        "mode": "paid" if allow_paid else "fake_http",
        "pricing": pricing,
        "cases": [],
    }
    original_reserve = spend.reserve_call
    active: dict = {}
    raw_cases = []

    def reserve(**kwargs):
        if (
            active.get("reserved")
            or kwargs["attempts"] != 1
            or kwargs["model"] != "deepseek-flash"
        ):
            raise ValueError("one request per case; retries and other models forbidden")
        amount = spend.cny_to_micros(
            spend.reservation_cny(
                prompt_chars=kwargs["prompt_chars"],
                max_tokens=kwargs["max_tokens"],
                attempts=1,
            )
        )
        if not 0 < amount <= 1_000_000:
            raise ValueError("per-call conservative reservation exceeds CNY 1")

        def guard(db: sqlite3.Connection, experiment: str):
            count, total = db.execute(
                "SELECT COUNT(*),COALESCE(SUM(amount_micros),0) FROM llm_spend_reservations "
                "WHERE experiment_id=? AND substr(request_key,1,?)=?",
                (experiment, len(PREFIX), PREFIX),
            ).fetchone()
            return (
                "m4c3_batch_limit"
                if count >= 12 or total + amount > 12_000_000
                else None
            )

        result = original_reserve(
            **{
                **kwargs,
                "request_key": active["invocation_key"],
                "admission_guard": guard,
            }
        )
        active["reserved"] = True
        active["reserved_micros"] = amount
        write_json(
            active["directory"] / "reservation.json",
            {"amount_micros": amount, "request_key": active["invocation_key"]},
        )
        return result

    class Transport(httpx.BaseTransport):
        def __init__(self):
            self.network = httpx.HTTPTransport(retries=0) if allow_paid else None

        def handle_request(self, request):
            if not active.get("reserved") or active.get("sent"):
                raise ValueError("send requires one fresh durable reservation")
            if (
                request.url.host != "api.deepseek.com"
                or request.url.path != "/v1/chat/completions"
            ):
                raise ValueError("unexpected provider endpoint")
            active["sent"] = True  # uncertain sends are never retried after a crash
            wire = request.read()
            (active["directory"] / "request-body.json").write_bytes(wire)
            payload = json.loads(wire)
            write_json(active["directory"] / "request.json", payload)
            if allow_paid:
                response = self.network.handle_request(request)
                response.read()
            else:
                response = httpx.Response(
                    200,
                    request=request,
                    json={
                        "id": "offline",
                        "object": "chat.completion",
                        "created": 0,
                        "model": "deepseek-flash",
                        "choices": [
                            {
                                "index": 0,
                                "message": {"role": "assistant", "content": fake_reply},
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": {
                            "prompt_tokens": 100,
                            "completion_tokens": 100,
                            "total_tokens": 200,
                        },
                    },
                )
            (active["directory"] / "provider-response.txt").write_bytes(
                response.content
            )
            try:
                provider_response = response.json()
            except ValueError:
                provider_response = {
                    "http_status": response.status_code,
                    "response_format": "non_json",
                }
            write_json(
                active["directory"] / "provider-response.json", provider_response
            )
            active["provider_response"] = provider_response
            return response

        def close(self):
            if self.network:
                self.network.close()

    with (
        patch.dict(os.environ, config),
        httpx.Client(transport=Transport(), timeout=180) as http,
    ):
        sdk = OpenAI(
            api_key=key,
            base_url=config["DEEPSEEK_BASE_URL"],
            http_client=http,
            max_retries=0,
        )
        with (
            patch.object(llm_client, "get_client", lambda **kw: sdk),
            patch.object(spend, "reserve_call", reserve),
        ):
            repository = RuntimeRepository(RuntimeDatabase(out / "runtime.db"))
            deps = replace(
                ChatDependencies(),
                load_runtime_modes=lambda: RuntimeModes(performance_mode="fast"),
                read_memory_bundle=lambda mode: {},
            )
            service = ChatService(repository, deps)
            for case in build_manifest()["cases"]:
                directory = out / case["task_id"]
                directory.mkdir()
                active.clear()
                active.update(case, directory=directory)
                started = time.monotonic()
                result = {
                    "task_id": case["task_id"],
                    "invocation_key": case["invocation_key"],
                }
                try:
                    prepared = service.start_turn(
                        ChatCommand(
                            user_input=case["prompt"],
                            selected_role="nahida",
                            selected_mode="普通",
                            selected_model="flash",
                            performance_mode="fast",
                            context_mode="none",
                            rag_enabled=False,
                            conversation_instruction=capability.group(1),
                        )
                    )
                    reply = service.generate(prepared)
                    # generate returns exactly the assistant text persisted by ChatService.
                    answer = reply
                    (directory / "answer.txt").write_bytes(answer.encode("utf-8"))
                    result.update(
                        status="completed",
                        route=prepared.route,
                        turn_id=prepared.turn.id,
                        provider=active.get("provider_response"),
                    )
                    from src.interactive_history import find_interactive_versions

                    versions = find_interactive_versions(
                        [{"role": "assistant", "content": answer}]
                    )
                    for number, version in enumerate(versions):
                        name = f"{case['task_id']}/document-{number}.html"
                        (out / name).write_bytes(version.html.encode("utf-8"))
                        raw_cases.append(
                            {
                                "case_id": f"{case['task_id']}-{number}",
                                "file": name,
                                "sha256": hashlib.sha256(
                                    version.html.encode()
                                ).hexdigest(),
                                "source_kind": "saved_model"
                                if allow_paid
                                else "fake_transport",
                                "task_id": case["task_id"],
                                "revision": version.revision,
                            }
                        )
                except Exception as error:
                    result.update(status="failed", error_type=type(error).__name__)
                result.update(
                    elapsed_seconds=time.monotonic() - started,
                    sent=bool(active.get("sent")),
                    reserved_micros=active.get("reserved_micros", 0),
                )
                write_json(directory / "result.json", result)
                report["cases"].append(result)
                write_json(out / "report.json", report)
        sdk.close()
    report["execution"] = "completed"
    try:
        report["ledger"] = ledger_snapshot(ledger, EXPERIMENT)
    except (ValueError, sqlite3.Error) as error:
        report["ledger"] = {
            "observation": "unavailable",
            "error_type": type(error).__name__,
        }
    write_json(
        out / "index.json",
        {
            "schema_version": "m4c3-raw-v1",
            "purpose": "m4c3_first_generation",
            "generation_mode": "paid" if allow_paid else "fake_http",
            "cases": raw_cases,
        },
    )
    write_json(out / "report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--pricing", required=True, type=Path)
    parser.add_argument("--allow-paid", action="store_true")
    parser.add_argument("--authorization", type=Path)
    parser.add_argument(
        "--browser",
        action="store_true",
        help="Run offline sandbox scoring after generation",
    )
    args = parser.parse_args()
    authorization = (
        json.loads(args.authorization.read_text(encoding="utf-8-sig"))
        if args.authorization
        else None
    )
    report = run_batch(
        args.out,
        args.ledger,
        json.loads(args.pricing.read_text(encoding="utf-8-sig")),
        allow_paid=args.allow_paid,
        authorization=authorization,
        fake_reply=None
        if args.allow_paid
        else (
            "```study-ui\n"
            + json.dumps(
                {
                    "type": "interactive",
                    "id": "offline-fixture",
                    "revision": 1,
                    "title": "Offline fixture",
                    "summary": "Fake transport; not model quality evidence.",
                    "html": "<p>Offline fixture; not a model answer.</p>",
                }
            )
            + "\n```"
        ),
    )
    if args.browser:
        from tools.m4c3_results import evaluate_artifacts

        evaluate_artifacts(args.out, render=True)
    print(
        json.dumps(
            {
                "execution": report["execution"],
                "cases": len(report["cases"]),
                "mode": report["mode"],
            }
        )
    )


if __name__ == "__main__":
    main()
