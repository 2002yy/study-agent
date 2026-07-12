import { describe, expect, it } from "vitest";
import {
  closureActionLabel,
  taskContractFromRoute,
  taskIntentLabel,
} from "./taskContract";

describe("taskContract", () => {
  it("parses a persisted route task contract", () => {
    const contract = taskContractFromRoute({
      task_contract: {
        task_intent: "research",
        source_policy: "web_only",
        closure_eligibility: "optional_note",
        learning_state_enabled: false,
        confidence: "high",
      },
    });

    expect(contract).toEqual({
      task_intent: "research",
      source_policy: "web_only",
      closure_eligibility: "optional_note",
      learning_state_enabled: false,
      confidence: "high",
      reason: undefined,
    });
  });

  it("keeps historical routes compatible", () => {
    expect(taskContractFromRoute({ mode: "普通" })).toBeUndefined();
    expect(closureActionLabel(undefined)).toBe("整理学习");
  });

  it("labels temporary and learning tasks separately", () => {
    expect(taskIntentLabel("research")).toBe("临时研究");
    expect(taskIntentLabel("quick_answer")).toBe("快速问答");
    expect(taskIntentLabel("learn")).toBe("系统学习");
  });

  it("only exposes closure actions for eligible task results", () => {
    expect(
      closureActionLabel({
        task_intent: "research",
        source_policy: "web_only",
        closure_eligibility: "optional_note",
        learning_state_enabled: false,
      })
    ).toBeNull();
    expect(
      closureActionLabel({
        task_intent: "learn",
        source_policy: "local_and_web",
        closure_eligibility: "learning_summary",
        learning_state_enabled: true,
      })
    ).toBe("整理学习");
    expect(
      closureActionLabel({
        task_intent: "project_execution",
        source_policy: "local_and_web",
        closure_eligibility: "project_summary",
        learning_state_enabled: true,
      })
    ).toBe("收束项目");
  });
});
