"""Public entrypoint for the strictly bounded RQ1-C qualification."""

from __future__ import annotations

import json
from typing import Any

from tools import rq1c_qualification_guardrails as _guardrails
from tools import run_rq1c_bounded_qualification_core as _core

MAX_MODEL_CALLS = _guardrails.MAX_MODEL_CALLS
HARD_TIMEOUT_SECONDS = _guardrails.HARD_TIMEOUT_SECONDS
QualificationModelBudgetExhausted = _guardrails.QualificationModelBudgetExhausted
QualificationHardDeadlineReached = _guardrails.QualificationHardDeadlineReached
_AnswerStageBudget = _guardrails._AnswerStageBudget
_ResearchBudgetProxy = _guardrails._ResearchBudgetProxy
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
_git_sha = _core._git_sha
_parser = _core._parser

# Preserve the public monkeypatch seam used by focused budget tests. Core-run
# budgets call the guardrails module, whose proxy resolves this module global at
# physical provider dispatch time.
_production_chat = _guardrails._production_chat


def _production_chat_proxy(messages: list[dict], **kwargs: Any) -> str:
    return _production_chat(messages, **kwargs)


_guardrails._production_chat = _production_chat_proxy
_guardrails.configure_default_binding_rows_provider(
    lambda run: _core.research_binding_rows(run)
)

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


if __name__ == "__main__":
    raise SystemExit(main())
