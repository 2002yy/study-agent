"""Application service for the ChatThread and ChatTurn lifecycle."""

from __future__ import annotations

from contextlib import suppress
from copy import deepcopy
from dataclasses import dataclass, field, replace
from typing import Any, AsyncIterator, Callable, Iterator

from src.application.answer_claim_binder import (
    ANSWER_CLAIM_BINDER_PRODUCER,
    AnswerClaimBindingRequest,
    AnswerClaimBindingRow,
    bind_answer_claims,
    factual_claims_fully_bound,
)
from src.context_builder import build_messages
from src.domain.answer_claims import rejected_answer_claim_snapshot
from src.domain.answer_validation import (
    PHASE_ANSWER_CLAIM_BINDING,
    PHASE_ANSWER_GENERATION,
    PHASE_OUTCOME_BUDGET_EXHAUSTED,
    PHASE_OUTCOME_COMPLETED,
    PHASE_OUTCOME_PASSED,
    PHASE_OUTCOME_REJECTED,
    build_answer_validation_audit,
)
from src.domain.runtime_entities import ChatThread, ChatTurn, new_id, utc_now
from src.llm_client import async_stream_chat, chat, stream_chat
from src.memory import read_memory_bundle
from src.mode_manager import load_runtime_modes
from src.performance_budget import chat_max_tokens
from src.pedagogy.engine import PedagogyEngine
from src.pedagogy.evaluation import PedagogyEvalRun, PedagogyEvaluationService
from src.pedagogy.evidence import EvidenceDisclosurePolicy, build_evidence_units
from src.pedagogy.types import LearningState, PedagogyTurnPlan
from src.rag.cancellation import RetrievalCancelled
from src.rag.query_plan import build_retrieval_query_plan
from src.repositories.runtime_repository import RuntimeRepository
from src.role_manager import build_role_prompt
from src.router import route_request
from src.tools.local_knowledge import retrieve_local_knowledge
from src.tools.web_agent import WebToolTrace, web_tools_disabled

PERFORMANCE_MODES = {"fast", "standard", "deep"}

RESEARCH_ANSWER_BLOCKED_COPY = (
    "联网检索结果未能通过证据核验，本次回答未发布基于联网来源的结论。"
)

# Gate=BLOCK is known *before* generation (no eligible evidence rows, or no
# attempt budget), and in that case the release gate replaces whatever the model
# writes with RESEARCH_ANSWER_BLOCKED_COPY. Measured: the default answer call
# spends 1330-2083 hidden reasoning tokens (16-41s) for output that is then
# discarded, so the blocked branch runs with thinking disabled. The published
# surface is unchanged; PARTIAL/PASS keep the production default.
THINKING_DISABLED_EXTRA_BODY: dict[str, dict[str, str]] = {
    "thinking": {"type": "disabled"}
}


def _answer_attempt_budget(prepared: Any) -> int:
    """Allowed answer-generation attempts for this turn (shared gate input)."""

    plan = prepared.answer_validation or {}
    raw_allowed = plan.get("allowed_attempts")
    try:
        return 0 if raw_allowed == 0 else max(1, min(int(raw_allowed or 1), 2))
    except (TypeError, ValueError):
        return 1


def _evidence_rows_present(prepared: Any) -> bool:
    """Whether the turn carries any eligible evidence row (shared gate input)."""

    plan = prepared.answer_validation or {}
    raw_rows = plan.get("evidence_rows") or ()
    return any(isinstance(row, dict) for row in raw_rows)


def _answer_generation_extra_body(prepared: Any) -> dict[str, dict[str, str]] | None:
    """Return the per-turn generation policy.

    ``BLOCK`` (no evidence rows / no attempt budget) disables hidden reasoning;
    any other gate outcome keeps the production default. This is derived from the
    same two inputs the release gate uses, so the policy cannot drift away from
    the gate decision.
    """

    if _answer_attempt_budget(prepared) < 1 or not _evidence_rows_present(prepared):
        return THINKING_DISABLED_EXTRA_BODY
    return None


def _configured_llm_provider() -> str:
    import os

    return os.getenv("LLM_PROVIDER_PROFILE", "openai").strip().lower() or "openai"


def answer_validation_active(prepared: PreparedChatTurn) -> bool:
    """True when the publication gate actually runs for this turn."""
    if prepared.answer_validation is None:
        return False
    policy = prepared.route.get("external_data_policy")
    if isinstance(policy, dict) and policy.get("web_allowed") is False:
        return False
    return True


class TurnCancelled(Exception):
    """Raised at a cooperative checkpoint when a turn cancellation was accepted."""

    def __init__(self, *, stage: str, turn_id: str, operation_id: str) -> None:
        super().__init__(f"Chat turn cancelled at stage '{stage}': {turn_id}")
        self.stage = stage
        self.turn_id = turn_id
        self.operation_id = operation_id


@dataclass(frozen=True)
class ChatCommand:
    user_input: str
    selected_role: str = "auto"
    selected_mode: str = "auto"
    selected_model: str = "auto"
    relationship_mode: str = "standard"
    scene: str = "single"
    conversation_instruction: str = ""
    performance_mode: str | None = None
    context_mode: str | None = None
    previous_mode: str | None = None
    chat_history: list[dict[str, Any]] = field(default_factory=list)
    keep_current_role: bool = False
    thread_id: str | None = None
    rag_enabled: bool = False
    rag_top_k: int = 3
    rag_search_top_k: int | None = None
    rag_chat_top_k: int | None = None
    rag_retrieval_mode: str = "hybrid"
    rag_min_score: float = 0.01
    web_context: str = ""
    web_context_run_id: str | None = None
    continuation_of_turn_id: str | None = None
    retry_of_turn_id: str | None = None
    partial_reply: str = ""
    turn_id: str | None = None
    operation_id: str | None = None
    answer_validation: dict[str, Any] | None = None


@dataclass(frozen=True)
class ChatDependencies:
    load_runtime_modes: Callable[[], Any] = load_runtime_modes
    read_memory_bundle: Callable[[str], dict[str, str]] = read_memory_bundle
    build_role_prompt: Callable[..., str] = build_role_prompt
    route_request: Callable[..., dict[str, Any]] = route_request
    retrieve_local_knowledge: Callable[..., Any] = retrieve_local_knowledge
    build_messages: Callable[..., list[dict[str, Any]]] = build_messages
    chat: Callable[..., str] = chat
    stream_chat: Callable[..., Iterator[str]] = stream_chat
    async_stream_chat: Callable[..., AsyncIterator[str]] = async_stream_chat
    chat_max_tokens: Callable[[str], int] = chat_max_tokens
    pedagogy_engine: PedagogyEngine = field(default_factory=PedagogyEngine)
    pedagogy_evaluation: PedagogyEvaluationService = field(
        default_factory=PedagogyEvaluationService
    )
    disclosure_policy: EvidenceDisclosurePolicy = field(
        default_factory=EvidenceDisclosurePolicy
    )
    resolve_web_tools: Callable[..., WebToolTrace] = web_tools_disabled


@dataclass(frozen=True)
class PreparedChatTurn:
    thread: ChatThread
    turn: ChatTurn
    messages: list[dict[str, Any]]
    route: dict[str, Any]
    rag: dict[str, Any]
    runtime_modes: Any
    memory_enabled: bool
    web_context_used: bool
    is_continuation: bool
    base_reply: str
    retry_parent_turn_id: str | None
    pedagogy_plan: PedagogyTurnPlan
    learning_state: LearningState
    learning_state_before: LearningState
    disclosure_policy: str
    learner_evaluation: PedagogyEvalRun
    answer_validation: dict[str, Any] | None = None


def _poll_cancel(repository: RuntimeRepository, turn_id: str, operation_id: str):
    def poll() -> bool:
        return repository.turn_cancel_requested(turn_id, operation_id)

    return poll


class ChatService:
    def __init__(
        self,
        repository: RuntimeRepository,
        dependencies: ChatDependencies | None = None,
    ):
        self.repository = repository
        self.dependencies = dependencies or ChatDependencies()

    def _make_cancel_check(
        self, turn_id: str, operation_id: str
    ) -> Callable[[str], None]:
        def check(stage: str) -> None:
            if stage == "answer_claim_binding_pre":
                current = self.repository.get_chat_turn(turn_id)
                if current is None:
                    raise ValueError(f"Chat turn not found: {turn_id}")
                try:
                    started = int(
                        current.route_snapshot.get(
                            "answer_claim_binding_calls_started", 0
                        )
                    )
                except (TypeError, ValueError):
                    started = 0
                reservation_route = {
                    **current.route_snapshot,
                    "answer_claim_binding_calls_started": max(
                        0, min(started, 1000)
                    )
                    + 1,
                }
                try:
                    self.repository.update_chat_turn(
                        turn_id,
                        assistant_message=current.assistant_message,
                        status="streaming",
                        route_snapshot=reservation_route,
                        expected_operation_id=operation_id,
                        enforce_operation_owner=True,
                        expected_status="streaming",
                        forbid_cancel_requested=True,
                    )
                except ValueError:
                    if self.repository.turn_cancel_requested(turn_id, operation_id):
                        raise TurnCancelled(
                            stage=stage,
                            turn_id=turn_id,
                            operation_id=operation_id,
                        ) from None
                    raise
                return
            if self.repository.turn_cancel_requested(turn_id, operation_id):
                raise TurnCancelled(
                    stage=stage, turn_id=turn_id, operation_id=operation_id
                )

        return check

    def _settle_cancelled_preparation(
        self,
        *,
        turn_id: str,
        operation_id: str,
        stage: str,
        assistant_message: str,
    ) -> None:
        self.repository.finish_turn_cancel(
            turn_id,
            operation_id=operation_id,
            stage=stage,
            reason="user_cancelled",
            assistant_message=assistant_message,
        )

    def finish_cancelled_turn(
        self, prepared: PreparedChatTurn, partial: str
    ) -> ChatTurn | None:
        reply = (
            f"{prepared.base_reply}{partial}" if prepared.is_continuation else partial
        )
        return self.repository.finish_turn_cancel(
            prepared.turn.id,
            operation_id=prepared.turn.operation_id or "",
            stage="generation",
            reason="user_cancelled",
            assistant_message=reply,
        )

    def start_turn(self, command: ChatCommand) -> PreparedChatTurn:
        command, existing, retry_parent = self._validate_turn_command(command)
        runtime_modes = self._runtime_modes(command.performance_mode)
        context_mode = command.context_mode or runtime_modes.context_mode
        settings = _session_settings(command, context_mode)
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
        operation_id = command.operation_id or new_id("op")
        thread = self.repository.acquire_chat_operation(
            thread.id,
            operation_id,
            settings_snapshot={
                **settings,
                "conversationInstruction": command.conversation_instruction,
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
            )
            learning_state = LearningState.from_dict(thread.learning_state)
            expected_concepts = tuple(
                str(item)
                for item in learning_state.payload.get(
                    "expected_concepts", learning_state.confirmed_points
                )
            )
            evidence_ids = self._previous_disclosed_evidence_ids(thread.id)
            cancel_check("pedagogy_evaluate")
            learner_evaluation = self.dependencies.pedagogy_evaluation.evaluate_learner(
                learner_input=command.user_input,
                state=learning_state,
                expected_concepts=expected_concepts,
                evidence=evidence_ids,
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
            pedagogy_plan, next_learning_state = self.dependencies.pedagogy_engine.plan(
                user_input=command.user_input,
                mode=route["mode"],
                state=learning_state,
            )
            route = {
                **route,
                "pedagogy": pedagogy_plan.to_dict(),
                "learning_state": next_learning_state.to_dict(),
                # Durable count of generation calls that already contributed to
                # this turn. The current operation increments only immediately
                # before its provider call is invoked.
                "answer_generation_calls": prior_generation_calls,
            }
            role_prompt = self.dependencies.build_role_prompt(
                route["role"],
                scene=command.scene,
                relationship_mode=command.relationship_mode,
            )
            memory_bundle = self.dependencies.read_memory_bundle(context_mode)
            retrieval_plan = build_retrieval_query_plan(
                command.user_input,
                state=learning_state,
                plan=pedagogy_plan,
            )
            cancel_check("retrieval")
            rag_result = self.dependencies.retrieve_local_knowledge(
                retrieval_plan.private_query,
                enabled=command.rag_enabled,
                force=retrieval_plan.force_retrieval,
                top_k=command.rag_chat_top_k or command.rag_top_k,
                retrieval_mode=command.rag_retrieval_mode,
                min_score=command.rag_min_score,
                should_cancel=_poll_cancel(self.repository, turn_id, operation_id),
            )
            rag = rag_result.to_dict()
            rag["query_plan"] = retrieval_plan.to_dict()
            cancel_check("web_tools")
            web_tools = self.dependencies.resolve_web_tools(
                command.user_input,
                model_profile=route["model_profile"],
                conversation_context=_tool_context(command.chat_history),
            )
            rag["web_tools"] = web_tools.to_dict()
            web_tool_error = str(rag["web_tools"].get("error") or "")
            rag["web_context"] = _web_context_provenance(
                command.web_context,
                command.web_context_run_id,
            )
            continuation_instruction = _continuation_instruction(command)
            context_blocks: list[str] = []
            evidence_units = build_evidence_units(
                rag=rag,
                web_context="\n\n".join(
                    part
                    for part in (command.web_context, web_tools.context_block())
                    if part.strip()
                ),
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
            if web_tool_error and not web_tools.used:
                context_blocks.append(
                    "联网搜索未获得可信来源。必须明确说明本回答未使用联网来源；"
                    "不得声称已经搜索、查到或依据联网结果。"
                )
            if continuation_instruction:
                context_blocks.append(continuation_instruction)
            messages = self.dependencies.build_messages(
                user_input=command.user_input,
                role_prompt=role_prompt,
                mode=route["mode"],
                memory_bundle=memory_bundle,
                chat_history=command.chat_history,
                relationship_mode=command.relationship_mode,
                runtime_modes=runtime_modes,
                context_mode=context_mode,
                rag_context="\n\n".join(context_blocks),
                scene=command.scene,
                conversation_instruction=command.conversation_instruction,
                pedagogy_plan=pedagogy_plan,
                learning_state=learning_state,
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
            expected = (
                "pending"
                if reserved_existing is None or reserved_existing.status == "pending"
                else "interrupted"
            )
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
            thread=self.repository.get_chat_thread(thread.id) or thread,
            turn=streaming,
            messages=messages,
            route=route,
            rag=streaming.rag_snapshot,
            runtime_modes=runtime_modes,
            memory_enabled=bool(memory_bundle),
            web_context_used=bool(command.web_context.strip()) or web_tools.used,
            is_continuation=is_continuation,
            base_reply=base_reply,
            retry_parent_turn_id=retry_parent.id if retry_parent else None,
            pedagogy_plan=pedagogy_plan,
            learning_state=next_learning_state,
            learning_state_before=learning_state,
            disclosure_policy=disclosed.policy,
            learner_evaluation=learner_evaluation,
            answer_validation=command.answer_validation,
        )

    def _begin_generation_call(self, prepared: PreparedChatTurn) -> bool:
        """Durably record one server-initiated generation call before invocation.

        Terminal/partial paths only inherit this counter. A cancellation that won
        the ownership race prevents this CAS and therefore never invents a model
        call merely because the turn later settles as interrupted/cancelled.
        """
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
        cancel_check = self._make_cancel_check(
            prepared.turn.id, prepared.turn.operation_id or ""
        )
        cancel_check("generate_pre")
        max_tokens = self.dependencies.chat_max_tokens(
            prepared.runtime_modes.performance_mode
        )
        if not self._begin_generation_call(prepared):
            self._settle_cancelled_preparation(
                turn_id=prepared.turn.id,
                operation_id=prepared.turn.operation_id or "",
                stage="generate_pre",
                assistant_message=(
                    prepared.base_reply if prepared.is_continuation else ""
                ),
            )
            raise TurnCancelled(
                stage="generate_pre",
                turn_id=prepared.turn.id,
                operation_id=prepared.turn.operation_id or "",
            )
        try:
            suffix = self.dependencies.chat(
                prepared.messages,
                model_profile=prepared.route["model_profile"],
                max_tokens=max_tokens,
                task_name="single_chat",
                request_max_retries=0,
                extra_body=_answer_generation_extra_body(prepared),
            )
        except TurnCancelled:
            self._settle_cancelled_preparation(
                turn_id=prepared.turn.id,
                operation_id=prepared.turn.operation_id or "",
                stage="generate_pre",
                assistant_message=prepared.base_reply if prepared.is_continuation else "",
            )
            raise
        except Exception:
            self.fail_turn(prepared)
            raise
        try:
            cancel_check("generate_post")
        except TurnCancelled:
            self._settle_cancelled_preparation(
                turn_id=prepared.turn.id,
                operation_id=prepared.turn.operation_id or "",
                stage="generate_post",
                assistant_message=prepared.base_reply if prepared.is_continuation else "",
            )
            raise
        try:
            return self.complete_turn(prepared, suffix).assistant_message
        except TurnCancelled as exc:
            self._settle_cancelled_preparation(
                turn_id=prepared.turn.id,
                operation_id=prepared.turn.operation_id or "",
                stage=exc.stage,
                assistant_message=prepared.base_reply if prepared.is_continuation else "",
            )
            raise
        except ValueError:
            operation_id = prepared.turn.operation_id or ""
            if operation_id and self.repository.turn_cancel_requested(
                prepared.turn.id, operation_id
            ):
                self._settle_cancelled_preparation(
                    turn_id=prepared.turn.id,
                    operation_id=operation_id,
                    stage="complete_turn",
                    assistant_message=(
                        prepared.base_reply if prepared.is_continuation else ""
                    ),
                )
                raise TurnCancelled(
                    stage="complete_turn",
                    turn_id=prepared.turn.id,
                    operation_id=operation_id,
                ) from None
            raise

    def stream(self, prepared: PreparedChatTurn, *, should_cancel=None) -> Iterator[str]:
        max_tokens = self.dependencies.chat_max_tokens(
            prepared.runtime_modes.performance_mode
        )
        if not self._begin_generation_call(prepared):
            return
        yield from self.dependencies.stream_chat(
            prepared.messages,
            model_profile=prepared.route["model_profile"],
            max_tokens=max_tokens,
            task_name="single_chat",
            should_cancel=should_cancel,
            request_max_retries=0,
            extra_body=_answer_generation_extra_body(prepared),
        )

    async def stream_async(self, prepared: PreparedChatTurn) -> AsyncIterator[str]:
        max_tokens = self.dependencies.chat_max_tokens(
            prepared.runtime_modes.performance_mode
        )
        started = self._begin_generation_call(prepared)
        if not started:
            return
        async for token in self.dependencies.async_stream_chat(
            prepared.messages,
            model_profile=prepared.route["model_profile"],
            max_tokens=max_tokens,
            task_name="single_chat",
            request_max_retries=0,
            extra_body=_answer_generation_extra_body(prepared),
        ):
            yield token

    def _record_claim_binding_call(
        self,
        prepared: PreparedChatTurn,
        *,
        outcome: str,
        attempts: int,
        candidate: str,
    ) -> None:
        """Record G16 egress truth for the binder phase.

        One logical phase record carries the exact number of physical outbound
        attempts; the separate answer-validation audit records the same count.
        Candidate answer text is never persisted here, only its payload class.
        """
        policy = prepared.route.get("external_data_policy")
        if not isinstance(policy, dict) or attempts < 1:
            return
        plan = prepared.answer_validation or {}
        raw_rows = plan.get("evidence_rows") or ()
        row_count = sum(1 for row in raw_rows if isinstance(row, dict))
        calls = [
            dict(item)
            for item in policy.get("external_calls", [])
            if isinstance(item, dict)
            and item.get("purpose") != "answer_claim_binding"
        ]
        status = "completed" if outcome == "validated" else "rejected"
        calls.append(
            {
                "call_id": "answer_claim_binding:1",
                "purpose": "answer_claim_binding",
                "provider": _configured_llm_provider(),
                "data_categories": [
                    "current_question",
                    "candidate_answer",
                    "web_results",
                ],
                "data_counts": {
                    "current_question": 1,
                    "candidate_answer": 1 if candidate else 0,
                    "web_results": row_count,
                },
                "attempts": attempts,
                "status": status,
                "result": status,
            }
        )
        refreshed = {**policy, "external_calls": calls}
        prepared.route["external_data_policy"] = refreshed
        prepared.rag["external_data_policy"] = refreshed

    def _gate_research_answer(
        self,
        prepared: PreparedChatTurn,
        candidate: str,
    ) -> tuple[str, Any | None, dict[str, Any], bool]:
        generation_calls = _route_generation_calls(prepared.route)
        generation_phase = {
            "attempted": generation_calls > 0,
            "model_calls": generation_calls,
            "attempts": generation_calls,
            "outcome": PHASE_OUTCOME_COMPLETED,
            "error_type": "",
        }
        plan = prepared.answer_validation or {}
        allowed_attempts = _answer_attempt_budget(prepared)
        if allowed_attempts < 1:
            return (
                RESEARCH_ANSWER_BLOCKED_COPY,
                None,
                {
                    PHASE_ANSWER_GENERATION: generation_phase,
                    PHASE_ANSWER_CLAIM_BINDING: {
                        "attempted": True,
                        "model_calls": 0,
                        "attempts": 0,
                        "outcome": PHASE_OUTCOME_BUDGET_EXHAUSTED,
                        "error_type": "budget_exhausted",
                    },
                },
                True,
            )
        raw_rows = plan.get("evidence_rows") or ()
        rows = tuple(
            AnswerClaimBindingRow(
                evidence_id=str(row.get("evidence_id") or "").strip(),
                claim_id=str(row.get("claim_id") or "").strip(),
                title=str(row.get("title") or ""),
                url=str(row.get("url") or ""),
                source_role=str(row.get("source_role") or ""),
                source_cluster_id=str(row.get("source_cluster_id") or ""),
                relation=str(row.get("relation") or ""),
                strength=str(row.get("strength") or ""),
                locator=str(row.get("locator") or ""),
                anchored_spans=tuple(
                    str(span) for span in row.get("anchored_spans") or ()
                ),
                caveats=tuple(str(caveat) for caveat in row.get("caveats") or ()),
            )
            for row in raw_rows
            if isinstance(row, dict)
        )
        if not rows:
            return (
                RESEARCH_ANSWER_BLOCKED_COPY,
                None,
                self._blocked_audit_phases(generation_phase, "missing_evidence_brief"),
                True,
            )
        question = prepared.turn.user_message
        answer = candidate.strip()
        if not answer:
            return (
                RESEARCH_ANSWER_BLOCKED_COPY,
                None,
                self._blocked_audit_phases(generation_phase, "candidate_unavailable"),
                True,
            )
        cancel_check = self._make_cancel_check(
            prepared.turn.id, prepared.turn.operation_id or ""
        )
        bound = bind_answer_claims(
            request=AnswerClaimBindingRequest(
                question=question,
                final_answer=candidate,
                evidence_rows=rows,
            ),
            model_fn=lambda messages: self.dependencies.chat(
                list(messages),
                model_profile=prepared.route["model_profile"],
                max_tokens=self.dependencies.chat_max_tokens(
                    prepared.runtime_modes.performance_mode
                ),
                task_name="answer_claim_binding",
                request_max_retries=0,
            ),
            max_attempts=allowed_attempts,
            before_model_call=lambda: cancel_check("answer_claim_binding_pre"),
        )
        binding_phase: dict[str, Any] = {
            "attempted": True,
            "model_calls": bound.attempt_count,
            "attempts": bound.attempt_count,
            "outcome": "",
            "error_type": "",
        }
        snapshot = bound.snapshot
        self._record_claim_binding_call(
            prepared,
            outcome=snapshot.status,
            attempts=bound.attempt_count,
            candidate=candidate,
        )
        if snapshot.status == "validated" and factual_claims_fully_bound(snapshot):
            binding_phase["outcome"] = PHASE_OUTCOME_PASSED
            return (
                candidate,
                snapshot,
                {
                    PHASE_ANSWER_GENERATION: generation_phase,
                    PHASE_ANSWER_CLAIM_BINDING: binding_phase,
                },
                False,
            )
        binding_phase["outcome"] = PHASE_OUTCOME_REJECTED
        binding_phase["error_type"] = (
            str(snapshot.reason or "")[:120]
            if snapshot.status != "validated"
            else "unbound_factual_claim"
        )
        rejected_reason = (
            str(snapshot.reason or "producer_unavailable")
            if snapshot.status != "validated"
            else "unbound_factual_claim"
        )
        rejected = rejected_answer_claim_snapshot(
            answer=RESEARCH_ANSWER_BLOCKED_COPY,
            producer=ANSWER_CLAIM_BINDER_PRODUCER,
            reason=rejected_reason,
        )
        return (
            RESEARCH_ANSWER_BLOCKED_COPY,
            rejected,
            {
                PHASE_ANSWER_GENERATION: generation_phase,
                PHASE_ANSWER_CLAIM_BINDING: binding_phase,
            },
            True,
        )

    def _blocked_audit_phases(
        self, generation_phase: dict[str, Any], error_type: str
    ) -> dict[str, Any]:
        return {
            PHASE_ANSWER_GENERATION: generation_phase,
            PHASE_ANSWER_CLAIM_BINDING: {
                "attempted": True,
                "model_calls": 0,
                "attempts": 0,
                "outcome": PHASE_OUTCOME_REJECTED,
                "error_type": error_type,
            },
        }

    def complete_turn(self, prepared: PreparedChatTurn, suffix: str) -> ChatTurn:
        reply = f"{prepared.base_reply}{suffix}" if prepared.is_continuation else suffix
        gate_blocked_pedagogy = False
        if answer_validation_active(prepared):
            reply, claims_snapshot, audit_phases, gate_blocked_pedagogy = (
                self._gate_research_answer(prepared, reply)
            )
            audit = build_answer_validation_audit(
                candidate_answer=(
                    f"{prepared.base_reply}{suffix}"
                    if prepared.is_continuation
                    else suffix
                ),
                published_answer=reply,
                phases=audit_phases,
            )
            published_rag = {
                **deepcopy(prepared.rag),
                "answer_validation_audit": audit,
            }
            if claims_snapshot is not None:
                published_rag["answer_claim_snapshot"] = claims_snapshot.to_dict()
            if claims_snapshot is not None and claims_snapshot.status == "validated":
                linked_evidence_ids = {
                    link.evidence_id
                    for link in claims_snapshot.claim_links
                    if link.evidence_id
                }
                published_rag["research_evidence_refs"] = [
                    {
                        "evidence_id": str(row.get("evidence_id") or ""),
                        "claim_id": str(row.get("claim_id") or ""),
                        "title": str(row.get("title") or ""),
                        "url": str(row.get("url") or ""),
                        "source_cluster_id": str(row.get("source_cluster_id") or ""),
                        "published_at": str(row.get("published_at") or ""),
                    }
                    for row in (prepared.answer_validation or {}).get(
                        "evidence_rows"
                    )
                    or ()
                    if isinstance(row, dict)
                    and str(row.get("evidence_id") or "") in linked_evidence_ids
                ]
        else:
            published_rag = deepcopy(prepared.rag)
        evaluation = self.dependencies.pedagogy_engine.evaluate_response(
            reply,
            plan=prepared.pedagogy_plan,
        )
        committed_state = self.dependencies.pedagogy_engine.apply_transition(
            before=prepared.learning_state_before,
            planned=prepared.learning_state,
            evaluation=evaluation,
        )
        if _requires_mastery_evidence(prepared.pedagogy_plan):
            if prepared.learner_evaluation.final_decision != "accept":
                committed_state = LearningState.from_dict(
                    {
                        **prepared.learning_state_before.to_dict(),
                        "payload": {
                            **prepared.learning_state_before.payload,
                            "pedagogy_evaluation": prepared.learner_evaluation.to_dict(),
                            "state_advance_blocked": True,
                        },
                    }
                )
        if gate_blocked_pedagogy:
            committed_state = prepared.learning_state_before
        pedagogy_snapshot = {
            **prepared.turn.pedagogy_snapshot,
            "assistant_evaluation": {
                "passed": evaluation.passed,
                "violations": list(evaluation.violations),
                "question_count": evaluation.question_count,
            },
            "committed_learning_state": committed_state.to_dict(),
        }
        completed_truth = _normalized_turn_truth(
            turn=prepared.turn,
            fallback_turn_id=prepared.turn.id,
            thread_id=prepared.thread.id,
            user_message=prepared.turn.user_message,
            assistant_message=reply,
            status="completed",
            role=prepared.route["role"],
            mode=prepared.route["mode"],
            model=prepared.route["model_profile"],
            route_snapshot=prepared.route,
            rag_snapshot=published_rag,
            pedagogy_snapshot=pedagogy_snapshot,
            parent_turn_id=prepared.turn.parent_turn_id,
            operation_id=prepared.turn.operation_id,
            conversation_instruction=prepared.turn.conversation_instruction,
        )
        updated = self.repository.complete_chat_turn_with_pedagogy(
            prepared.turn.id,
            assistant_message=reply,
            learning_state=committed_state.to_dict(),
            route_snapshot={
                **prepared.route,
                "learning_state": committed_state.to_dict(),
                "web_context_used": prepared.web_context_used,
                "is_continuation": prepared.is_continuation,
                "is_continuation_resolved": prepared.is_continuation,
                "answer_generation_calls": _route_generation_calls(prepared.route),
            },
            rag_snapshot=completed_truth.rag_snapshot,
            operation_id=prepared.turn.operation_id or "",
            pedagogy_snapshot=pedagogy_snapshot,
            supersede_parent_turn_id=prepared.retry_parent_turn_id,
            pedagogy_eval_run=prepared.learner_evaluation,
        )
        return updated

    def interrupt_turn(self, prepared: PreparedChatTurn, suffix: str) -> ChatTurn:
        reply = f"{prepared.base_reply}{suffix}" if prepared.is_continuation else suffix
        interrupted_truth = _normalized_turn_truth(
            turn=prepared.turn,
            fallback_turn_id=prepared.turn.id,
            thread_id=prepared.thread.id,
            user_message=prepared.turn.user_message,
            assistant_message=reply,
            status="interrupted",
            role=prepared.route["role"],
            mode=prepared.route["mode"],
            model=prepared.route["model_profile"],
            route_snapshot={
                **prepared.route,
                "interrupted": True,
                "answer_generation_calls": _route_generation_calls(prepared.route),
            },
            rag_snapshot=prepared.rag,
            pedagogy_snapshot=prepared.turn.pedagogy_snapshot,
            parent_turn_id=prepared.turn.parent_turn_id,
            operation_id=prepared.turn.operation_id,
            conversation_instruction=prepared.turn.conversation_instruction,
        )
        updated = self.repository.update_chat_turn(
            prepared.turn.id,
            assistant_message=reply,
            status="interrupted",
            route_snapshot=interrupted_truth.route_snapshot,
            rag_snapshot=interrupted_truth.rag_snapshot,
            pedagogy_snapshot=interrupted_truth.pedagogy_snapshot,
            operation_id=prepared.turn.operation_id,
            expected_operation_id=prepared.turn.operation_id,
            enforce_operation_owner=True,
            expected_status="streaming",
            release_operation=True,
            forbid_cancel_requested=True,
        )
        if updated is None:
            raise RuntimeError(f"Chat turn disappeared: {prepared.turn.id}")
        return updated

    def fail_turn(self, prepared: PreparedChatTurn, suffix: str = "") -> ChatTurn:
        reply = f"{prepared.base_reply}{suffix}" if prepared.is_continuation else suffix
        failed_truth = _normalized_turn_truth(
            turn=prepared.turn,
            fallback_turn_id=prepared.turn.id,
            thread_id=prepared.thread.id,
            user_message=prepared.turn.user_message,
            assistant_message=reply,
            status="failed",
            role=prepared.route["role"],
            mode=prepared.route["mode"],
            model=prepared.route["model_profile"],
            route_snapshot={**prepared.route, "failed": True},
            rag_snapshot=prepared.rag,
            pedagogy_snapshot=prepared.turn.pedagogy_snapshot,
            parent_turn_id=prepared.turn.parent_turn_id,
            operation_id=prepared.turn.operation_id,
            conversation_instruction=prepared.turn.conversation_instruction,
        )
        updated = self.repository.update_chat_turn(
            prepared.turn.id,
            assistant_message=reply,
            status="failed",
            route_snapshot=failed_truth.route_snapshot,
            rag_snapshot=failed_truth.rag_snapshot,
            pedagogy_snapshot=failed_truth.pedagogy_snapshot,
            operation_id=prepared.turn.operation_id,
            expected_operation_id=prepared.turn.operation_id,
            enforce_operation_owner=True,
            expected_status="streaming",
            release_operation=True,
            forbid_cancel_requested=True,
        )
        if updated is None:
            raise RuntimeError(f"Chat turn disappeared: {prepared.turn.id}")
        return updated

    def _validate_turn_command(
        self,
        command: ChatCommand,
    ) -> tuple[ChatCommand, ChatTurn | None, ChatTurn | None]:
        if command.continuation_of_turn_id and command.retry_of_turn_id:
            raise ValueError("A chat turn cannot be both a continuation and a retry")
        if command.continuation_of_turn_id:
            target_id = command.continuation_of_turn_id
            if command.turn_id and command.turn_id != target_id:
                raise ValueError("turn_id must match continuation_of_turn_id")
            existing = self.repository.get_chat_turn(target_id)
            if existing is None:
                raise ValueError(f"Continuation target does not exist: {target_id}")
            if command.thread_id and command.thread_id != existing.thread_id:
                raise ValueError(f"Chat turn {target_id} belongs to a different thread")
            if existing.status != "interrupted":
                raise ValueError(
                    f"Chat turn cannot be continued from status {existing.status}: {target_id}"
                )
            return (
                replace(
                    command,
                    user_input=existing.user_message,
                    thread_id=existing.thread_id,
                    turn_id=target_id,
                ),
                existing,
                None,
            )
        retry_parent = None
        if command.retry_of_turn_id:
            retry_parent = self.repository.get_chat_turn(command.retry_of_turn_id)
            if retry_parent is None:
                raise ValueError(f"Retry target does not exist: {command.retry_of_turn_id}")
            if command.thread_id and command.thread_id != retry_parent.thread_id:
                raise ValueError(
                    f"Chat turn {command.retry_of_turn_id} belongs to a different thread"
                )
            if retry_parent.status not in {"interrupted", "failed", "cancelled"}:
                raise ValueError(
                    f"Chat turn cannot be retried from status {retry_parent.status}: {retry_parent.id}"
                )
            command = replace(
                command,
                user_input=retry_parent.user_message,
                thread_id=retry_parent.thread_id,
            )
        existing = self.repository.get_chat_turn(command.turn_id) if command.turn_id else None
        if existing is not None and command.thread_id and existing.thread_id != command.thread_id:
            raise ValueError(f"Chat turn {existing.id} belongs to a different thread")
        return command, existing, retry_parent

    def commit_partial_turn(
        self,
        *,
        thread_id: str,
        turn_id: str,
        operation_id: str,
        user_input: str,
        assistant_message: str,
        role: str,
        mode: str,
        model: str,
        route_snapshot: dict[str, Any],
        rag_snapshot: dict[str, Any],
        conversation_instruction: str,
    ) -> tuple[ChatTurn, bool]:
        thread = self.repository.get_chat_thread(thread_id)
        if thread is None or thread.status != "active":
            raise ValueError(f"Chat thread not found or inactive: {thread_id}")
        existing = self.repository.get_chat_turn(turn_id)
        if existing is None:
            raise ValueError(f"Chat turn not found: {turn_id}")
        if existing.thread_id != thread_id:
            raise ValueError(
                f"Chat turn {turn_id} belongs to a different thread"
            )
        if existing.operation_id != operation_id:
            raise ValueError(f"Chat turn operation ownership lost: {turn_id}")
        if existing.status not in {"streaming", "interrupted"}:
            return existing, False
        stored_reply = assistant_message
        if existing.assistant_message:
            stored_reply = _preferred_partial_reply(
                existing.assistant_message,
                assistant_message,
            )
        if existing.status == "interrupted" and existing.assistant_message == stored_reply:
            return existing, False
        route_truth = deepcopy(existing.route_snapshot)
        partial_truth = _normalized_turn_truth(
            turn=existing,
            fallback_turn_id=turn_id,
            thread_id=thread_id,
            user_message=existing.user_message,
            assistant_message=stored_reply,
            status="interrupted",
            role=existing.role,
            mode=existing.mode,
            model=existing.model,
            route_snapshot=route_truth,
            rag_snapshot=existing.rag_snapshot,
            pedagogy_snapshot=existing.pedagogy_snapshot,
            parent_turn_id=existing.parent_turn_id,
            operation_id=operation_id,
            conversation_instruction=existing.conversation_instruction,
        )
        updated = self.repository.update_chat_turn(
            turn_id,
            assistant_message=stored_reply,
            status="interrupted",
            route_snapshot=partial_truth.route_snapshot,
            rag_snapshot=partial_truth.rag_snapshot,
            pedagogy_snapshot=partial_truth.pedagogy_snapshot,
            expected_operation_id=operation_id,
            enforce_operation_owner=existing.status == "streaming",
            expected_status=existing.status,
            release_operation=existing.status == "streaming",
            forbid_cancel_requested=True,
        )
        if updated is None:
            raise ValueError(f"Chat turn not found: {turn_id}")
        return updated, True

    def _runtime_modes(self, requested: str | None):
        runtime_modes = self.dependencies.load_runtime_modes()
        if not requested:
            return runtime_modes
        if requested not in PERFORMANCE_MODES:
            raise ValueError(f"Invalid performance_mode: {requested}")
        return replace(runtime_modes, performance_mode=requested)

    def _previous_persisted_mode(self, thread_id: str) -> str | None:
        turns = self.repository.list_chat_turns(thread_id)
        for turn in reversed(turns):
            if turn.status != "superseded" and turn.mode:
                return turn.mode
        return None

    def _previous_disclosed_evidence_ids(self, thread_id: str) -> tuple[str, ...]:
        turns = self.repository.list_chat_turns(thread_id)
        for turn in reversed(turns):
            if turn.status != "completed":
                continue
            units = turn.pedagogy_snapshot.get("evidence_units", ())
            if not isinstance(units, list):
                return ()
            return tuple(
                str(unit["source_id"])
                for unit in units
                if isinstance(unit, dict) and str(unit.get("source_id", "")).strip()
            )
        return ()


def _normalized_turn_truth(
    *,
    turn: ChatTurn | None,
    fallback_turn_id: str,
    thread_id: str,
    user_message: str,
    assistant_message: str,
    status: str,
    role: str,
    mode: str,
    model: str,
    route_snapshot: dict[str, Any],
    rag_snapshot: dict[str, Any],
    pedagogy_snapshot: dict[str, Any],
    parent_turn_id: str | None,
    operation_id: str | None,
    conversation_instruction: str,
) -> ChatTurn:
    normalized_rag = deepcopy(rag_snapshot)
    raw_claims = normalized_rag.get("answer_claim_snapshot")
    if status == "completed" and isinstance(raw_claims, dict):
        if raw_claims.get("status") == "unavailable":
            normalized_rag.pop("answer_claim_snapshot", None)
    return ChatTurn(
        id=turn.id if turn is not None else fallback_turn_id,
        thread_id=thread_id,
        user_message=user_message,
        assistant_message=assistant_message,
        status=status,
        role=role,
        mode=mode,
        model=model,
        route_snapshot=deepcopy(route_snapshot),
        rag_snapshot=normalized_rag,
        pedagogy_snapshot=deepcopy(pedagogy_snapshot),
        parent_turn_id=parent_turn_id,
        operation_id=operation_id,
        conversation_instruction=conversation_instruction,
        created_at=turn.created_at if turn is not None else utc_now(),
        updated_at=utc_now(),
    )


def _route_generation_calls(route_snapshot: dict[str, Any]) -> int:
    try:
        calls = int(route_snapshot.get("answer_generation_calls", 0))
    except (TypeError, ValueError):
        return 0
    return max(0, min(calls, 1000))


def _persisted_generation_calls(turn: ChatTurn) -> int:
    """Recover durable generation truth for a continuation.

    New interrupted turns carry an explicit server-owned count in the route
    snapshot. Legacy interrupted turns predate that marker; reaching the
    interrupted state itself proves at least one physical generation attempt,
    so they conservatively resume from one instead of silently undercounting.
    """
    if "answer_generation_calls" in turn.route_snapshot:
        return _route_generation_calls(turn.route_snapshot)
    return 1 if turn.status == "interrupted" else 0


def _requires_mastery_evidence(plan: PedagogyTurnPlan) -> bool:
    return (
        plan.phase in {"transfer", "complete", "deliver"}
        or plan.move in {"transfer", "transfer_test", "close_stage"}
    )


def _previous_assistant_role(history: list[dict[str, Any]]) -> str | None:
    valid_roles = {"nahida", "march7", "keqing", "firefly"}
    for message in reversed(history):
        if message.get("role") != "assistant":
            continue
        avatar_role = message.get("avatarRole")
        if avatar_role in valid_roles:
            return str(avatar_role)
    return None


def _web_context_provenance(
    web_context: str,
    run_id: str | None,
) -> dict[str, Any]:
    used = bool(web_context.strip())
    normalized_run_id = str(run_id or "").strip()
    return {
        "used": used,
        "run_id": normalized_run_id if used and normalized_run_id else "",
        "source": "research_run" if used and normalized_run_id else "manual",
    }


def _tool_context(history: list[dict[str, Any]]) -> str:
    recent = history[-6:]
    return "\n".join(
        f"{str(message.get('role', 'user'))}: {str(message.get('content', ''))[:500]}"
        for message in recent
        if isinstance(message, dict)
    )


def _continuation_instruction(command: ChatCommand) -> str:
    if not command.continuation_of_turn_id or not command.partial_reply.strip():
        return ""
    return (
        "[继续生成指令]\n"
        "请从下面已经输出的内容之后继续回答，不要重复已输出的部分。\n"
        f"已输出内容：\n{command.partial_reply.strip()[:800]}"
    )


def _preferred_partial_reply(stored: str, supplied: str) -> str:
    if not stored:
        return supplied
    if not supplied or supplied == stored:
        return stored
    if supplied.startswith(stored):
        return supplied
    if stored.startswith(supplied):
        return stored
    raise ValueError("Supplied partial reply conflicts with the stored turn")


def _session_settings(command: ChatCommand, context_mode: str) -> dict[str, Any]:
    chat_top_k = command.rag_chat_top_k or command.rag_top_k
    return {
        "selectedRole": command.selected_role,
        "selectedMode": command.selected_mode,
        "selectedModel": command.selected_model,
        "relationshipMode": command.relationship_mode,
        "contextMode": context_mode,
        "ragEnabled": command.rag_enabled,
        "ragSettings": {
            "chatTopK": chat_top_k,
            "topK": command.rag_search_top_k or chat_top_k,
            "retrievalMode": command.rag_retrieval_mode,
            "minScore": command.rag_min_score,
        },
        "keepCurrentRole": command.keep_current_role,
    }
