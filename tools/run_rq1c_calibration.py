"""Calibration-case runner for paired performance attribution.

The strict qualification entrypoint (``run_rq1c_bounded_qualification``) is
frozen to exactly 12 holdout cases, and that guard must stay: it is the
qualification contract. Paired attribution needs 3-4 *representative* cases
instead of a full 12-case run, so this diagnostic runner reuses the very same
guarded per-case driver, database/service wiring and artifact shape - it only
selects a subset of the frozen manifest.

It changes nothing about budgets, providers or prompts, and its artifact is a
diagnostic (``rq1c-calibration-run-v1``), never qualification evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

# Importing the public qualification entrypoint first preserves the guardrail
# wiring (production chat proxy + binding rows provider) used by the guarded
# per-case driver.
from tools import run_rq1c_bounded_qualification as _public  # noqa: E402,F401
from tools import run_rq1c_bounded_qualification_core as _core  # noqa: E402
from src.application.research_web_lookup_dispatch import (  # noqa: E402
    ClaimEngineDispatchWebLookupService,
)
from src.infrastructure.sqlite.database import RuntimeDatabase  # noqa: E402
from src.repositories.web_lookup_repository import WebLookupRepository  # noqa: E402

# Same representative set as tools/run_paired_attribution.CALIBRATION_CASES.
DEFAULT_CASES = (
    "rq1c-numeric-uk-inflation",
    "rq1c-unverifiable-python-security",
    "rq1c-academic-primary-attention",
    "rq1c-provenance-xz",
)
CALIBRATION_SCHEMA_VERSION = "rq1c-calibration-run-v1"


def _load_cases(
    manifest_path: Path,
    case_ids: Iterable[str],
) -> tuple[dict[str, str], ...]:
    """Select the requested cases from the frozen manifest (no 12-case guard)."""

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
            raise ValueError(f"calibration case is not in the manifest: {case_id}")
        selected.append(
            {
                "id": case_id,
                "category": str(row.get("category") or ""),
                "question": str(row.get("question") or ""),
            }
        )
    if not selected:
        raise ValueError("no calibration case selected")
    return tuple(selected)


def run_calibration(
    *,
    manifest_path: Path,
    output_path: Path,
    case_ids: Iterable[str],
) -> dict[str, Any]:
    load_dotenv(REPO_ROOT / ".env")
    cases = _load_cases(manifest_path, case_ids)
    git_sha = _core._git_sha()
    if not git_sha:
        raise RuntimeError("calibration run requires an exact git head")
    manifest_bytes = manifest_path.read_bytes()
    reference_date = datetime.now(timezone.utc).date().isoformat()
    artifact: dict[str, Any] = {
        "schema_version": CALIBRATION_SCHEMA_VERSION,
        "diagnostic_only": True,
        "qualification_evidence": False,
        "git_sha": git_sha,
        "started_at": _core._utc_now(),
        "completed_at": None,
        "manifest": {
            "path": str(manifest_path).replace("\\", "/"),
            "sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "case_count": len(cases),
        },
        "configured_budget": {
            "max_candidates": 20,
            "max_reads": 8,
            "max_model_calls": 8,
            "soft_timeout_seconds": 45,
            "hard_timeout_seconds": 60,
        },
        "cases": [],
        "summary": {},
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="rq1c_calibration_")
    try:
        database = RuntimeDatabase(Path(tmp) / "calibration.sqlite")
        repository = WebLookupRepository(database)
        service = ClaimEngineDispatchWebLookupService(
            repository,
            active_runtime_factory=_core._qualification_active_runtime_factory,
        )
        chat_service = _core._build_chat_service(database)
        for index, case in enumerate(cases, start=1):
            record = _core._run_case(
                case=case,
                repository=repository,
                service=service,
                chat_service=chat_service,
                reference_date=reference_date,
            )
            artifact["cases"].append(record)
            write_started = time.monotonic()
            output_path.write_text(
                json.dumps(artifact, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            breakdown = record.get("finalization_breakdown")
            if isinstance(breakdown, dict):
                breakdown["artifact_write_seconds"] = round(
                    max(0.0, time.monotonic() - write_started), 3
                )
            print(
                f"[{index}/{len(cases)}] {case['id']}: "
                f"status={(record.get('run') or {}).get('status', 'runner_error')} · "
                f"elapsed={record['elapsed_seconds']}s",
                flush=True,
            )
    finally:
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)

    records = artifact["cases"]
    artifact["completed_at"] = _core._utc_now()
    artifact["summary"] = {
        "case_count": len(records),
        "runner_error_cases": sum(1 for item in records if item.get("runner_error_type")),
        "budget_violation_cases": sum(
            1 for item in records if item.get("budget_contract_violations")
        ),
        "total_elapsed_seconds": round(
            sum(float(item.get("elapsed_seconds") or 0.0) for item in records), 3
        ),
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
        help="comma separated holdout case ids (diagnostic subset)",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    case_ids = [item.strip() for item in args.cases.split(",") if item.strip()]
    artifact = run_calibration(
        manifest_path=args.manifest.resolve(),
        output_path=args.output.resolve(),
        case_ids=case_ids,
    )
    print(json.dumps(artifact["summary"], ensure_ascii=False, sort_keys=True))
    return 0 if artifact["summary"]["runner_error_cases"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
