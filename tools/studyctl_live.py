"""Opt-in desktop-to-HTTP checks using real providers and a shared spend cap."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
from typing import Any


def plan_live(options) -> dict[str, Any]:
    budget = options.budget_cny
    if budget is None or not math.isfinite(budget) or budget <= 0:
        raise ValueError("A positive --budget-cny is required.")
    if not options.artifact_dir or not options.experiment_id:
        raise ValueError(
            "Provide --artifact-dir and a stable --experiment-id; retries share this ledger."
        )
    if not options.config_path or not options.desktop_launcher:
        raise ValueError("Provide --config-path and --desktop-launcher.")
    if not getattr(options, "dry_run", False) and not options.allow_paid:
        raise ValueError("Real calls require --allow-paid and the explicit budget.")
    return {
        "budget_cny": budget,
        "experiment_id": options.experiment_id,
        "artifact_dir": str(options.artifact_dir.resolve()),
        "cases": [
            "desktop_and_docker",
            "access_control",
            "nahida",
            "followup",
            "march7",
            "firefly",
            "attachment",
            "web_search",
            "persistence",
        ],
        "pricing": {"input_cny_per_mtok": 9, "output_cny_per_mtok": 27},
        "pricing_source": "https://api-docs.deepseek.com/zh-cn/quick_start/pricing/",
        "pricing_policy": "Peak uncached Pro prices bound both configured DeepSeek models; reservations are not billed cost.",
        "execution": "not_started",
    }


def live_environment(
    config: dict[str, str | None], artifact: Path, experiment: str, cap: float
) -> dict[str, str]:
    if config.get("LLM_PROVIDER_PROFILE") != "deepseek":
        raise ValueError(
            "This bounded qualification currently supports the configured DeepSeek provider only."
        )
    if config.get("DEEPSEEK_BASE_URL", "").rstrip("/") not in {
        "https://api.deepseek.com",
        "https://api.deepseek.com/v1",
    }:
        raise ValueError(
            "The verified price bound requires the official DeepSeek endpoint."
        )
    env = os.environ.copy()
    env.update({key: value for key, value in config.items() if value is not None})
    env.update(
        {
            "STUDY_AGENT_API_TOKEN": secrets.token_urlsafe(32),
            "STUDY_AGENT_RUNTIME_DB": str(artifact / "runtime.db"),
            "STUDY_AGENT_CURRENT_EXPORT_DIR": str(artifact / "current"),
            "STUDY_AGENT_ARCHIVE_EXPORT_DIR": str(artifact / "archive"),
            "LLM_SPEND_LEDGER_DB": str(artifact / "spend.db"),
            "LLM_SPEND_EXPERIMENT_ID": experiment,
            "LLM_SPEND_EXPERIMENT_CAP_CNY": str(cap),
            "LLM_SPEND_CAP_CNY": str(cap),
            "LLM_SPEND_INPUT_CNY_PER_MTOK": "9",
            "LLM_SPEND_OUTPUT_CNY_PER_MTOK": "27",
            "LLM_SPEND_DEFAULT_MAX_TOKENS": "1400",
            "LLM_MAX_TOKENS": "1400",
            "LLM_MAX_RETRIES": "0",
            "DEEPSEEK_MAX_RETRIES": "0",
            "LLM_EXPERIMENT_ALLOWED_MODELS": "deepseek-flash,deepseek-v4-pro",
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
        }
    )
    env.pop("VITE_STUDY_AGENT_API_TOKEN", None)
    return env


def require_answer(data: dict[str, Any]) -> str:
    answer = str(data.get("reply", ""))
    if not answer.strip():
        raise ValueError("The published final answer is empty.")
    if data.get("status") in {"failed", "cancelled", "interrupted"}:
        raise ValueError("The turn did not complete.")
    return answer


def build_launcher_command(
    launcher: Path,
    root: Path,
    config_path: Path,
    python: str,
    backend_port: int,
    frontend_port: int,
) -> list[str]:
    launcher_args = [
        "-NoBrowser",
        "-StartSearXNG",
        "-ProjectRoot",
        str(root),
        "-ConfigPath",
        str(config_path.resolve()),
        "-PythonExecutable",
        python,
        "-BackendPort",
        str(backend_port),
        "-FrontendPort",
        str(frontend_port),
    ]
    # A .ps1 is not a Win32 executable; Windows refuses to CreateProcess it.
    if launcher.suffix.lower() in {".cmd", ".bat"}:
        return ["cmd.exe", "/c", str(launcher), *launcher_args]
    return [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(launcher),
        *launcher_args,
    ]


def run_live(options, root: Path) -> dict[str, Any]:
    result = plan_live(options)
    if getattr(options, "dry_run", False):
        return result
    from dotenv import dotenv_values
    import requests
    from src.infrastructure.sqlite.database import RuntimeDatabase
    from src.infrastructure.sqlite.spend_ledger import SpendLedger, SpendLedgerError

    artifact = options.artifact_dir.resolve()
    artifact.mkdir(parents=True, exist_ok=True)
    attempt = time.strftime("%Y%m%d-%H%M%S")
    config = dict(dotenv_values(options.config_path))
    env = live_environment(config, artifact, options.experiment_id, options.budget_cny)
    # Migrate the existing ledger schema, never replace/reset prior reservations.
    # RuntimeDatabase only records the path; initialize() is what creates the
    # spend-ledger tables that reserve_call() requires.
    RuntimeDatabase(artifact / "spend.db").initialize()
    report_path = artifact / f"checks-{attempt}.json"
    result.update(execution="attempted", checks=[], artifacts=[str(report_path)])
    headers = {"X-Study-Agent-Token": env["STUDY_AGENT_API_TOKEN"]}
    base = f"http://127.0.0.1:{options.backend_port}"
    client = requests.Session()
    client.headers.update(headers)
    client.trust_env = False  # Loopback requests must not enter an ambient proxy.

    def record(name: str, passed: bool, **details: Any) -> None:
        result["checks"].append({"name": name, "passed": passed, **details})
        report_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def request(method: str, path: str, **kwargs: Any):
        response = client.request(method, base + path, timeout=(5, 180), **kwargs)
        response.raise_for_status()
        return response.json()

    def chat(
        name: str,
        session_id: str,
        text: str,
        role: str,
        mode: str = "普通",
        **extra: Any,
    ):
        started = time.monotonic()
        payload = dict(
            user_input=text,
            session_id=session_id,
            selected_role=role,
            selected_mode=mode,
            selected_model="flash",
            performance_mode="fast",
            context_mode="none",
            rag_enabled=False,
            web_policy="off",
            cloud_context_policy="allow",
            **extra,
        )
        data = request("POST", "/chat", json=payload)
        (artifact / f"{attempt}-{name}.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        answer = require_answer(data)
        record(
            name,
            data.get("route", {}).get("role") == role,
            seconds=round(time.monotonic() - started, 2),
            session_id=session_id,
            turn_id=data.get("turn_id"),
            answer=answer,
            route=data.get("route"),
        )
        return data

    try:
        # Ports belong to this attempt; do not accidentally exercise another worktree.
        import socket

        for port in (options.backend_port, options.frontend_port):
            with socket.socket() as probe:
                probe.settimeout(0.2)
                if probe.connect_ex(("127.0.0.1", port)) == 0:
                    raise ValueError(
                        f"Port {port} is already in use; choose fresh ports for this attempt."
                    )
        launcher = options.desktop_launcher
        command = build_launcher_command(
            launcher,
            root,
            options.config_path,
            sys.executable,
            options.backend_port,
            options.frontend_port,
        )
        with (artifact / f"launcher-{attempt}.log").open("w", encoding="utf-8") as log:
            launched = subprocess.run(
                command,
                cwd=root,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=240,
                check=False,
            )
        if launched.returncode:
            raise ValueError(
                f"Desktop startup failed ({launched.returncode}); inspect its local log."
            )
        docker = subprocess.run(
            [
                "docker",
                "inspect",
                "study-agent-searxng",
                "--format",
                "{{.State.Running}}",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
        if docker.stdout.strip() != "true":
            raise ValueError("The required Docker SearXNG container is not running.")
        record(
            "desktop_and_docker",
            request("GET", "/health").get("service") == "study-agent",
            command=command,
        )
        public_client = requests.Session()
        public_client.trust_env = False
        public = public_client.get(base + "/sessions", timeout=5)
        record(
            "access_control", public.status_code == 401, status_code=public.status_code
        )
        sid = request("POST", "/sessions/new")["session_id"]
        chat(
            "nahida",
            sid,
            "只有10个存储位置却有11个不同的键，先不讲HashMap，从根本推导为什么需要额外区分机制。简短讲透，不出题。",
            "nahida",
        )
        chat(
            "followup",
            sid,
            "延续上面的10个位置和11个键，用袜子与抽屉的类比讲清楚，并指出类比的边界。不要让我复述。",
            "nahida",
            "费曼",
        )
        march = request("POST", "/sessions/new")["session_id"]
        chat(
            "march7",
            march,
            "游戏服务器有1000个Player，每个有血量，但在线人数只有一份。用轻松自然的语言讲清static，不要列长提纲。",
            "march7",
        )
        firefly = request("POST", "/sessions/new")["session_id"]
        chat(
            "firefly",
            firefly,
            'final Student a = new Student(); a.name = "Tom"; 完整讲解是否能编译，区分引用和对象，不要追问。',
            "firefly",
        )
        attachment = request(
            "POST",
            f"/sessions/{firefly}/attachments",
            files={
                "file": (
                    "inventory-check.txt",
                    "验收用合成库存记录。商品SKU-A9，当前库存37件，锁定5件，可售32件。".encode(),
                    "text/plain",
                )
            },
        )
        data = chat(
            "attachment",
            firefly,
            "只根据这次附件：SKU-A9的当前库存、锁定和可售分别是多少？",
            "firefly",
            attachment_ids=[attachment["id"]],
        )
        record(
            "attachment_values",
            all(value in data["reply"] for value in ("37", "5", "32")),
            attachment_id=attachment["id"],
        )
        research = request(
            "POST",
            "/web-lookup-runs",
            json={
                "query": "site:docs.oracle.com Java static class variables",
                "max_items": 3,
            },
        )
        (artifact / f"{attempt}-web-search.json").write_text(
            json.dumps(research, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        record(
            "web_search",
            research.get("status") in {"completed", "partial"}
            and bool(research.get("sources") or research.get("items")),
            run_id=research.get("id"),
            status=research.get("status"),
        )
        persisted = request("GET", f"/sessions/{firefly}")
        record(
            "persistence",
            "SKU-A9" in json.dumps(persisted, ensure_ascii=False),
            session_id=firefly,
        )
    except Exception as exc:
        record("failure", False, error_type=type(exc).__name__, message=str(exc)[:600])
    finally:
        try:
            result["spend"] = SpendLedger(artifact / "spend.db").experiment_spend(
                options.experiment_id
            )
        except SpendLedgerError as exc:
            # No reservation rows is a verifiable zero, not an unknown cost.
            if "unknown experiment" in str(exc):
                result["spend"] = {"reserved_micros": 0, "calls": 0}
            else:
                result["spend"] = {"unavailable": type(exc).__name__}
        except Exception as exc:
            result["spend"] = {"unavailable": type(exc).__name__}
        result["status"] = (
            "PASS"
            if result["checks"] and all(row["passed"] for row in result["checks"])
            else "FAIL"
        )
        result["exit_code"] = 0 if result["status"] == "PASS" else 1
        report_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return result
