"""Policy-aware chat preparation.

Only the preparation stage differs from ``ChatService``. Generation,
interruption, retry and atomic completion reuse the established lifecycle.
"""

from __future__ import annotations

from contextlib import suppress
from copy import deepcopy
from dataclasses import dataclass, replace
import logging
import os
from typing import Any, AsyncIterator, Iterator, cast

from src.application.chat_service import (
    ChatCommand,
    ChatService,
    PreparedChatTurn,
    TurnCancelled,
    _continuation_instruction,
    _normalized_turn_truth,
    _persisted_generation_calls,
    _poll_cancel,
    _preferred_partial_reply,
    _previous_assistant_role,
    _route_generation_calls,
    _session_settings,
    _tool_context,
    _web_context_provenance,
)
from src.application.helpers import load_frontend_settings
from src.context_builder import chat_history_limit, trim_duplicate_current_user_input
from src.domain.runtime_entities import ChatThread, ChatTurn, new_id, utc_now
from src.external_data_policy import decide_external_data
from src.pedagogy.evidence import build_evidence_units
from src.pedagogy.types import LearningState
from src.rag.cancellation import RetrievalCancelled
from src.rag.query_plan import build_retrieval_query_plan
from src.task_contract import resolve_turn_task_contract
from src.task_intent import SourcePolicy, TaskIntent
from src.tools.web_agent import WebToolTrace

WEB_CONSENT_MARKER = "__STUDY_AGENT_WEB_CONSENT__"
EXTERNAL_DATA_AUDIT_VERSION = 2

_SOURCE_POLICIES: set[str] = {
    "model_only",
    "local_only",
    "web_only",
    "local_and_web",
    "ask_before_external",
}


@dataclass(frozen=True)
class PolicyChatCommand(ChatCommand):
    web_policy: str | None = None
    web_consent: bool = False
    cloud_context_policy: str | None = None
    memory_policy: str | None = None
    # G16 decision 6: explicit per-turn consent signal from the frontend
    # confirm dialog; persisted server-side as a session-level grant.
    memory_consent: bool = False
    task_intent: TaskIntent | None = None
    research_sources: dict[str, Any] | None = None


def _source_policy(route: dict[str, Any]) -> SourcePolicy:
    contract = route.get("task_contract")
    if not isinstance(contract, dict):
        return "local_and_web"
    value = str(contract.get("source_policy", "local_and_web"))
    if value not in _SOURCE_POLICIES:
        return "local_and_web"
    return cast(SourcePolicy, value)


def _restore_persisted_research_truth(
    command: PolicyChatCommand,
    persisted_turn: ChatTurn | None,
) -> PolicyChatCommand:
    """Prevent continuation/retry from switching ResearchRun evidence owners."""

    if persisted_turn is None:
        return command
    web_context = persisted_turn.rag_snapshot.get("web_context")
    persisted_run_id = ""
    if isinstance(web_context, dict):
        persisted_run_id = str(web_context.get("run_id", "") or "").strip()
    requested_run_id = str(command.web_context_run_id or "").strip()
    if requested_run_id:
        if not persisted_run_id or requested_run_id != persisted_run_id:
            raise ValueError(
                "Continuation/retry cannot switch ResearchRun evidence: "
                f"{requested_run_id}"
            )
        persisted_sources = persisted_turn.rag_snapshot.get("research_sources")
        sources = (
            deepcopy(persisted_sources)
            if isinstance(persisted_sources, dict)
            else deepcopy(command.research_sources)
            if isinstance(command.research_sources, dict)
            else None
        )
        return replace(command, research_sources=sources)
    return replace(command, research_sources=None)


def _configured_llm_provider() -> str:
    return os.getenv("LLM_PROVIDER_PROFILE", "openai").strip().lower() or "openai"


def _semantic_external_call(run: Any) -> dict[str, Any] | None:
    status = str(getattr(run, "semantic_review_status", "legacy_unknown"))
    if status not in {"blocked_by_policy", "attempted_failed", "completed"}:
        return None
    categories = list(getattr(run, "semantic_review_data_categories", ()) or ())
    counts = {
        "learner_input": 1 if str(getattr(run, "learner_input", "")) else 0,
        "learning_objective": 1 if str(getattr(run, "objective", "")) else 0,
        "learning_protocol": 1 if str(getattr(run, "protocol", "")) else 0,
        "expected_concepts": len(getattr(run, "expected_concepts", ()) or ()),
        "evidence_refs": len(getattr(run, "evidence", ()) or ()),
    }
    return {
        "call_id": "semantic_evaluation:1",
        "purpose": "semantic_evaluation",
        "provider": str(getattr(run, "semantic_review_provider", "") or "unknown"),
        "data_categories": categories,
        "data_counts": {key: counts[key] for key in categories},
        "status": status,
        "result": status,
    }


def _web_external_calls(web_call_rows: list[Any]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for row in web_call_rows:
        if not isinstance(row, dict) or row.get("name") != "web_search":
            continue
        raw_result = row.get("result")
        result: dict[str, Any] = raw_result if isinstance(raw_result, dict) else {}
        providers = result.get("providers_attempted") or ["unknown"]
        for provider in providers:
            raw_status = str(result.get("status") or "completed")
            status = {
                "ok": "completed",
                "empty": "completed_empty",
                "unavailable": "attempted_failed",
            }.get(raw_status, raw_status)
            calls.append(
                {
                    "call_id": f"web_search:{len(calls) + 1}",
                    "purpose": "web_search",
                    "provider": str(provider).split(":", 1)[0] or "unknown",
                    "data_categories": ["search_query"],
                    "data_counts": {"search_query": 1},
                    "status": status,
                    "result": status,
                }
            )
    return calls


def _embedding_external_call(rag: dict[str, Any]) -> dict[str, Any] | None:
    raw_debug = rag.get("debug")
    debug: dict[str, Any] = raw_debug if isinstance(raw_debug, dict) else {}
    raw_embedding = debug.get("external_embedding")
    if not isinstance(raw_embedding, dict):
        return None
    embedding: dict[str, Any] = raw_embedding
    return {
        "call_id": "query_embedding:1",
        "purpose": str(embedding.get("purpose") or "query_embedding"),
        "provider": str(embedding.get("provider") or "unknown"),
        "data_categories": list(embedding.get("data_categories") or []),
        "data_counts": {"retrieval_query": 1},
        "status": str(embedding.get("status") or "unknown"),
        "result": str(embedding.get("status") or "unknown"),
    }


def _sent_categories(calls: list[dict[str, Any]]) -> set[str]:
    transmitted = {
        "attempted",
        "attempted_failed",
        "completed",
        "completed_empty",
        "failed",
        "interrupted",
    }
    return {
        str(category)
        for call in calls
        if str(call.get("status")) in transmitted
        for category in call.get("data_categories", [])
    }


def _refresh_execution_truth(snapshot: dict[str, Any]) -> dict[str, Any]:
    calls = [item for item in snapshot.get("external_calls", []) if isinstance(item, dict)]
    categories = _sent_categories(calls)
    return {
        **snapshot,
        "external_data_audit_version": EXTERNAL_DATA_AUDIT_VERSION,
        "external_calls": calls,
        "web_search_performed": any(
            call.get("purpose") == "web_search"
            and call.get("status")
            in {"attempted", "attempted_failed", "completed", "completed_empty", "failed"}
            for call in calls
        ),
        "history_sent_to_model": "recent_chat" in categories,
        "learning_state_sent_to_model": bool(
            categories
            & {"learning_state", "learning_objective", "learning_protocol", "expected_concepts"}
        ),
        "memory_context_sent_to_model": "memory_context" in categories,
        "local_evidence_sent_to_model": "local_evidence" in categories,
    }


class ExternalDataPolicyChatService(ChatService):
    """Apply user-controlled source and model-context gates."""

    @staticmethod
    def _retrieve_session_attachments(
        query: str,
        *,
        thread_id: str,
        enabled: bool,
        top_k: int,
        min_score: float,
        should_cancel: Any = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        """Thread-scoped temporary attachment retrieval (G14 gate 2/7).

        Failures degrade to "no attachments" instead of blocking the turn;
        cooperative cancellation always propagates.
        """
        if not enabled:
            return [], None
        try:
            from src.application.runtime_repository import (
                get_session_attachment_service,
            )

            service = get_session_attachment_service()
            hits = service.retrieve_for_thread(
                query,
                thread_id,
                top_k=max(1, top_k),
                min_score=min_score,
                should_cancel=should_cancel,
            )
        except RetrievalCancelled:
            raise
        except Exception:  # noqa: BLE001 - attachments must not break turns
            return [], {
                "status": "error",
                "count": 0,
                "attachment_ids": [],
            }
        provenance = {
            "status": "found" if hits else "none",
            "count": len(hits),
            "attachment_ids": service.attachment_ids_in_results(hits),
        }
        return [result.to_dict() for result in hits], provenance

    def start_turn(self, command: ChatCommand) -> PreparedChatTurn:
        policy_command = (
            command
            if isinstance(command, PolicyChatCommand)
            else PolicyChatCommand(**command.__dict__)
        )
        validated_command, existing, retry_parent = self._validate_turn_command(
            policy_command
        )
        command = cast(PolicyChatCommand, validated_command)
        from src.application.review_turn_context import resolve_review_answer, review_evaluation_inputs

        review_binding = resolve_review_answer(self.repository, command, existing or retry_parent)
        runtime_modes = self._runtime_modes(command.performance_mode)
        context_mode = command.context_mode or runtime_modes.context_mode
        saved_policy = load_frontend_settings()
        effective_web_policy = command.web_policy or str(
            saved_policy.get("web_policy", "auto")
        )
        effective_cloud_context_policy = command.cloud_context_policy or str(
            saved_policy.get("cloud_context_policy", "allow_local_evidence")
        )
        marker_consent = command.web_context.strip() == WEB_CONSENT_MARKER
        manual_web_context = "" if marker_consent else command.web_context
        effective_web_consent = command.web_consent or marker_consent
        effective_memory_policy = command.memory_policy or str(
            saved_policy.get("memory_policy", "auto")
        )
        settings = {
            **_session_settings(command, context_mode),
            "webPolicy": effective_web_policy,
            "cloudContextPolicy": effective_cloud_context_policy,
            "memoryPolicy": effective_memory_policy,
        }
        turn_id = command.turn_id or command.continuation_of_turn_id or new_id("turn")
        is_continuation = bool(command.continuation_of_turn_id)
        prior_generation_calls = (
            _persisted_generation_calls(existing)
            if is_continuation and existing is not None
            else 0
        )
        thread_id = command.thread_id or (
            existing.thread_id if existing is not None and is_continuation else ChatThread().id
        )
        if existing is not None and not is_continuation:
            raise ValueError(f"Chat turn already exists: {turn_id}")
        thread = self.repository.ensure_chat_thread(thread_id)
        learning_state = LearningState.from_dict(thread.learning_state)
        persisted_turn = existing if is_continuation else retry_parent
        command = _restore_persisted_research_truth(command, persisted_turn)
        task_contract = resolve_turn_task_contract(
            user_input=command.user_input,
            state=learning_state,
            explicit_override=command.task_intent,
            persisted_route=(persisted_turn.route_snapshot if persisted_turn else None),
        )
        if review_binding is not None:
            from src.task_intent import default_contract

            task_contract = replace(default_contract("explain_back"), source_policy="local_only")
        operation_id = command.operation_id or new_id("op")
        thread = self.repository.acquire_chat_operation(
            thread.id,
            operation_id,
            settings_snapshot={
                **settings,
                "conversationInstruction": command.conversation_instruction,
                "taskIntent": task_contract.task_intent,
            },
        )
        reserved_existing = existing
        if existing is None:
            self.repository.add_chat_turn(
                ChatTurn(
                    id=turn_id,
                    thread_id=thread.id,
                    user_message=command.user_input,
                    assistant_message="",
                    status="pending",
                    parent_turn_id=retry_parent.id if retry_parent else None,
                    operation_id=operation_id,
                    conversation_instruction=command.conversation_instruction,
                    created_at=utc_now(),
                    updated_at=utc_now(),
                )
            )
        else:
            reassign = self.repository.reassign_chat_turn_operation(
                turn_id,
                expected_operation_id=existing.operation_id,
                new_operation_id=operation_id,
            )
            if reassign is None:
                self.repository.release_chat_operation(thread.id, operation_id)
                raise ValueError(f"Chat turn cannot continue from current state: {turn_id}")
            reserved_existing = reassign
        cancel_check = self._make_cancel_check(turn_id, operation_id)
        # G16 decisions 5-8: per-session memory consent. The grant lives in
        # the thread snapshot; a fresh frontend consent marker persists it
        # once via CAS. A failed CAS fails the turn closed (declined).
        memory_consent_granted = bool(
            (thread.settings_snapshot or {}).get("memory_consent_granted")
        )
        if (
            effective_memory_policy == "ask"
            and not memory_consent_granted
            and command.memory_consent
        ):
            try:
                self.repository.grant_session_memory_consent(thread.id)
                memory_consent_granted = True
            except Exception:  # noqa: BLE001 - decision 7 fail-closed
                logging.getLogger(__name__).warning(
                    "Memory consent grant failed for %s; turn declined",
                    thread.id,
                    exc_info=True,
                )
        base_reply = ""
        try:
            cancel_check("route")
            route = self.dependencies.route_request(
                user_input=command.user_input,
                selected_role=command.selected_role,
                selected_mode=command.selected_mode,
                selected_model=command.selected_model,
                runtime_modes=runtime_modes,
                previous_role=_previous_assistant_role(command.chat_history),
                previous_mode=command.previous_mode or self._previous_persisted_mode(thread.id),
                keep_current_role=command.keep_current_role,
                task_contract=task_contract,
            )
            route = {**route, "task_contract": task_contract.to_dict()}
            decision = decide_external_data(
                web_policy=effective_web_policy,
                web_consent=effective_web_consent,
                cloud_context_policy=effective_cloud_context_policy,
                task_source_policy=_source_policy(route),
                memory_policy=effective_memory_policy,
                memory_consent=memory_consent_granted,
            )
            route = {**route, "external_data_policy": decision.to_dict()}
            if review_binding is not None:
                route["review"] = review_binding.snapshot("answer")
            expected_concepts = tuple(
                str(item)
                for item in learning_state.payload.get(
                    "expected_concepts", learning_state.confirmed_points
                )
            )
            evidence_ids = self._previous_disclosed_evidence_ids(thread.id)
            eval_state, expected_concepts, evidence_ids = review_evaluation_inputs(
                review_binding, learning_state, expected_concepts, evidence_ids
            )
            cancel_check("pedagogy_evaluate")
            learner_evaluation = cast(
                Any, self.dependencies.pedagogy_evaluation
            ).evaluate_learner(
                learner_input=command.user_input,
                state=eval_state,
                expected_concepts=expected_concepts,
                evidence=evidence_ids,
                task_contract=task_contract,
                semantic_review_allowed=decision.memory_allowed,
            )
            learning_state = LearningState.from_dict(
                {
                    **learning_state.to_dict(),
                    "payload": {
                        **learning_state.payload,
                        "pedagogy_evaluation": learner_evaluation.to_dict(),
                    },
                }
            )
            pedagogy_plan, next_learning_state = cast(
                Any, self.dependencies.pedagogy_engine
            ).plan(
                user_input=command.user_input,
                mode=route["mode"],
                state=learning_state,
                task_contract=task_contract,
            )
            route = {
                **route,
                "pedagogy": pedagogy_plan.to_dict(),
                "learning_state": next_learning_state.to_dict(),
                "answer_generation_calls": prior_generation_calls,
            }
            role_prompt = self.dependencies.build_role_prompt(
                route["role"],
                scene=command.scene,
                relationship_mode=command.relationship_mode,
            )
            memory_bundle = (
                self.dependencies.read_memory_bundle(context_mode)
                if decision.memory_allowed
                else {}
            )
            retrieval_plan = build_retrieval_query_plan(
                command.user_input,
                state=learning_state,
                plan=pedagogy_plan,
            )
            cancel_check("retrieval")
            rag_result = self.dependencies.retrieve_local_knowledge(
                retrieval_plan.private_query,
                enabled=(command.rag_enabled and decision.local_retrieval_allowed),
                force=(retrieval_plan.force_retrieval and decision.local_retrieval_allowed),
                top_k=command.rag_chat_top_k or command.rag_top_k,
                retrieval_mode=command.rag_retrieval_mode,
                min_score=command.rag_min_score,
                should_cancel=_poll_cancel(self.repository, turn_id, operation_id),
            )
            rag = rag_result.to_dict()
            rag["query_plan"] = retrieval_plan.to_dict()
            # G14: thread-scoped temporary attachments join retrieval with
            # priority over the long-term corpus (acceptance gate 2). Only
            # `ready` chunks exist in the temp index, so processing files
            # are invisible here (gate 7); failed fragments can never leak.
            attachment_results, attachment_provenance = (
                self._retrieve_session_attachments(
                    retrieval_plan.private_query,
                    thread_id=thread.id,
                    enabled=(command.rag_enabled and decision.local_retrieval_allowed),
                    top_k=command.rag_chat_top_k or command.rag_top_k,
                    min_score=command.rag_min_score,
                    should_cancel=_poll_cancel(
                        self.repository, turn_id, operation_id
                    ),
                )
            )
            if attachment_results:
                rag["results"] = [*attachment_results, *(rag.get("results") or [])]
            if attachment_provenance is not None:
                rag["session_attachments"] = attachment_provenance
            cancel_check("web_tools")
            if decision.web_allowed:
                web_tools = self.dependencies.resolve_web_tools(
                    command.user_input,
                    model_profile=route["model_profile"],
                    conversation_context=(
                        _tool_context(command.chat_history)
                        if decision.history_allowed
                        else ""
                    ),
                    owner_thread_id=thread.id,
                    owner_turn_id=turn_id,
                    research_intent=task_contract.task_intent == "research",
                )
            else:
                web_tools = WebToolTrace(enabled=False)
            rag["web_tools"] = {
                **web_tools.to_dict(),
                "policy_reason": decision.reason,
            }
            web_tool_error = str(rag["web_tools"].get("error") or "")
            continuation_instruction = _continuation_instruction(command)
            context_blocks: list[str] = []
            web_context = "\n\n".join(
                part
                for part in (
                    manual_web_context if decision.web_allowed else "",
                    web_tools.context_block(),
                )
                if part.strip()
            )
            rag["web_context"] = _web_context_provenance(
                manual_web_context if decision.web_allowed else "",
                command.web_context_run_id,
            )
            if decision.web_allowed and command.research_sources:
                rag["research_sources"] = deepcopy(command.research_sources)
            evidence_rag = (
                rag
                if decision.local_evidence_to_model_allowed
                else {**rag, "results": []}
            )
            evidence_units = build_evidence_units(
                rag=evidence_rag,
                web_context=web_context,
            )
            disclosed = self.dependencies.disclosure_policy.select(
                units=evidence_units,
                plan=pedagogy_plan,
            )
            web_call_rows = web_tools.to_dict().get("calls") or []
            local_evidence_units = [
                unit for unit in evidence_units if unit.type == "document_chunk"
            ]
            sent_history = (
                trim_duplicate_current_user_input(
                    command.chat_history,
                    command.user_input,
                )[-chat_history_limit(runtime_modes):]
                if decision.history_allowed
                else []
            )
            external_data_execution = {
                **decision.to_dict(),
                "history_message_count": len(sent_history),
                "local_evidence_chunk_count": len(local_evidence_units),
                # G16 decision 10: why memory did or did not enter context.
                # granted = bundle used; declined = user policy/refusal kept
                # it out (off or unanswered ask); not_required = another gate
                # (non-allow context policy) made memory moot this turn.
                "memory_consent": (
                    "granted"
                    if memory_bundle and decision.memory_allowed
                    else "declined"
                    if effective_memory_policy in {"off", "ask"}
                    else "not_required"
                ),
                "answer_data_categories": [
                    "current_question",
                    *(["recent_chat"] if sent_history else []),
                    *(["learning_state"] if decision.memory_allowed else []),
                    *(["memory_context"] if memory_bundle else []),
                    *(["local_evidence"] if local_evidence_units else []),
                    *(["web_results"] if web_context else []),
                ],
                "external_calls": [
                    *(
                        [semantic_call]
                        if (semantic_call := _semantic_external_call(learner_evaluation))
                        else []
                    ),
                    *_web_external_calls(web_call_rows),
                    *(
                        [embedding_call]
                        if (embedding_call := _embedding_external_call(rag))
                        else []
                    ),
                ],
            }
            external_data_execution = _refresh_execution_truth(external_data_execution)
            route["external_data_policy"] = external_data_execution
            rag["external_data_policy"] = external_data_execution
            route["evidence_disclosure"] = disclosed.policy
            if disclosed.private_context:
                context_blocks.append(disclosed.private_context)
            if disclosed.context:
                context_blocks.append(disclosed.context)
            if decision.web_allowed and (
                task_contract.task_intent == "research"
                or web_tools.to_dict().get("recovery") is not None
            ):
                context_blocks.append(
                    "用户已授权本轮联网研究。优先依据实际读取的相关来源回答原研究主题；"
                    "不要因模型不认识术语就让用户先解释、提供链接或再次授权搜索。"
                    "简短追问与催促承接前文主题。搜索或读取失败时简要说明实际失败，"
                    "不要归咎于用户命名错误；未找到不能证明不存在。只有已检索仍有"
                    "无法区分的多个指代时才提出必要澄清，不长篇重复证据规则。"
                    "本轮受限检索恢复已执行；直接给出可支持的回答或简短失败说明，"
                    "不要以‘是否要我去查’或‘如果你愿意我可以继续搜’结束回答。"
                )
            if decision.web_allowed and not web_tools.used:
                if task_contract.task_intent == "research":
                    context_blocks.append(
                        "这是明确研究请求，但本轮没有取得任何已读取正文或结构化一手证据。"
                        "只能报告研究未完成、候选数量和读取缺口；不得依据搜索摘要或模型既有"
                        "知识输出具体事实、比较、价格、日期、能力判断或确定性结论。"
                    )
                elif web_tool_error:
                    context_blocks.append(
                        "联网搜索未获得可用于回答的已读来源。必须明确说明本回答未使用联网"
                        "来源；不得声称已经查证或依据搜索摘要得出结论。"
                    )
            if continuation_instruction:
                context_blocks.append(continuation_instruction)
            model_learning_state = (
                learning_state
                if decision.memory_allowed
                else LearningState(
                    protocol=learning_state.protocol,
                    protocol_version=learning_state.protocol_version,
                )
            )
            model_pedagogy_plan = (
                pedagogy_plan
                if decision.memory_allowed
                else replace(
                    pedagogy_plan,
                    learner_claim="",
                    unresolved_gap="",
                    target_understanding=command.user_input,
                    evidence_ids=(),
                )
            )
            messages = self.dependencies.build_messages(
                user_input=command.user_input,
                role_prompt=role_prompt,
                mode=route["mode"],
                memory_bundle=memory_bundle,
                chat_history=(command.chat_history if decision.history_allowed else []),
                relationship_mode=command.relationship_mode,
                runtime_modes=runtime_modes,
                context_mode=context_mode,
                rag_context="\n\n".join(context_blocks),
                scene=command.scene,
                conversation_instruction=command.conversation_instruction,
                pedagogy_plan=model_pedagogy_plan,
                learning_state=model_learning_state,
            )
            base_reply = ""
            if is_continuation:
                base_reply = _preferred_partial_reply(
                    existing.assistant_message if existing else "",
                    command.partial_reply,
                )
            pedagogy_snapshot = {
                **pedagogy_plan.to_dict(),
                "learning_state_before": learning_state.to_dict(),
                "learning_state_after": next_learning_state.to_dict(),
                "evidence_disclosure": disclosed.policy,
                "evidence_units": list(disclosed.units),
                "external_data_policy": external_data_execution,
                "task_contract": task_contract.to_dict(),
            }
            streaming_truth = _normalized_turn_truth(
                turn=reserved_existing,
                fallback_turn_id=turn_id,
                thread_id=thread.id,
                user_message=command.user_input,
                assistant_message=base_reply,
                status="streaming",
                role=route["role"],
                mode=route["mode"],
                model=route["model_profile"],
                route_snapshot=route,
                rag_snapshot=rag,
                pedagogy_snapshot=pedagogy_snapshot,
                parent_turn_id=retry_parent.id if retry_parent else None,
                operation_id=operation_id,
                conversation_instruction=command.conversation_instruction,
            )
            expected = "pending" if reserved_existing is None or reserved_existing.status == "pending" else "interrupted"
            streaming = self.repository.update_chat_turn(
                turn_id,
                assistant_message=base_reply,
                status="streaming",
                role=route["role"],
                mode=route["mode"],
                model=route["model_profile"],
                route_snapshot=route,
                rag_snapshot=streaming_truth.rag_snapshot,
                pedagogy_snapshot=pedagogy_snapshot,
                operation_id=operation_id,
                expected_operation_id=operation_id,
                enforce_operation_owner=True,
                expected_status=expected,
                forbid_cancel_requested=True,
            )
            if streaming is None:
                raise RuntimeError(f"Chat turn was not created: {turn_id}")
        except (TurnCancelled, RetrievalCancelled) as exc:
            self._settle_cancelled_preparation(
                turn_id=turn_id,
                operation_id=operation_id,
                stage=getattr(exc, "stage", "retrieval"),
                assistant_message=base_reply,
            )
            raise
        except Exception:
            settled_failed = False
            with suppress(Exception):
                lingering = self.repository.get_chat_turn(turn_id)
                if (
                    lingering is not None
                    and lingering.status == "pending"
                    and lingering.operation_id == operation_id
                ):
                    self.repository.update_chat_turn(
                        turn_id,
                        assistant_message=lingering.assistant_message,
                        status="failed",
                        expected_status="pending",
                        enforce_operation_owner=True,
                        expected_operation_id=operation_id,
                        release_operation=True,
                        forbid_cancel_requested=True,
                    )
                    settled_failed = True
            if not settled_failed:
                with suppress(ValueError):
                    self.repository.release_chat_operation(thread.id, operation_id)
            raise
        return PreparedChatTurn(
            research_deadline=web_tools.answer_deadline,
            thread=self.repository.get_chat_thread(thread.id) or thread,
            turn=streaming,
            messages=messages,
            route=route,
            rag=streaming.rag_snapshot,
            runtime_modes=runtime_modes,
            memory_enabled=bool(memory_bundle),
            web_context_used=bool(web_context),
            is_continuation=is_continuation,
            base_reply=base_reply,
            retry_parent_turn_id=retry_parent.id if retry_parent else None,
            pedagogy_plan=pedagogy_plan,
            learning_state=next_learning_state,
            learning_state_before=learning_state,
            answer_validation=command.answer_validation,
            disclosure_policy=disclosed.policy,
            learner_evaluation=learner_evaluation,
        )

    def _record_answer_call(
        self, prepared: PreparedChatTurn, status: str
    ) -> None:
        current = prepared.route.get("external_data_policy")
        if not isinstance(current, dict):
            return
        calls = [
            dict(item)
            for item in current.get("external_calls", [])
            if isinstance(item, dict)
        ]
        answer = next(
            (item for item in calls if item.get("purpose") == "answer_generation"),
            None,
        )
        if answer is None:
            if status != "attempted":
                return
            answer_categories = list(current.get("answer_data_categories") or [])
            available_counts = {
                "current_question": 1,
                "recent_chat": int(current.get("history_message_count") or 0),
                "learning_state": 1,
                "memory_context": 1,
                "local_evidence": int(current.get("local_evidence_chunk_count") or 0),
                "web_results": 1,
            }
            answer = {
                "call_id": "answer_generation:1",
                "purpose": "answer_generation",
                "provider": _configured_llm_provider(),
                "data_categories": answer_categories,
                "data_counts": {
                    key: available_counts[key] for key in answer_categories
                },
            }
            calls.append(answer)
        answer["status"] = status
        answer["result"] = status
        refreshed = _refresh_execution_truth({**current, "external_calls": calls})
        prepared.route["external_data_policy"] = refreshed
        prepared.rag["external_data_policy"] = refreshed
        if status == "attempted":
            # Stage the outbound audit in memory only. The generation-start CAS
            # below persists this snapshot together with the physical call count,
            # so cancellation and provider-start accounting share one linearization
            # point instead of reporting egress before a call actually starts.
            return
        self.repository.update_chat_turn(
            prepared.turn.id,
            assistant_message=prepared.turn.assistant_message,
            status="streaming",
            route_snapshot=prepared.route,
            rag_snapshot=prepared.rag,
            operation_id=prepared.turn.operation_id,
            expected_operation_id=prepared.turn.operation_id,
            enforce_operation_owner=True,
            expected_status="streaming",
            forbid_cancel_requested=True,
        )

    def _begin_generation_call(self, prepared: PreparedChatTurn) -> bool:
        """Atomically reserve provider start and persist G16 answer egress truth."""
        operation_id = prepared.turn.operation_id or ""
        next_calls = _route_generation_calls(prepared.route) + 1
        route_snapshot = {
            **prepared.route,
            "answer_generation_calls": next_calls,
        }
        try:
            updated = self.repository.update_chat_turn(
                prepared.turn.id,
                assistant_message=prepared.turn.assistant_message,
                status="streaming",
                route_snapshot=route_snapshot,
                rag_snapshot=prepared.rag,
                expected_operation_id=operation_id,
                enforce_operation_owner=True,
                expected_status="streaming",
                forbid_cancel_requested=True,
            )
        except ValueError:
            if operation_id and self.repository.turn_cancel_requested(
                prepared.turn.id, operation_id
            ):
                return False
            raise
        if updated is None:
            raise RuntimeError(f"Chat turn disappeared: {prepared.turn.id}")
        prepared.route["answer_generation_calls"] = next_calls
        return True

    def generate(self, prepared: PreparedChatTurn) -> str:
        self._record_answer_call(prepared, "attempted")
        return super().generate(prepared)

    def stream(self, prepared: PreparedChatTurn, *, should_cancel=None) -> Iterator[str]:
        def audited_stream() -> Iterator[str]:
            self._record_answer_call(prepared, "attempted")
            yield from super(ExternalDataPolicyChatService, self).stream(
                prepared, should_cancel=should_cancel
            )

        return audited_stream()

    async def stream_async(self, prepared: PreparedChatTurn) -> AsyncIterator[str]:
        self._record_answer_call(prepared, "attempted")
        async for token in super().stream_async(prepared):
            yield token

    def complete_turn(self, prepared: PreparedChatTurn, suffix: str) -> ChatTurn:
        self._record_answer_call(prepared, "completed")
        return super().complete_turn(prepared, suffix)

    def interrupt_turn(self, prepared: PreparedChatTurn, suffix: str) -> ChatTurn:
        self._record_answer_call(prepared, "interrupted")
        return super().interrupt_turn(prepared, suffix)

    def fail_turn(self, prepared: PreparedChatTurn, suffix: str = "") -> ChatTurn:
        self._record_answer_call(prepared, "failed")
        return super().fail_turn(prepared, suffix)
