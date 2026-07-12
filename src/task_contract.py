"""Top-level task contract independent from role voice and pedagogy protocol."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Callable, Literal
from uuid import uuid4

from src.pedagogy.classifier import classify_knowledge
from src.pedagogy.engine import PedagogyEngine
from src.pedagogy.evaluation import PedagogyEvalRun, PedagogyEvaluationService
from src.pedagogy.types import (
    AssistantResponseEvaluation,
    LearningState,
    PedagogyTurnPlan,
)

TaskIntent = Literal[
    "quick_answer",
    "research",
    "learn",
    "explain_back",
    "project_execution",
    "conversation",
    "organize",
]
SourcePolicy = Literal[
    "model_only",
    "local_only",
    "web_only",
    "local_and_web",
    "ask_before_external",
]
ClosureEligibility = Literal[
    "not_applicable",
    "optional_note",
    "learning_summary",
    "research_summary",
    "project_summary",
]


@dataclass(frozen=True)
class TaskContract:
    task_intent: TaskIntent
    source_policy: SourcePolicy
    closure_eligibility: ClosureEligibility
    learning_state_enabled: bool
    confidence: str
    reason: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


_EXPLAIN_BACK_MARKERS = (
    "我来讲",
    "我来解释",
    "我解释一遍",
    "我复述",
    "检查我的理解",
    "检查我理解",
    "你找漏洞",
    "听我解释",
)
_PROJECT_MARKERS = (
    "修改项目",
    "修复 bug",
    "修复bug",
    "排查 bug",
    "排查bug",
    "帮我改代码",
    "开始实现",
    "应用补丁",
    "跑测试",
    "运行测试",
    "部署项目",
    "修这个项目",
)
_LEARN_MARKERS = (
    "带我系统学习",
    "系统学习",
    "带我学",
    "我想学习",
    "我想学",
    "从零学",
    "零基础学",
    "学习路径",
    "一步步学",
    "教我学习",
)
_RESEARCH_PATTERNS = (
    re.compile(r"联网(?:看|查|搜|检索|了解)"),
    re.compile(r"(?:搜|查)(?:一下|一查|查看).{0,12}(?:最新|最近|发布|官网|公开)"),
    re.compile(r"(?:最新|最近).{0,16}(?:消息|进展|发布|版本|报道|新闻)"),
    re.compile(r"(?:公开信息|官方消息|官网资料|新闻来源)"),
)
_ORGANIZE_MARKERS = (
    "整理这次学习",
    "整理本次学习",
    "总结本次会话",
    "生成课后总结",
)
_CONVERSATION_MARKERS = (
    "陪我聊",
    "随便聊聊",
    "闲聊",
    "我心情不好",
    "我很难受",
)


def classify_task_contract(
    user_input: str, *, active_learning: bool = False
) -> TaskContract:
    text = " ".join(user_input.strip().lower().split())

    if any(marker in text for marker in _EXPLAIN_BACK_MARKERS):
        return TaskContract(
            task_intent="explain_back",
            source_policy="local_and_web",
            closure_eligibility="learning_summary",
            learning_state_enabled=True,
            confidence="high",
            reason="explicit_explain_back",
        )
    if any(marker in text for marker in _PROJECT_MARKERS):
        return TaskContract(
            task_intent="project_execution",
            source_policy="local_and_web",
            closure_eligibility="project_summary",
            learning_state_enabled=True,
            confidence="high",
            reason="explicit_project_execution",
        )
    if any(marker in text for marker in _LEARN_MARKERS):
        return TaskContract(
            task_intent="learn",
            source_policy="local_and_web",
            closure_eligibility="learning_summary",
            learning_state_enabled=True,
            confidence="high",
            reason="explicit_learning_request",
        )
    if any(pattern.search(text) for pattern in _RESEARCH_PATTERNS):
        return TaskContract(
            task_intent="research",
            source_policy="web_only",
            closure_eligibility="optional_note",
            learning_state_enabled=False,
            confidence="high",
            reason="explicit_external_research",
        )
    if any(marker in text for marker in _ORGANIZE_MARKERS):
        return TaskContract(
            task_intent="organize",
            source_policy="model_only",
            closure_eligibility="not_applicable",
            learning_state_enabled=False,
            confidence="high",
            reason="explicit_organize_request",
        )
    if any(marker in text for marker in _CONVERSATION_MARKERS):
        return TaskContract(
            task_intent="conversation",
            source_policy="model_only",
            closure_eligibility="not_applicable",
            learning_state_enabled=False,
            confidence="high",
            reason="explicit_conversation",
        )
    if active_learning:
        return TaskContract(
            task_intent="learn",
            source_policy="local_and_web",
            closure_eligibility="learning_summary",
            learning_state_enabled=True,
            confidence="medium",
            reason="continue_active_learning",
        )
    return TaskContract(
        task_intent="quick_answer",
        source_policy="local_and_web",
        closure_eligibility="not_applicable",
        learning_state_enabled=False,
        confidence="low",
        reason="safe_default_quick_answer",
    )


def route_request_with_task_contract(**kwargs: Any) -> dict[str, Any]:
    """Add task semantics without coupling them to the role router."""

    from src.router import route_request

    route = route_request(**kwargs)
    previous_mode = str(kwargs.get("previous_mode") or "")
    contract = classify_task_contract(
        str(kwargs.get("user_input", "")),
        active_learning=previous_mode in {"苏格拉底", "费曼", "项目"},
    )
    return {**route, "task_contract": contract.to_dict()}


def _not_applicable_evaluation(
    *,
    contract: TaskContract,
    learner_input: str,
    state: LearningState,
    expected_concepts: tuple[str, ...],
    evidence: tuple[str, ...],
) -> PedagogyEvalRun:
    return PedagogyEvalRun(
        id=f"ped_eval_{uuid4().hex}",
        learner_input=learner_input,
        objective=state.objective,
        protocol=state.protocol,
        expected_concepts=expected_concepts,
        evidence=evidence,
        deterministic_result={
            "skipped": True,
            "reason": "task_contract_not_learning",
        },
        semantic_result=None,
        confidence=1.0,
        final_decision="not_applicable",
        reasons=(f"task_intent:{contract.task_intent}",),
    )


def _direct_task_plan(
    *, contract: TaskContract, learner_input: str
) -> PedagogyTurnPlan:
    knowledge_kind = classify_knowledge(learner_input)
    return PedagogyTurnPlan(
        mode="direct_answer",
        phase="answer",
        knowledge_kind=knowledge_kind,
        move="direct_explain",
        disclosure_level=5,
        target_understanding=learner_input,
        library_needed=knowledge_kind in {"empirical", "conventional", "diagnostic"},
        constraints=(
            "do_not_update_learning_state",
            f"task_intent:{contract.task_intent}",
        ),
    )


def _without_non_learning_evaluation(state: LearningState) -> LearningState:
    payload = dict(state.payload)
    evaluation = payload.get("pedagogy_evaluation")
    if isinstance(evaluation, dict) and evaluation.get("final_decision") == "not_applicable":
        payload.pop("pedagogy_evaluation", None)
    return LearningState.from_dict({**state.to_dict(), "payload": payload})


class TaskAwarePedagogyEvaluationService(PedagogyEvaluationService):
    """Skip mastery evaluation for temporary or conversational tasks."""

    def evaluate_learner(
        self,
        *,
        learner_input: str,
        state: LearningState,
        expected_concepts: tuple[str, ...] = (),
        evidence: tuple[str, ...] = (),
    ) -> PedagogyEvalRun:
        contract = classify_task_contract(
            learner_input,
            active_learning=bool(state.objective or state.protocol),
        )
        if contract.learning_state_enabled:
            return super().evaluate_learner(
                learner_input=learner_input,
                state=state,
                expected_concepts=expected_concepts,
                evidence=evidence,
            )
        return _not_applicable_evaluation(
            contract=contract,
            learner_input=learner_input,
            state=state,
            expected_concepts=expected_concepts,
            evidence=evidence,
        )


class TaskAwarePedagogyEngine(PedagogyEngine):
    """Use a direct response plan while preserving persisted learning state."""

    def plan(
        self, *, user_input: str, mode: str, state: LearningState
    ) -> tuple[PedagogyTurnPlan, LearningState]:
        contract = classify_task_contract(
            user_input,
            active_learning=bool(state.objective or state.protocol),
        )
        if contract.learning_state_enabled:
            return super().plan(user_input=user_input, mode=mode, state=state)
        preserved = _without_non_learning_evaluation(state)
        return _direct_task_plan(contract=contract, learner_input=user_input), preserved

    def apply_transition(
        self,
        *,
        before: LearningState,
        planned: LearningState,
        evaluation: AssistantResponseEvaluation,
    ) -> LearningState:
        learner_evaluation = before.payload.get("pedagogy_evaluation")
        if (
            isinstance(learner_evaluation, dict)
            and learner_evaluation.get("final_decision") == "not_applicable"
        ):
            return planned
        return super().apply_transition(
            before=before,
            planned=planned,
            evaluation=evaluation,
        )


def prepare_task_pedagogy(
    *,
    contract: TaskContract,
    learner_input: str,
    mode: str,
    state: LearningState,
    expected_concepts: tuple[str, ...],
    evidence: tuple[str, ...],
    evaluate_learner: Callable[..., PedagogyEvalRun],
    plan_pedagogy: Callable[..., tuple[PedagogyTurnPlan, LearningState]],
) -> tuple[PedagogyEvalRun, PedagogyTurnPlan, LearningState, LearningState]:
    """Pure seam for a future direct ChatService integration."""

    if contract.learning_state_enabled:
        learner_evaluation = evaluate_learner(
            learner_input=learner_input,
            state=state,
            expected_concepts=expected_concepts,
            evidence=evidence,
        )
        evaluated_state = LearningState.from_dict(
            {
                **state.to_dict(),
                "payload": {
                    **state.payload,
                    "pedagogy_evaluation": learner_evaluation.to_dict(),
                },
            }
        )
        plan, next_state = plan_pedagogy(
            user_input=learner_input,
            mode=mode,
            state=evaluated_state,
        )
        return learner_evaluation, plan, next_state, evaluated_state

    skipped = _not_applicable_evaluation(
        contract=contract,
        learner_input=learner_input,
        state=state,
        expected_concepts=expected_concepts,
        evidence=evidence,
    )
    return skipped, _direct_task_plan(contract=contract, learner_input=learner_input), state, state
