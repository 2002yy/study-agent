import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
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
  it("shows observable learning evidence without a mastery estimate", () => {
    let renderer!: ReactTestRenderer;
    act(() => {
      renderer = create(
        <LearningPanel
          lastChat={learningResponse()}
          visitedPhases={["orientation", "scaffold"]}
          memoryStatus={null}
        />
      );
    });

    const serialized = JSON.stringify(renderer.toJSON());
    expect(serialized).toContain("本轮学习证据");
    expect(serialized).toContain("已确认知识点");
    expect(serialized).toContain("已使用第 1 级提示");
    expect(serialized).toContain("不推算掌握百分比");
    expect(serialized).not.toContain("mastery-ring");

    act(() => renderer.unmount());
  });
});
