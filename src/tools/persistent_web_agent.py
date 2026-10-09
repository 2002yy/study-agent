"""Persistent GitHub-aware extension of the model-directed web tool agent."""

from __future__ import annotations

import json
import re
import time
from dataclasses import replace
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeout
from typing import TYPE_CHECKING, Any

from src.llm_client import ModelProfile
from src.tools.web_agent import (
    WEB_TOOLS,
    WebToolAgent,
    WebToolTrace,
    _TOOL_SYSTEM_PROMPT,
    _env_flag,
    _env_int,
)
from src.web.query_normalizer import normalize_web_query
from src.web.conversation_query import conversation_search_query, research_topic
from src.web.research_recovery import recover_public_research, recovery_budget
from src.web.semantic_recovery import ResearchEpisode, ResearchSemanticSession

if TYPE_CHECKING:
    from src.application.web_lookup_service import WebLookupService

_PR_REVIEW_CONTEXT_TOOL = {
    "type": "function",
    "function": {
        "name": "github_pr_review_context",
        "description": (
            "Build one source-backed PR review evidence pack from immutable base/head, "
            "review threads, changed symbols, affected tests, and failed checks/jobs. "
            "Returns coverage and uncertainty and never an approval or correctness verdict."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "repo_url": {
                    "type": "string",
                    "description": "Public or explicitly approved GitHub repository URL.",
                },
                "number": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Pull request number.",
                },
                "max_files": {"type": "integer", "minimum": 1, "maximum": 50},
                "max_symbols": {"type": "integer", "minimum": 1, "maximum": 300},
                "max_comments": {"type": "integer", "minimum": 1, "maximum": 100},
                "max_reviews": {"type": "integer", "minimum": 1, "maximum": 100},
                "depth": {"type": "integer", "minimum": 1, "maximum": 4},
                "max_impact_files": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                },
                "max_edges": {"type": "integer", "minimum": 1, "maximum": 500},
                "max_provider_requests": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 128,
                    "description": "Global REST/GraphQL request budget for the composed PR read.",
                },
                "max_pages_per_collection": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "description": "Maximum pages for each reviews/files/checks/jobs collection.",
                },
            },
            "required": ["repo_url", "number"],
            "additionalProperties": False,
        },
    },
}


def _requires_planned_tools(user_input: str) -> bool:
    """Keep the LLM planner for GitHub workflows; use deterministic web search otherwise."""

    lowered = str(user_input or "").casefold()
    return (
        "github.com/" in lowered
        or "pull request" in lowered
        or "代码仓库" in lowered
        or "拉取请求" in lowered
        or re.search(r"\bpr\s*#?\s*\d+\b", lowered) is not None
    )


DEEP_RESEARCH_PREFIX = "请深度研究："


def _requires_deep_research(user_input: str) -> bool:
    """G18 decision 4: explicit prefix or heuristic auto-escalation.

    The sensitivity switch lives in the user's frontend settings (default
    conservative); the deterministic judge in src/web/deep_research.py keeps
    short conversational questions out unconditionally.
    """
    import os

    if os.getenv("WEB_DEEP_RESEARCH_ENABLED", "1").strip().lower() in {
        "0",
        "false",
        "off",
    }:
        return False
    stripped = str(user_input or "").strip()
    if stripped.startswith(DEEP_RESEARCH_PREFIX):
        return True
    # Ordinary explicit research stays on the bounded Lookup/Standard path.
    # Multiple question marks are not authorization to bypass its recovery.
    if research_topic(stripped):
        return False
    try:
        from src.application.helpers import load_frontend_settings
        from src.web.deep_research import should_use_deep_research

        sensitivity = str(
            load_frontend_settings().get("deep_research_sensitivity", "balanced")
        )
        return should_use_deep_research(stripped, sensitivity=sensitivity)
    except Exception:
        return False


class PersistentWebToolAgent(WebToolAgent):
    """Persistent variant that records every tool loop as a durable run."""

    def __init__(
        self,
        *args: Any,
        research_service: WebLookupService | None = None,
        submit_tool_loop: Any = None,
        semantic_completion: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.research_service = research_service
        self.submit_tool_loop = submit_tool_loop
        self.semantic_completion = semantic_completion

    def resolve(
        self,
        user_input: str,
        *,
        model_profile: ModelProfile = "flash",
        conversation_context: str = "",
        owner_thread_id: str | None = None,
        owner_turn_id: str | None = None,
        research_intent: bool = False,
        history_allowed: bool = False,
    ) -> WebToolTrace:
        if not _env_flag("WEB_TOOL_ENABLED", default=True):
            return WebToolTrace(enabled=False)
        from src.web.research.official_resolver import official_plan

        known_source = (getattr(self.gateway, "supports_official_metadata", False) is True
                        and official_plan(user_input) is not None)
        if (
            self.semantic_completion is not None
            and not known_source
            and self.research_service is not None
            and not _requires_planned_tools(user_input)
            and not user_input.strip().startswith(DEEP_RESEARCH_PREFIX)
        ):
            return self._resolve_semantic(
                user_input, conversation_context=conversation_context,
                owner_thread_id=owner_thread_id, owner_turn_id=owner_turn_id,
                history_allowed=history_allowed,
            )
        if _requires_deep_research(user_input) and self.research_service is not None:
            return self._resolve_deep_research(
                user_input,
                owner_thread_id=owner_thread_id,
                owner_turn_id=owner_turn_id,
            )
        focused_query = conversation_search_query(user_input, conversation_context)
        run = None
        operation_id = ""
        persistence_error = ""
        if self.research_service is not None:
            try:
                run = self.research_service.create(
                    focused_query or user_input,
                    owner_thread_id=owner_thread_id,
                    owner_turn_id=owner_turn_id,
                    run_kind="chat_tool_loop",
                )
                operation_id = self.research_service.begin_tool_trace(run.id)
            except Exception as exc:
                persistence_error = (
                    f"ResearchRun create failed: {type(exc).__name__}: {exc}"
                )
        query_context = normalize_web_query(user_input)
        research_instruction = (
            "This is an explicit bounded-research request. Search results are "
            "candidates only. Use web_read on discovered pages before declaring "
            "research complete; if reading fails, leave the result candidate-only "
            "and do not infer facts from snippets."
            if research_intent
            else ""
        )
        system_prompt = (
            f"{_TOOL_SYSTEM_PROMPT}\n"
            f"{research_instruction}\n"
            "Use github_pr_review_context when the user asks for an integrated PR review, "
            "review risk context, unresolved-review mapping, or CI-to-change evidence. "
            "Prefer it over manually combining github_pr and github_change_impact. "
            "It is an evidence pack, not an approval, rejection, correctness, or bug verdict.\n"
            f"Current UTC date: {query_context.as_of_date}.\n"
            f"Canonical user query: {query_context.canonical_query}.\n"
            f"Candidate search variants: "
            f"{json.dumps(query_context.query_variants, ensure_ascii=False)}."
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    f"Conversation context:\n{conversation_context[-3000:]}\n\n"
                    f"User request:\n{user_input}"
                ),
            },
        ]
        try:
            if (
                not _requires_planned_tools(user_input)
                and self.submit_tool_loop is None
            ):
                if not focused_query:
                    raise ValueError("没有可承接的研究主题；请提供要查询的名称或问题")
                budget = recovery_budget(focused_query)
                answer_deadline = time.monotonic() + budget.hard_seconds
                calls = recover_public_research(
                    self.gateway,
                    focused_query,
                    budget=budget,
                    should_cancel=lambda: bool(
                        run is not None
                        and self.research_service is not None
                        and self.research_service.tool_trace_cancel_requested(
                            run.id, operation_id
                        )
                    ),
                )
                trace_error = persistence_error
                if run is not None:
                    preview = WebToolTrace(calls=tuple(calls), run_id=run.id)
                    trace_error = self._record_trace(
                        run.id,
                        calls=calls,
                        source_block=preview.context_block(),
                        operation_id=operation_id,
                    )
                return WebToolTrace(
                    calls=tuple(calls),
                    answer_deadline=answer_deadline,
                    error=("ResearchCancelled: Research cancelled by user"
                           if calls[-1].get("result", {}).get("status") == "cancelled"
                           else trace_error),
                    run_id=(run.id if run else ""),
                )

            total_budget = _env_int(
                "WEB_TOOL_TOTAL_BUDGET_SECONDS",
                12,
                minimum=5,
                maximum=18,
            )
            deadline = time.monotonic() + total_budget
            executor = None
            submit = self.submit_tool_loop
            if submit is None:
                # A per-request executor prevents several timed-out provider calls from
                # starving later research runs in a shared fixed-size pool. Provider
                # requests remain independently bounded by the same deadline.
                executor = ThreadPoolExecutor(
                    max_workers=1,
                    thread_name_prefix="study-agent-web-tool-request",
                )
                submit = executor.submit
            future: Future[list[dict[str, Any]]] = submit(
                self.run_loop,
                messages,
                tools=[*WEB_TOOLS, _PR_REVIEW_CONTEXT_TOOL],
                execute_tool=self._execute,
                model_profile=model_profile,
                task_name="web_tool_planner",
                max_rounds=_env_int(
                    "WEB_TOOL_MAX_ROUNDS",
                    3,
                    minimum=1,
                    maximum=5,
                ),
                should_cancel=(
                    lambda: (
                        time.monotonic() >= deadline
                        or (
                            self.research_service.tool_trace_cancel_requested(
                                run.id, operation_id
                            )
                            if self.research_service is not None
                            and run is not None
                            and operation_id
                            else False
                        )
                    )
                ),
                timeout=float(total_budget),
                request_max_retries=0,
            )
            try:
                calls = future.result(timeout=float(total_budget))
            except FutureTimeout as exc:
                future.cancel()
                raise TimeoutError(
                    f"联网研究超过 {total_budget} 秒总预算，可重试或缩小问题范围"
                ) from exc
            finally:
                if executor is not None:
                    executor.shutdown(wait=False, cancel_futures=True)
            trace_error = persistence_error
            if run is not None:
                preview = WebToolTrace(calls=tuple(calls), run_id=run.id)
                trace_error = self._record_trace(
                    run.id,
                    calls=calls,
                    source_block=preview.context_block(),
                    operation_id=operation_id,
                )
            return WebToolTrace(
                calls=tuple(calls),
                error=trace_error,
                run_id=(run.id if run else ""),
            )
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            if run is not None:
                if (
                    operation_id
                    and self.research_service is not None
                    and self.research_service.tool_trace_cancel_requested(
                        run.id, operation_id
                    )
                ):
                    self.research_service.finish_tool_trace_cancel(run.id, operation_id)
                    error = "ResearchCancelled: Research cancelled by user"
                    persistence_error = ""
                else:
                    persistence_error = self._record_trace(
                        run.id,
                        calls=[],
                        source_block="",
                        error=error,
                        operation_id=operation_id,
                    )
                if persistence_error:
                    error = f"{error}; {persistence_error}"
            return WebToolTrace(error=error, run_id=(run.id if run else ""))

    def _resolve_deep_research(
        self,
        user_input: str,
        *,
        owner_thread_id: str | None = None,
        owner_turn_id: str | None = None,
    ) -> WebToolTrace:
        """G18 deep-research pipeline (decisions 1-16).

        Runs the multi-round WebLookupRun synchronously inside the caller's
        preparation thread; G12 cancellation semantics apply through the run's
        cooperative checkpoints. The final source block carries the rolling
        memo and structured notes so the chat answer is genuinely informed by
        every round, not just the first page of hits.
        """
        stripped = user_input.strip()
        query = (
            stripped[len(DEEP_RESEARCH_PREFIX) :].strip() or stripped
            if stripped.startswith(DEEP_RESEARCH_PREFIX)
            else normalize_web_query(stripped).canonical_query
        )
        error = ""
        calls: list[dict[str, Any]] = []
        run = None
        assert self.research_service is not None
        research_service = self.research_service
        try:
            run = research_service.create(
                query,
                owner_thread_id=owner_thread_id,
                owner_turn_id=owner_turn_id,
                run_kind="deep_research",
                research_mode="deep",
            )
            completed = research_service.execute(run.id)
            deep = completed.research_context.get("deep") or {}
            for attempt in completed.query_attempts:
                calls.append(
                    {
                        "name": "web_search",
                        "arguments": {
                            "query": str(attempt.get("query", "")),
                            "round": attempt.get("round"),
                            "influenced_by_steering": bool(
                                attempt.get("influenced_by_steering")
                            ),
                        },
                        "result": {
                            "status": str(attempt.get("status") or ""),
                            "result_count": int(attempt.get("result_count") or 0),
                        },
                    }
                )
            for note in deep.get("notes", []):
                if isinstance(note, dict):
                    calls.append(
                        {
                            "name": "web_read",
                            "arguments": {"url": note.get("url", "")},
                            "result": {
                                "status": "read",
                                "title": note.get("title", ""),
                                "facts_excerpt": str(note.get("facts", ""))[:300],
                            },
                        }
                    )
            return WebToolTrace(
                calls=tuple(calls),
                run_id=completed.id,
            )
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            cancelled = "ResearchCancelled" in type(exc).__name__ or (
                "ResearchCancelled" in str(exc)
            )
            if cancelled:
                error = "ResearchCancelled: 深度研究已被用户停止"
            return WebToolTrace(
                calls=tuple(calls),
                error=error,
                run_id=(run.id if run else ""),
            )

    def _resolve_semantic(
        self, user_input: str, *, conversation_context: str,
        owner_thread_id: str | None, owner_turn_id: str | None,
        history_allowed: bool,
    ) -> WebToolTrace:
        service = self.research_service
        assert service is not None
        if user_input.strip() in {"停止", "取消", "停止研究", "取消研究", "stop", "cancel"}:
            return WebToolTrace(error="ResearchCancelled: Research cancelled by user")
        prior = service.active_semantic_episode(owner_thread_id or "") if history_allowed else None
        # No stored/assistant-generated evidence is imported into a new run.
        run = service.create(user_input, owner_thread_id=owner_thread_id,
                             owner_turn_id=owner_turn_id, run_kind="chat_tool_loop")
        operation_id = service.begin_tool_trace(run.id)
        episode = prior or ResearchEpisode(
            task_id=run.id, thread_id=owner_thread_id or "",
            original_question=user_input.strip(),
            questions=[{"id": "rq-question", "question": user_input.strip()[:500]}],
            source_run_id=run.id, source_run_version=run.version,
        )
        budget = recovery_budget(episode.original_question)
        current_budget = recovery_budget(user_input)
        if current_budget.hard_seconds > budget.hard_seconds:
            budget = current_budget
        started = time.monotonic()
        # B planning has a separately bounded overhead allowance. Credit only
        # actual elapsed planning time; never renew the research window per tool.
        planning_allowance = 20.0
        answer_deadline = started + budget.hard_seconds + planning_allowance
        session = ResearchSemanticSession(
            self.semantic_completion,
            deadline=answer_deadline - budget.finalization_reserve,
            should_cancel=lambda: service.tool_trace_cancel_requested(run.id, operation_id),
            history_allowed=history_allowed,
        )
        calls: list[dict[str, Any]] = []
        error = ""
        plan: list[dict[str, str]] = []
        focused = ""
        admitted = False
        try:
            decision = session.plan(episode, user_input, new_task_id=run.id,
                                         history=conversation_context if prior and not research_topic(user_input) else "",
                                         active_task_exists=prior is not None)
            from src.web.conversation_query import is_research_resume

            if is_research_resume(user_input) and decision.intent == "NEW_RESEARCH":
                raise ValueError("retry_is_not_new_topic")
            if decision.intent in {"ABSTAIN", "ANSWER"}:
                raise ValueError("semantic_abstain_no_new_evidence")
            if decision.intent == "NEW_RESEARCH":
                episode = ResearchEpisode(
                    task_id=run.id, thread_id=owner_thread_id or "",
                    original_question=user_input.strip(), questions=decision.unresolved_questions,
                    constraints=decision.constraints_delta,
                    previous_task_id=prior.task_id if prior else "",
                    source_run_id=run.id, source_run_version=run.version,
                )
            elif prior is None:
                raise ValueError("no_active_episode")
            else:
                old = {q["id"]: q["question"] for q in episode.questions}
                proposed = {q["id"]: q["question"] for q in decision.unresolved_questions}
                if not set(old) <= set(proposed):
                    raise ValueError("original_rq_removed")
                frozen_questions = [{"id": q["id"], "question": old.get(q["id"], q["question"])}
                                    for q in decision.unresolved_questions]
                episode = replace(episode, questions=frozen_questions,
                                  constraints={**episode.constraints, **decision.constraints_delta})
            plan = decision.proposed_queries
            focused = episode.original_question
            admitted = True
        except Exception as exc:
            # Only explicit subjects or proven whole-turn retry controls may use
            # the old deterministic path. Unknown follow-ups never become queries.
            from src.web.conversation_query import is_research_resume

            if service.tool_trace_cancel_requested(run.id, operation_id):
                service.finish_tool_trace_cancel(run.id, operation_id)
                return WebToolTrace(calls=tuple(calls), error="ResearchCancelled: Research cancelled by user", run_id=run.id)
            if prior and is_research_resume(user_input):
                focused = prior.original_question
                episode = prior
            elif research_topic(user_input) and len(user_input.strip()) <= 4096:
                focused = user_input.strip()
                episode = ResearchEpisode(
                    task_id=run.id, thread_id=owner_thread_id or "", original_question=focused,
                    questions=[{"id": "rq-question", "question": focused[:500]}],
                    previous_task_id=prior.task_id if prior else "",
                    source_run_id=run.id, source_run_version=run.version,
                )
            else:
                error = f"SemanticRecovery blocked: {type(exc).__name__}: {exc}"
            calls.append({"name": "research_semantic_fallback", "arguments": {},
                          "result": {"reason": type(exc).__name__, "known_subject": bool(focused)}})
        planning_elapsed = max(0.0, time.monotonic() - started)
        planning_credit = min(planning_allowance, planning_elapsed)
        research_started = started + planning_credit
        if focused:
            # A newly interpreted topic cannot extend the deadline inherited from
            # the current run. A short new topic may reduce it to Lookup.
            budget = recovery_budget(focused)
            answer_deadline = min(answer_deadline, research_started + budget.hard_seconds)
            session.deadline = answer_deadline - budget.finalization_reserve
            session.episode = episode
            calls.extend(recover_public_research(
                self.gateway, focused, budget=budget, started_at=research_started,
                answer_deadline=answer_deadline, semantic_session=session,
                query_plan=plan, should_cancel=session.should_cancel,
            ))
            attempts = [*episode.attempts, *[
                {"query": str(c["arguments"]["query"])[:500],
                 "outcome": str(c["result"].get("status", "unknown"))[:100]}
                for c in calls if c.get("name") == "web_search"
            ]][-8:]
            from src.web.tool_evidence import _public_url

            leads = [{"url": str(c["arguments"].get("url", ""))[:500],
                      "status": "related_read" if c["result"].get("answer_eligible") else "unrelated_or_failed_read",
                      "reason": str(c["result"].get("adequacy_reason") or c["result"].get("error") or "")[:300],
                      "summary": str(c["result"].get("content") or c["result"].get("readme") or "")[:300]}
                     for c in calls if c.get("name") == "web_read" and _public_url(c.get("arguments", {}).get("url"))][-5:]
            episode = replace(episode, attempts=attempts, source_leads=leads)
        calls.append({"name": "research_semantics", "arguments": {}, "result": {
            "model_calls": len(session.events), "events": session.events,
            "intent": session.decision.intent if admitted and session.decision else "FALLBACK",
            "decision_admitted": admitted,
            "task_id": episode.task_id, "question_coverage": sorted(session.body_questions),
            "coverage_kind": "relevance_only_not_support_or_adequacy",
            "time_budget": {
                "planning_allowance_seconds": planning_allowance,
                "planning_elapsed_seconds": planning_elapsed,
                "credited_seconds": planning_credit,
                "research_hard_seconds": budget.hard_seconds,
                "total_hard_seconds": budget.hard_seconds + planning_allowance,
                "finalization_reserve_seconds": budget.finalization_reserve,
                "answer_deadline": answer_deadline,
                "research_started": research_started,
                "automatic_extension": "actual_planning_overhead_once",
            },
        }})
        if session.should_cancel():
            service.finish_tool_trace_cancel(run.id, operation_id)
            return WebToolTrace(calls=tuple(calls), error="ResearchCancelled: Research cancelled by user", run_id=run.id)
        preview = WebToolTrace(calls=tuple(calls), run_id=run.id)
        try:
            service.record_tool_trace(
                run.id, calls=calls, source_block=preview.context_block(), error=error,
                operation_id=operation_id, semantic_episode=episode.to_dict() if focused or prior else None,
                semantic_events=session.events,
            )
        except Exception as exc:
            error = f"ResearchRun record failed: {type(exc).__name__}: {exc}"
        return WebToolTrace(calls=tuple(calls), error=error, run_id=run.id, answer_deadline=answer_deadline)

    def _record_trace(
        self,
        run_id: str,
        *,
        calls: list[dict[str, Any]],
        source_block: str,
        error: str = "",
        operation_id: str = "",
    ) -> str:
        if self.research_service is None:
            return ""
        try:
            self.research_service.record_tool_trace(
                run_id,
                calls=calls,
                source_block=source_block,
                error=error,
                operation_id=operation_id or None,
            )
        except Exception as exc:
            return f"ResearchRun persistence failed: {type(exc).__name__}: {exc}"
        return ""

    def _execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name != "github_pr_review_context":
            return super()._execute(name, arguments)
        method = self._optional(name)
        if method is None:
            return {"ok": False, "error": "github_pr_review_context_unavailable"}
        return method(
            str(arguments.get("repo_url", "")),
            int(arguments.get("number", 0)),
            max_files=int(arguments.get("max_files", 20)),
            max_symbols=int(arguments.get("max_symbols", 100)),
            max_comments=int(arguments.get("max_comments", 100)),
            max_reviews=int(arguments.get("max_reviews", 100)),
            depth=int(arguments.get("depth", 2)),
            max_impact_files=int(arguments.get("max_impact_files", 40)),
            max_edges=int(arguments.get("max_edges", 160)),
            max_provider_requests=int(arguments.get("max_provider_requests", 24)),
            max_pages_per_collection=int(arguments.get("max_pages_per_collection", 10)),
        )
