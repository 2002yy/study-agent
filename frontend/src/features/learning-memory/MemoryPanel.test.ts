import { describe, expect, it } from "vitest";
import {
  buildMemoryUpdatePayload,
  buildMemoryUpdatePayloads,
  memoryActionLabel,
  memoryConfidenceLabel,
  memoryTargetLabel,
} from "./MemoryPanel";

describe("memory update payload builders", () => {
  it("builds append updates for normal memory targets", () => {
    expect(
      buildMemoryUpdatePayload({
        target: "progress",
        content: "  finished RAG wiring  ",
        replaceCurrentFocus: true,
        learnerPending: true
      })
    ).toEqual({
      target: "progress",
      content: "finished RAG wiring",
      append: true,
      learner_pending: true
    });
  });

  it("allows current_focus replacement when explicitly selected", () => {
    expect(
      buildMemoryUpdatePayload({
        target: "current_focus",
        content: "Only finish memory UI",
        replaceCurrentFocus: true,
        learnerPending: false
      })
    ).toEqual({
      target: "current_focus",
      content: "Only finish memory UI",
      append: false,
      learner_pending: false
    });
  });

  it("rejects disabled or blank memory candidates", () => {
    expect(
      buildMemoryUpdatePayload({
        target: "summary",
        content: "important but unchecked",
        replaceCurrentFocus: false,
        learnerPending: false,
        enabled: false
      })
    ).toBeNull();
    expect(
      buildMemoryUpdatePayload({
        target: "summary",
        content: "   ",
        replaceCurrentFocus: false,
        learnerPending: false
      })
    ).toBeNull();
  });

  it("builds a multi-candidate payload from enabled non-empty drafts", () => {
    expect(
      buildMemoryUpdatePayloads([
        {
          target: "progress",
          content: "第一条进展",
          replaceCurrentFocus: false,
          learnerPending: false,
          enabled: true
        },
        {
          target: "summary",
          content: "  ",
          replaceCurrentFocus: false,
          learnerPending: false,
          enabled: true
        },
        {
          target: "current_focus",
          content: "下一步只做群聊搜索",
          replaceCurrentFocus: true,
          learnerPending: true,
          enabled: true
        }
      ])
    ).toEqual([
      {
        target: "progress",
        content: "第一条进展",
        append: true,
        learner_pending: false
      },
      {
        target: "current_focus",
        content: "下一步只做群聊搜索",
        append: false,
        learner_pending: true
      }
    ]);
  });
});

describe("memory presentation labels", () => {
  it("uses user-facing labels instead of storage target identifiers", () => {
    expect(memoryTargetLabel("current_focus")).toBe("当前重点");
    expect(memoryTargetLabel("learner_profile")).toBe("学习偏好");
    expect(memoryTargetLabel("session_archive")).toBe("本次学习归档");
    expect(memoryTargetLabel("unknown_target")).toBe("长期记忆");
  });

  it("translates low-level write actions and confidence values", () => {
    expect(memoryActionLabel("append")).toBe("追加");
    expect(memoryActionLabel("replace")).toBe("替换");
    expect(memoryActionLabel("created")).toBe("新建");
    expect(memoryActionLabel("upsert")).toBe("更新");
    expect(memoryConfidenceLabel("high")).toBe("高");
    expect(memoryConfidenceLabel("medium")).toBe("中");
    expect(memoryConfidenceLabel("low")).toBe("低");
    expect(memoryConfidenceLabel("internal_code")).toBe("未标注");
  });
});
