"""Render saved generation artifacts and score the frozen batch without resending."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

from tools.m4c3_prepare import ROOT, TASKS


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def browser_environment(extra: dict[str, str]) -> dict[str, str]:
    allowed = {
        "PATH",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
        "SYSTEMDRIVE",
        "PROGRAMDATA",
        "ALLUSERSPROFILE",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "PROGRAMW6432",
        "USERPROFILE",
        "HOME",
        "TEMP",
        "TMP",
        "LOCALAPPDATA",
        "APPDATA",
        "PLAYWRIGHT_BROWSERS_PATH",
        "PLAYWRIGHT_USE_SYSTEM_CHROME",
    }
    return {
        key: value for key, value in os.environ.items() if key.upper() in allowed
    } | extra


def evaluate_artifacts(run_dir: Path, *, render: bool = True) -> dict:
    execution = read_json(run_dir / "report.json")
    index = read_json(run_dir / "index.json")
    if execution.get("mode") not in {"paid", "fake_http"}:
        raise ValueError("expected a generation batch, not historical replay")
    if index.get("purpose") != "m4c3_first_generation":
        raise ValueError("missing first-generation provenance")
    if index.get("generation_mode") != execution["mode"]:
        raise ValueError("generation mode differs across artifacts")
    reports = [run_dir / f"sandbox-{width}" / "report.json" for width in (1280, 390)]
    if render and not all(path.is_file() for path in reports):
        cli = ROOT / "frontend/node_modules/@playwright/test/cli.js"
        node = shutil.which("node")
        if not node or not cli.is_file():
            raise RuntimeError(
                "install the existing frontend dependencies and Chromium first"
            )
        # Browser children need the toolchain, not the parent provider secrets.
        env = browser_environment({"M4C3_RAW_DIR": str(run_dir.resolve())})
        with (run_dir / "browser.log").open("wb") as log:
            result = subprocess.run(
                [
                    node,
                    str(cli),
                    "test",
                    "--config=playwright.m4c-offline.config.ts",
                    "e2e/acceptance/rawReplay.spec.ts",
                    "--project=desktop-chromium",
                    "--grep=raw corpus",
                    "--reporter=line",
                ],
                cwd=ROOT / "frontend",
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=600,
                check=False,
            )
        if result.returncode:
            raise RuntimeError(
                f"browser replay failed; answers retained; inspect {run_dir / 'browser.log'}"
            )
    if not all(path.is_file() for path in reports):
        raise ValueError(
            "both viewport reports are required; never infer missing evidence"
        )
    by_task: dict[str, list[dict]] = {task: [] for task in TASKS}
    source_cases = {item["case_id"]: item for item in index["cases"]}
    if len(source_cases) != len(index["cases"]):
        raise ValueError("duplicate document identity")
    for source in source_cases.values():
        if source.get("capabilities", []) not in ([], ["three"]):
            raise ValueError("unsupported source host capabilities")
        path = (run_dir / source["file"]).resolve()
        if (
            not path.is_relative_to(run_dir.resolve())
            or hashlib.sha256(path.read_bytes()).hexdigest() != source["sha256"]
        ):
            raise ValueError("source document changed or escaped run directory")
    for report_path, expected_width in zip(reports, (1280, 390), strict=True):
        report = read_json(report_path)
        if report.get("source_generation_mode") != execution["mode"] or report.get(
            "historical_replay_only"
        ):
            raise ValueError("browser report provenance mismatch")
        if len(report["cases"]) != len(source_cases):
            raise ValueError("incomplete viewport report")
        seen = set()
        for item in report["cases"]:
            source = source_cases.get(item["case_id"])
            if (
                not source
                or item["case_id"] in seen
                or item["sha256"] != source["sha256"]
                or item["task_id"] != source["task_id"]
                or item.get("capabilities", []) != source.get("capabilities", [])
                or item["viewport"]["width"] != expected_width
            ):
                raise ValueError("duplicate or stale browser evidence")
            seen.add(item["case_id"])
            if item["task_id"] not in by_task:
                raise ValueError("unknown task in generation corpus")
            by_task[item["task_id"]].append(item)
    generated = {item["task_id"]: item for item in execution["cases"]}
    if len(generated) != len(execution["cases"]) or set(generated) - set(TASKS):
        raise ValueError("invalid generated task identities")
    outcomes = []
    for task in TASKS:
        case = generated.get(task, {})
        evidence = by_task[task]
        if not case.get("sent"):
            status = "not_run"
        elif case.get("status") != "completed" or not evidence:
            status = "failed"
        else:
            checks = [
                check
                for item in evidence
                for check in item["checks"] + item["usability"]
            ]
            status = (
                "failed"
                if any(check["status"] == "fail" for check in checks)
                else (
                    "indeterminate"
                    if not checks or any(check["status"] != "pass" for check in checks)
                    else "passed"
                )
            )
        outcomes.append(
            {
                "task_id": task,
                "status": status,
                "screenshots": [
                    str(
                        run_dir
                        / f"sandbox-{item['viewport']['width']}"
                        / item["screenshot"]
                    )
                    for item in evidence
                ],
            }
        )
    counts = {
        name: sum(item["status"] == name for item in outcomes)
        for name in ("passed", "failed", "indeterminate", "not_run")
    }
    complete = counts["not_run"] == 0 and len(generated) == 12
    quality_data = execution["mode"] == "paid"
    summary = {
        "schema_version": "m4c3-score-v1",
        "mode": execution["mode"],
        "real_model_quality_data": quality_data,
        "batch_complete": complete,
        "counts": counts,
        "cases": outcomes,
        "ledger": execution.get("ledger"),
        "first_generation_success_rate": counts["passed"] / 12
        if quality_data and complete and not counts["indeterminate"]
        else None,
        "success_rate_lower_bound": counts["passed"] / 12
        if quality_data and complete
        else None,
        "success_rate_upper_bound": (counts["passed"] + counts["indeterminate"]) / 12
        if quality_data and complete
        else None,
        "note": "Fake transport proves the pipeline only; missing task geometry is indeterminate, not a model failure.",
    }
    (run_dir / "scores.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--aggregate-only", action="store_true")
    args = parser.parse_args()
    result = evaluate_artifacts(args.run_dir, render=not args.aggregate_only)
    print(json.dumps({"mode": result["mode"], "counts": result["counts"]}))


if __name__ == "__main__":
    main()
