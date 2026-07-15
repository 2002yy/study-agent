import { describe, expect, it } from "vitest";

import {
  projectTrustworthyLearningStatus,
  verificationFromState,
} from "./trustworthyLearningStatus";
import type { LearningState } from "../../types";

function stateWithEvaluation(evaluation: Record<string, unknown>): LearningState {
  return {
    protocol: "socratic_rediscovery",
    objective: "理解二分查找复杂度",
    phase: "guided_practice",
    unresolved_gap: "边界条件",
    confirmed_points: ["区间每轮减半"],
    hint_level: 0,
    turn_count: 3,
    payload: { pedagogy_evaluation: evaluation },
  };
}

describe("trustworthy learning status", () => {
  it("maps accepted committed evaluation to verified", () => {
    const result = verificationFromState(
      stateWithEvaluation({
        final_decision: "accept",
        confidence: 0.91,
        reasons: [],
      })
    );

    expect(result.status).toBe("verified");
    expect(result.label).toBe("已验证");
    expect(result.confidence).toBe(0.91);
  });

  it("maps unavailable semantic review to pending semantic review", () => {
    const result = verificationFromState(
      stateWithEvaluation({
        final_decision: "needs_semantic_review",
        confidence: 0,
        reasons: ["semantic_evaluator_unavailable"],
      })
    );

    expect(result.status).toBe("pending_semantic_review");
    expect(result.label).toBe("待语义复核");
  });

  it("maps explicit misconceptions to needs reteach", () => {
    const result = verificationFromState(
      stateWithEvaluation({
        final_decision: "reject",
        confidence: 1,
        reasons: ["semantic_misconception"],
        semantic_result: {
          misconceptions: ["把 O(log n) 说成 O(n)"],
        },
      })
    );

    expect(result.status).toBe("needs_reteach");
    expect(result.label).toBe("需重讲");
  });

  it("keeps incomplete or low-confidence understanding pending validation", () => {
    const incomplete = verificationFromState(
      stateWithEvaluation({
        final_decision: "reject",
        confidence: 0.82,
        reasons: ["reasoning_incomplete"],
      })
    );
    const lowConfidence = verificationFromState(
      stateWithEvaluation({
        final_decision: "reject",
        confidence: 0.42,
        reasons: ["low_confidence"],
      })
    );

    expect(incomplete.status).toBe("pending_validation");
    expect(incomplete.detail).toContain("推理过程");
    expect(lowConfidence.status).toBe("pending_validation");
    expect(lowConfidence.detail).toContain("暂不判定为已掌握");
  });

  it("does not treat bare understanding claims as verified", () => {
    const result = verificationFromState(
      stateWithEvaluation({
        final_decision: "reject",
        deterministic_result: {
          is_claim: false,
          reason: "understanding_asserted_without_reasoning",
        },
      })
    );

    expect(result.status).toBe("pending_validation");
    expect(result.detail).toContain("自己的解释");
  });

  it("projects only committed gap and committed next action", () => {
    const projected = projectTrustworthyLearningStatus({
      protocol: "project_execution",
      objective: "完成 API 重构",
      phase: "run_validation",
      unresolved_gap: "剩余一个类型错误",
      hint_level: 0,
      turn_count: 4,
      payload: {
        next_action: "修复类型错误后重新运行测试",
        planned_next_action: "不得展示这个 planned 字段",
      },
    });

    expect(projected.objective).toBe("完成 API 重构");
    expect(projected.phase).toBe("run_validation");
    expect(projected.unresolvedGap).toBe("剩余一个类型错误");
    expect(projected.nextAction).toBe("修复类型错误后重新运行测试");
    expect(projected.verification.label).toBe("待验证");
  });
});
