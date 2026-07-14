"""Policy-aware chat preparation.

Only the preparation stage differs from ``ChatService``. Generation,
interruption, retry and atomic completion reuse the established lifecycle.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, cast

from src.application.chat_service import (
    ChatCommand,
    ChatService,
    PreparedChatTurn,
    _continuation_instruction,
    _preferred_partial_reply,
    _previous_assistant_role,
    _session_settings,
    _tool_context,
)
from src.application.helpers import load_frontend_settings
from src.domain.runtime_entities import ChatThread, ChatTurn, new_id, utc_now
from src.external_data_policy import decide_external_data
from src.pedagogy.evidence import build_evidence_units
from src.pedagogy.types import LearningState
from src.rag.query_plan import build_retrieval_query_plan
from src.task_contract import resolve_turn_task_contract
from src.task_intent import SourcePolicy, TaskIntent
from src.tools.web_agent import WebToolTrace

WEB_CONSENT_MARKER = "__STUDY_AGENT_WEB_CONSENT__"

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
    task_intent: TaskIntent | None = None


def _source_policy(route: dict[str, Any]) -> SourcePolicy:
    contract = route.get("task_contract")
    if not isinstance(contract, dict):
        return "local_and_web"
    value = str(contract.get("source_policy", "local_and_web"))
    if value not in _SOURCE_POLICIES:
        return "local_and_web"
    return cast(SourcePolicy, value)


class ExternalDataPolicyChatService(ChatService):
    """Apply user-controlled source and model-context gates."""

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
        settings = {
            **_session_settings(command, context_mode),
            "webPolicy": effective_web_policy,
            "cloudContextPolicy": effective_cloud_context_policy,
        }
        turn_id = command.turn_id or command.continuation_of_turn_id or new_id("turn")
        is_continuation = bool(command.continuation_of_turn_id)
        thread_id = command.thread_id or (
            existing.thread_id if existing is not None and is_continuation else ChatThread().id
        )
        if existing is not None and not is_continuation:
            raise ValueError(f"Chat turn already exists: {turn_id}")
        thread = self.repository.ensure_chat_thread(thread_id)
        learning_state = LearningState.from_dict(thread.learning_state)
        persisted_turn = existing if is_continuation else retry_parent
        task_contract = resolve_turn_task_contract(
            user_input=command.user_input,
            state=learning_state,
            explicit_override=command.task_intent,
            persisted_route=(persisted_turn.route_snapshot if persisted_turn else None),
        )
        operation_id = new_id("op")
        thread = self.repository.acquire_chat_operation(
            thread.id,
            operation_id,
            settings_snapshot={
                **settings,
                "conversationInstruction": command.conversation_instruction,
                "taskIntent": task_contract.task_intent,
            },
        )
        try:
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
            )
            route = {**route, "external_data_policy": decision.to_dict()}
            expected_concepts = tuple(
                str(item)
                for item in learning_state.payload.get(
                    "expected_concepts", learning_state.confirmed_points
                )
            )
            evidence_ids = self._previous_disclosed_evidence_ids(thread.id)
            learner_evaluation = cast(
                Any, self.dependencies.pedagogy_evaluation
            ).evaluate_learner(
                learner_input=command.user_input,
                state=learning_state,
                expected_concepts=expected_concepts,
                evidence=evidence_ids,
                task_contract=task_contract,
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
            rag_result = self.dependencies.retrieve_local_knowledge(
                retrieval_plan.private_query,
                enabled=(command.rag_enabled and decision.local_retrieval_allowed),
                force=(retrieval_plan.force_retrieval and decision.local_retrieval_allowed),
                top_k=command.rag_chat_top_k or command.rag_top_k,
                retrieval_mode=command.rag_retrieval_mode,
                min_score=command.rag_min_score,
            )
            rag = rag_result.to_dict()
            rag["query_plan"] = retrieval_plan.to_dict()
            if decision.web_allowed:
                web_tools = self.dependencies.resolve_web_tools(
                    command.user_input,
                    model_profile=route["model_profile"],
                    conversation_context=(
                        _tool_context(command.chat_history)
                        if decision.history_allowed
                        else ""
                    ),
                )
            else:
                web_tools = WebToolTrace(enabled=False)
            rag["web_tools"] = {
                **web_tools.to_dict(),
                "policy_reason": decision.reason,
            }
            rag["external_data_policy"] = decision.to_dict()
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
            route["evidence_disclosure"] = disclosed.policy
            if disclosed.private_context:
                context_blocks.append(disclosed.private_context)
            if disclosed.context:
                context_blocks.append(disclosed.context)
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
            now = utc_now()
            pedagogy_snapshot = {
                **pedagogy_plan.to_dict(),
                "learning_state_before": learning_state.to_dict(),
                "learning_state_after": next_learning_state.to_dict(),
                "evidence_disclosure": disclosed.policy,
                "evidence_units": list(disclosed.units),
                "external_data_policy": decision.to_dict(),
                "task_contract": task_contract.to_dict(),
            }
            if existing is None:
                pending = ChatTurn(
                    id=turn_id,
                    thread_id=thread.id,
                    user_message=command.user_input,
                    assistant_message=base_reply,
                    status="pending",
                    role=route["role"],
                    mode=route["mode"],
                    model=route["model_profile"],
                    route_snapshot=route,
                    rag_snapshot=rag,
                    pedagogy_snapshot=pedagogy_snapshot,
                    parent_turn_id=retry_parent.id if retry_parent else None,
                    operation_id=operation_id,
                    conversation_instruction=command.conversation_instruction,
                    created_at=now,
                    updated_at=now,
                )
                self.repository.add_chat_turn(pending)
            streaming = self.repository.update_chat_turn(
                turn_id,
                assistant_message=base_reply,
                status="streaming",
                role=route["role"],
                mode=route["mode"],
                model=route["model_profile"],
                route_snapshot=route,
                rag_snapshot=rag,
                pedagogy_snapshot=pedagogy_snapshot,
                operation_id=operation_id,
                expected_operation_id=(operation_id if existing is None else existing.operation_id),
                enforce_operation_owner=True,
                expected_status="pending" if existing is None else "interrupted",
            )
            if streaming is None:
                raise RuntimeError(f"Chat turn was not created: {turn_id}")
        except Exception:
            self.repository.release_chat_operation(thread.id, operation_id)
            raise
        return PreparedChatTurn(
            thread=self.repository.get_chat_thread(thread.id) or thread,
            turn=streaming,
            messages=messages,
            route=route,
            rag=rag,
            runtime_modes=runtime_modes,
            memory_enabled=bool(memory_bundle),
            web_context_used=bool(web_context),
            is_continuation=is_continuation,
            base_reply=base_reply,
            retry_parent_turn_id=retry_parent.id if retry_parent else None,
            pedagogy_plan=pedagogy_plan,
            learning_state=next_learning_state,
            learning_state_before=learning_state,
            disclosure_policy=disclosed.policy,
            learner_evaluation=learner_evaluation,
        )
