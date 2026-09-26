"""Compatibility exports for the callable-boundary RQ1-C guardrails.

Qualification safety now lives in the core callable contract itself, so importing
this legacy module never patches another module or changes execution semantics.
"""

from __future__ import annotations

from tools import rq1c_qualification_guardrails as _guardrails
from tools import run_rq1c_bounded_qualification_impl as _impl

MAX_MODEL_CALLS = _guardrails.MAX_MODEL_CALLS
HARD_TIMEOUT_SECONDS = _guardrails.HARD_TIMEOUT_SECONDS
QualificationModelBudgetExhausted = _guardrails.QualificationModelBudgetExhausted
QualificationHardDeadlineReached = _guardrails.QualificationHardDeadlineReached
_AnswerStageBudget = _guardrails._AnswerStageBudget
_ResearchBudgetProxy = _guardrails._ResearchBudgetProxy
_evidence_rows = _impl._evidence_rows
_load_manifest = _impl._load_manifest
_observed_read_count = _impl._observed_read_count
_provider_audit = _impl._provider_audit
_source_rows = _impl._source_rows
_unavailable_answer_surface = _impl._unavailable_answer_surface
_answer_stage_model_calls = _impl._answer_stage_model_calls
_production_answer_surface = _impl._production_answer_surface
_production_chat_command = _impl._production_chat_command
_active_context = _impl._active_context
_git_sha = _impl._git_sha
_parser = _impl._parser
run_qualification = _impl.run_qualification


def main() -> int:
    return _impl.main()


if __name__ == "__main__":
    raise SystemExit(main())