"""Compatibility facade for the guarded RQ1-C qualification core."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools import run_rq1c_bounded_qualification_core as _core  # noqa: E402

DEFAULT_MANIFEST = _core.DEFAULT_MANIFEST
DEFAULT_OUTPUT = _core.DEFAULT_OUTPUT

_evidence_rows = _core._evidence_rows
_load_manifest = _core._load_manifest
_observed_read_count = _core._observed_read_count
_provider_audit = _core._provider_audit
_source_rows = _core._source_rows
_unavailable_answer_surface = _core._unavailable_answer_surface
_answer_stage_model_calls = _core._answer_stage_model_calls
_production_answer_surface = _core._production_answer_surface
_production_chat_command = _core._production_chat_command
_active_context = _core._active_context
_parser = _core._parser

_git_sha = _core._git_sha
_build_chat_service = _core._build_chat_service
_run_case = _core._run_case
run_qualification = _core.run_qualification


def main() -> int:
    args = _parser().parse_args()
    artifact = run_qualification(
        manifest_path=args.manifest.resolve(),
        output_path=args.output.resolve(),
    )
    print(json.dumps(artifact["summary"], ensure_ascii=False, sort_keys=True))
    structural_ok = (
        artifact["summary"]["case_count"] == 12
        and artifact["summary"]["runner_error_cases"] == 0
        and artifact["summary"]["budget_violation_cases"] == 0
        and artifact["summary"]["reviewable_answer_cases"] == 12
    )
    return 0 if structural_ok else 2


def __getattr__(name: str) -> Any:
    return getattr(_core, name)


if __name__ == "__main__":
    from tools.run_rq1c_bounded_qualification import main as guarded_main

    raise SystemExit(guarded_main())