import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
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

function responseWithTask(taskContract: Record<string, unknown>): ChatResponse {
  return {
    reply: "done",
    session_id: "chat-1",
    route: {
      task_contract: taskContract,
      learning_state: {
        protocol: "socratic_rediscovery",
        phase: "scaffold",
        unresolved_gap: "old gap",
      },
    },
    rag: baseRag,
  };
}

describe("LearningStrip task contract", () => {
  it("shows a non-learning notice for temporary research", () => {
    let renderer: ReactTestRenderer;
    act(() => {
      renderer = create(
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
    });

    const text = JSON.stringify(renderer!.toJSON());
    expect(text).toContain("临时研究");
    expect(text).toContain("本轮不会计入长期学习进度");
    expect(text).not.toContain("old gap");
  });

  it("keeps the expandable learning strip for learning tasks", () => {
    let renderer: ReactTestRenderer;
    act(() => {
      renderer = create(
        <LearningStrip
          lastChat={responseWithTask({
            task_intent: "learn",
            source_policy: "local_and_web",
            closure_eligibility: "learning_summary",
            learning_state_enabled: true,
            confidence: "high",
          })}
          visitedPhases={["scaffold"]}
          memoryStatus={null}
        />
      );
    });

    const text = JSON.stringify(renderer!.toJSON());
    expect(text).toContain("苏格拉底");
    expect(text).toContain("old gap");
  });
});
