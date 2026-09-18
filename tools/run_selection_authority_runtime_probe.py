"""§38b runtime probe: selection authority = model on the raw (unguarded) driver.

Diagnostic-only. This is the *same* case runner the calibration harness uses,
except it calls the raw case driver instead of the qualification-guarded one:

- the qualification guard caps physical research model calls at six and
  reserves two for answers; a per-wave selector call inside that cap starves
  the pipeline (observed: wave 2+ selectors hit
  ``qualification_research_model_budget_exhausted`` and fell back to rules,
  which then dropped the target again);
- the raw driver keeps the runtime's own production budgets
  (max_model_calls=8 etc.) but has no qualification overlay.

Accounting caveat, recorded in the artifact: the selector call does not pass
through the runtime's durable model-attempt ledger, so the runtime's own model
budget does not count it. Selector calls are counted separately in
``metrics.selection_authority``. This runner is never qualification evidence.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

# Importing the public qualification entrypoint first preserves the guardrail
# wiring used by the raw per-case driver's collaborators.
from tools import run_rq1c_bounded_qualification as _public  # noqa: E402,F401
from tools import run_rq1c_bounded_qualification_core as _core  # noqa: E402
from src.infrastructure.sqlite.database import RuntimeDatabase  # noqa: E402
from src.repositories.web_lookup_repository import WebLookupRepository  # noqa: E402
from src.web.research.selection_authority import (  # noqa: E402
    SELECTION_AUTHORITY_ENV,  # noqa: F401
    selection_authority_mode,
)

PROBE_SCHEMA_VERSION = "selection-authority-runtime-probe-v1"
DEFAULT_CASE = "rq1c-historical-current-node-modules"


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


def run_probe(*, manifest_path: Path, output_path: Path, case_id: str) -> dict[str, Any]:
    load_dotenv(REPO_ROOT / ".env")
    case = _load_case(manifest_path, case_id)
    git_sha = _core._git_sha()
    if not git_sha:
        raise RuntimeError("diagnostic probe requires an exact git head")
    reference_date = datetime.now(timezone.utc).date().isoformat()
    artifact: dict[str, Any] = {
        "schema_version": PROBE_SCHEMA_VERSION,
        "diagnostic_only": True,
        "qualification_evidence": False,
        "qualification_guard_bypassed": True,
        "guard_bypass_reason": (
            "the six-call research cap starves per-wave selection calls; the raw "
            "driver keeps the runtime's production budgets but has no overlay"
        ),
        "selector_accounting_caveat": (
            "selection-authority model calls are recorded in "
            "metrics.selection_authority but do not pass through the runtime's "
            "durable model-attempt ledger, so the runtime's own model budget "
            "does not count them"
        ),
        "git_sha": git_sha,
        "started_at": _core._utc_now(),
        "completed_at": None,
        "manifest": {
            "path": str(manifest_path).replace("\\", "/"),
            "case_count": 1,
        },
        "selection_authority_mode": selection_authority_mode(),
        "cases": [],
        "summary": {},
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="selection_probe_")
    try:
        database = RuntimeDatabase(Path(tmp) / "probe.sqlite")
        repository = WebLookupRepository(database)
        service = _core.ClaimEngineDispatchWebLookupService(
            repository,
            active_runtime_factory=_core._qualification_active_runtime_factory,
        )
        chat_service = _core._build_chat_service(database)
        started = time.monotonic()
        record = _core.raw_run_case(
            case=case,
            repository=repository,
            service=service,
            chat_service=chat_service,
            reference_date=reference_date,
        )
        record["elapsed_seconds"] = round(max(0.0, time.monotonic() - started), 3)
        artifact["cases"].append(record)
    finally:
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)
    artifact["completed_at"] = _core._utc_now()
    record = artifact["cases"][0]
    metrics = record.get("metrics") or {}
    authority_records = metrics.get("selection_authority") or []
    artifact["summary"] = {
        "selection_authority_records": len(authority_records),
        "selector_completed_calls": sum(
            1 for item in authority_records if item.get("status") == "completed"
        ),
        "fallback_records": sum(1 for item in authority_records if item.get("fallback")),
        "targets_in_selector_input": sorted(
            {
                url
                for item in authority_records
                for url in item.get("input_set") or []
                if "api/modules" in url
            }
        ),
        "reads": len(metrics.get("reads") or []),
        "gate_status": (record.get("gate") or {}).get("status", ""),
        "answer_status": (record.get("answer") or {}).get("status", ""),
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
    parser.add_argument("--case", default=DEFAULT_CASE)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    artifact = run_probe(
        manifest_path=args.manifest.resolve(),
        output_path=args.output.resolve(),
        case_id=args.case,
    )
    print(json.dumps(artifact["summary"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
