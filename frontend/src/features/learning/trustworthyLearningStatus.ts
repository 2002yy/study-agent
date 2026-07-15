import type { LearningState } from "../../types";

export type LearningVerificationStatus =
  | "verified"
  | "pending_validation"
  | "needs_reteach"
  | "pending_semantic_review";

export type LearningVerification = {
  status: LearningVerificationStatus;
  label: "已验证" | "待验证" | "需重讲" | "待语义复核";
  detail: string;
  confidence: number | null;
};

export type TrustworthyLearningStatus = {
  state: LearningState | null;
  objective: string;
  phase: string;
  unresolvedGap: string;
  nextAction: string;
  verification: LearningVerification;
};

type EvaluationPayload = {
  final_decision?: unknown;
  confidence?: unknown;
  reasons?: unknown;
  deterministic_result?: unknown;
  semantic_result?: unknown;
};

export function projectTrustworthyLearningStatus(
  raw: unknown
): TrustworthyLearningStatus {
  const state = asLearningState(raw);
  const objective = state?.objective.trim() ?? "";
  const phase = state?.phase.trim() ?? "";
  const unresolvedGap = state?.unresolved_gap.trim() ?? "";
  const nextAction = committedNextAction(state);
  return {
    state,
    objective,
    phase,
    unresolvedGap,
    nextAction,
    verification: verificationFromState(state),
  };
}

export function verificationFromState(
  state: LearningState | null
): LearningVerification {
  const evaluation = evaluationFromState(state);
  if (!evaluation) {
    return {
      status: "pending_validation",
      label: "待验证",
      detail: "尚无已提交的理解验证结果",
      confidence: null,
    };
  }

  const decision = text(evaluation.final_decision);
  const reasons = stringList(evaluation.reasons);
  const deterministic = record(evaluation.deterministic_result);
  const semantic = record(evaluation.semantic_result);
  const misconceptions = [
    ...stringList(deterministic?.misconceptions),
    ...stringList(semantic?.misconceptions),
  ];
  const confidence = finiteNumber(evaluation.confidence);

  if (decision === "accept") {
    return {
      status: "verified",
      label: "已验证",
      detail: "最近一次已提交理解验证通过",
      confidence,
    };
  }

  if (decision === "needs_semantic_review") {
    return {
      status: "pending_semantic_review",
      label: "待语义复核",
      detail: "当前结果不能可靠自动判定，未推进掌握结论",
      confidence,
    };
  }

  if (
    misconceptions.length > 0 ||
    reasons.includes("semantic_misconception") ||
    text(deterministic?.reason) === "claim_conflicts_with_known_constraints"
  ) {
    return {
      status: "needs_reteach",
      label: "需重讲",
      detail: "最近一次验证发现明确概念冲突，需要先纠正",
      confidence,
    };
  }

  return {
    status: "pending_validation",
    label: "待验证",
    detail: pendingValidationDetail(reasons, deterministic),
    confidence,
  };
}

function asLearningState(raw: unknown): LearningState | null {
  const value = record(raw);
  if (!value) return null;
  return {
    protocol: text(value.protocol),
    protocol_version: finiteNumber(value.protocol_version) ?? undefined,
    objective: text(value.objective),
    phase: text(value.phase),
    learner_claim: text(value.learner_claim) || undefined,
    confirmed_points: stringList(value.confirmed_points),
    unresolved_gap: text(value.unresolved_gap),
    attempted_examples: stringList(value.attempted_examples),
    hint_level: finiteNumber(value.hint_level) ?? 0,
    library_facts_given: stringList(value.library_facts_given),
    turn_count: finiteNumber(value.turn_count) ?? 0,
    payload: record(value.payload) ?? {},
  };
}

function evaluationFromState(
  state: LearningState | null
): EvaluationPayload | null {
  const evaluation = record(state?.payload?.pedagogy_evaluation);
  return evaluation as EvaluationPayload | null;
}

function committedNextAction(state: LearningState | null): string {
  const payload = state?.payload ?? {};
  const nextAction = text(payload.next_action);
  return nextAction;
}

function pendingValidationDetail(
  reasons: string[],
  deterministic: Record<string, unknown> | null
): string {
  if (reasons.includes("reasoning_incomplete")) {
    return "解释还不完整，需要继续说明推理过程";
  }
  if (reasons.includes("transfer_not_ready")) {
    return "当前解释尚未通过迁移验证";
  }
  if (reasons.includes("low_confidence")) {
    return "证据不足，暂不判定为已掌握";
  }
  if (
    text(deterministic?.reason) === "understanding_asserted_without_reasoning" ||
    text(deterministic?.reason) === "no_conclusion_claim"
  ) {
    return "仅表达理解不足以验证，需要给出自己的解释";
  }
  return "最近一次验证尚未达到通过条件";
}

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function text(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => text(item)).filter(Boolean);
}

function finiteNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}
