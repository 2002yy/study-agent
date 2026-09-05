"""Public entrypoint for the strictly bounded RQ1-C qualification."""

from __future__ import annotations

from typing import Any

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

# Preserve the public monkeypatch seam used by focused budget tests. Core-run
# budgets call the guardrails module, whose proxy resolves this module global at
# physical provider dispatch time.
_production_chat = _guardrails._production_chat


def _production_chat_proxy(messages: list[dict], **kwargs: Any) -> str:
    return _production_chat(messages, **kwargs)


_guardrails._production_chat = _production_chat_proxy
_guardrails.configure_default_binding_rows_provider(
    lambda run: _impl.research_binding_rows(run)
)

run_qualification = _impl.run_qualification


def main() -> int:
    return _impl.main()


if __name__ == "__main__":
    raise SystemExit(main())