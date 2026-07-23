// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ChatResponse } from "../../types";
import { LearningPanel } from "./LearningPanel";

const rag: ChatResponse["rag"] = {
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

function learningResponse(): ChatResponse {
  return {
    reply: "继续验证",
    session_id: "chat-1",
    route: {
      learning_state: {
        protocol: "socratic_rediscovery",
        objective: "理解二分查找复杂度",
        phase: "scaffold",
        unresolved_gap: "还不能解释循环不变量",
        confirmed_points: ["每轮缩小一半搜索区间", "时间复杂度为 O(log n)"],
        hint_level: 1,
        turn_count: 4,
      },
    },
    rag,
  };
}

describe("LearningPanel evidence summary", () => {
  it("shows committed evidence and trustworthy evaluation without a mastery estimate", () => {
    const { container } = render(
      <LearningPanel
        lastChat={learningResponse()}
        visitedPhases={["orientation", "scaffold"]}
        memoryStatus={null}
      />
    );

    const text = container.textContent ?? "";
    expect(text).toContain("最近评估");
    expect(text).toContain("待验证");
    expect(text).toContain("已记录的学习证据");
    expect(text).toContain("已确认知识点");
    expect(text).toContain("已使用第 1 级提示");
    expect(text).toContain("不换算为掌握度");
    expect(container.querySelector(".mastery-ring")).toBeNull();
  });
});
