// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ChatResponse } from "../../types";
import { LearningStrip } from "./LearningStrip";

const baseRag: ChatResponse["rag"] = {
  status: "waiting",
  query: "",
  retrieval_mode: "",
  reason: "",
  context: "",
  sources: "",
  result_count: 0,
  results: [],
  debug: {},
  attempts: [],
  rewritten_query: "",
};

function responseWithTask(
  taskContract: Record<string, unknown>,
  learningState: Record<string, unknown> = {
    protocol: "socratic_rediscovery",
    objective: "理解二分查找复杂度",
    phase: "scaffold",
    unresolved_gap: "old gap",
    hint_level: 0,
    turn_count: 2,
    payload: {},
  }
): ChatResponse {
  return {
    reply: "done",
    session_id: "chat-1",
    route: {
      task_contract: taskContract,
      learning_state: learningState,
    },
    rag: baseRag,
  };
}

describe("LearningStrip trustworthy status", () => {
  it("shows task status instead of learning verification for temporary research", () => {
    const { container } = render(
      <LearningStrip
        lastChat={responseWithTask({
          task_intent: "research",
          source_policy: "web_only",
          closure_eligibility: "research_summary",
          learning_state_enabled: false,
          confidence: "high",
        })}
        visitedPhases={[]}
        memoryStatus={null}
      />
    );

    const text = container.textContent ?? "";
    expect(text).toContain("临时研究");
    expect(text).toContain("研究结果已返回");
    expect(text).toContain("不推进长期学习状态");
    expect(text).not.toContain("old gap");
    expect(text).not.toContain("已验证");
    expect(text).not.toContain("待验证");
  });

  it("orders collapsed learning truth as objective, phase, gap-next and evaluation", () => {
    const { container } = render(
      <LearningStrip
        lastChat={responseWithTask(
          {
            task_intent: "learn",
            source_policy: "local_and_web",
            closure_eligibility: "learning_summary",
            learning_state_enabled: true,
            confidence: "high",
          },
          {
            protocol: "socratic_rediscovery",
            objective: "理解二分查找复杂度",
            phase: "scaffold",
            unresolved_gap: "边界条件",
            hint_level: 0,
            turn_count: 3,
            payload: {
              pedagogy_evaluation: {
                final_decision: "accept",
                confidence: 0.9,
              },
            },
          }
        )}
        visitedPhases={["scaffold"]}
        memoryStatus={null}
      />
    );

    const text = container.textContent ?? "";
    const objectiveIndex = text.indexOf("理解二分查找复杂度");
    const phaseIndex = text.indexOf("提供线索");
    const gapIndex = text.indexOf("缺口：边界条件");
    const evaluationIndex = text.indexOf("已验证");

    expect(objectiveIndex).toBeGreaterThanOrEqual(0);
    expect(phaseIndex).toBeGreaterThan(objectiveIndex);
    expect(gapIndex).toBeGreaterThan(phaseIndex);
    expect(evaluationIndex).toBeGreaterThan(gapIndex);
    expect(text).not.toContain("掌握百分比");
  });

  it("shows committed next action when no unresolved gap exists", () => {
    const { container } = render(
      <LearningStrip
        lastChat={responseWithTask(
          {
            task_intent: "project_execution",
            source_policy: "local_only",
            closure_eligibility: "project_summary",
            learning_state_enabled: true,
          },
          {
            protocol: "project_execution",
            objective: "完成 API 重构",
            phase: "verify",
            unresolved_gap: "",
            hint_level: 0,
            turn_count: 4,
            payload: {
              next_action: "重新运行完整测试",
              planned_next_action: "不得展示",
            },
          }
        )}
        visitedPhases={[]}
        memoryStatus={null}
      />
    );

    const text = container.textContent ?? "";
    expect(text).toContain("下一步：重新运行完整测试");
    expect(text).not.toContain("planned_next_action");
  });
});
