// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ChatResponse } from "../../types";
import { LearningStrip } from "./LearningStrip";
import type { LearningResumeResponse } from "./learningResumeApi";

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
    objective: "旧目标",
    phase: "scaffold",
    unresolved_gap: "旧缺口",
    confirmed_points: ["旧 confirmed point"],
    hint_level: 0,
    turn_count: 2,
  },
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

function durableResume(status: "active" | "no_active_goal" = "active"): LearningResumeResponse {
  if (status === "no_active_goal") {
    return {
      source: "durable",
      status,
      topic: {},
      goal: {},
      claims: [],
      claim_count: 0,
      unresolved: [],
      next_step: {},
      optional_next_steps: [],
    };
  }
  return {
    source: "durable",
    status,
    topic: { topic_id: "topic-1", title: "恢复" },
    goal: {
      goal_id: "goal-1",
      topic_id: "topic-1",
      objective: "durable Goal 优先",
      status: "active",
    },
    claims: [
      {
        claim_id: "claim-1",
        revision_id: "rev-2",
        text: "最新 Revision",
        claim_kind: "invariant",
        scope: "resume",
        understanding_status: "confirmed",
        validation_result: "pass",
        latest_validation: { method: "explain", result: "pass" },
        primary_evidence: {},
        supporting_evidence: [],
      },
    ],
    claim_count: 1,
    unresolved: [],
    next_step: { text: "继续 durable 下一步", status: "active", is_primary: true },
    optional_next_steps: [],
  };
}

describe("LearningStrip durable resume status", () => {
  it("keeps temporary non-learning task status when no durable active Goal exists", () => {
    const { container } = render(
      <LearningStrip
        resume={null}
        resumeError=""
        lastChat={responseWithTask({
          task_intent: "research",
          source_policy: "web_only",
          closure_eligibility: "research_summary",
          learning_state_enabled: false,
          confidence: "high",
        })}
        visitedPhases={[]}
        memoryStatus={null}
      />,
    );

    const text = container.textContent ?? "";
    expect(text).toContain("临时研究");
    expect(text).toContain("研究结果已返回");
    expect(text).toContain("不推进长期学习状态");
    expect(text).not.toContain("旧缺口");
  });

  it("keeps durable Goal visible across a temporary research detour", () => {
    const { container } = render(
      <LearningStrip
        resume={durableResume()}
        resumeError=""
        lastChat={responseWithTask({
          task_intent: "research",
          source_policy: "web_only",
          closure_eligibility: "research_summary",
          learning_state_enabled: false,
          confidence: "high",
        })}
        visitedPhases={[]}
        memoryStatus={null}
      />,
    );

    const text = container.textContent ?? "";
    expect(text).toContain("durable Goal 优先");
    expect(text).toContain("学习命题 1/1");
    expect(text).toContain("下一步：继续 durable 下一步");
    expect(text).toContain("1 条已验证");
    expect(text).not.toContain("旧目标");
    expect(text).not.toContain("旧 confirmed point");
  });

  it("surfaces stale source claims above confirmed understanding in the summary", () => {
    const resume = durableResume();
    if (resume.claims[0]) {
      resume.claims[0].freshness = {
        status: "stale_candidate",
        head_commit: "f".repeat(40),
        reason: "Primary 源码已实质变更",
      };
    }
    const { container } = render(
      <LearningStrip
        resume={resume}
        resumeError=""
        lastChat={responseWithTask({
          task_intent: "learn",
          source_policy: "local_only",
          closure_eligibility: "learning_summary",
          learning_state_enabled: true,
        })}
        visitedPhases={[]}
        memoryStatus={null}
      />,
    );

    const text = container.textContent ?? "";
    expect(text).toContain("1 条源码已变动");
    expect(text).not.toContain("1 条已验证");
  });

  it("never resurrects legacy navigation for durable no_active_goal", () => {
    const { container } = render(
      <LearningStrip
        resume={durableResume("no_active_goal")}
        resumeError=""
        lastChat={responseWithTask({
          task_intent: "learn",
          source_policy: "local_only",
          closure_eligibility: "learning_summary",
          learning_state_enabled: true,
        })}
        visitedPhases={["scaffold"]}
        memoryStatus={null}
      />,
    );

    const text = container.textContent ?? "";
    expect(text).toContain("当前没有进行中的学习目标");
    expect(text).toContain("不回退旧学习状态");
    expect(text).not.toContain("旧目标");
    expect(text).not.toContain("旧缺口");
    expect(text).not.toContain("旧 confirmed point");
  });

  it("labels explicit legacy fallback as old unverified state", () => {
    const resume: LearningResumeResponse = {
      source: "legacy_fallback",
      status: "legacy",
      topic: {},
      goal: { objective: "旧目标", status: "legacy_unverified" },
      claims: [],
      claim_count: 0,
      unresolved: [{ text: "旧缺口", reason: "legacy_unverified" }],
      next_step: {},
      optional_next_steps: [],
      legacy_confirmed_points: ["旧 confirmed point"],
    };
    const { container } = render(
      <LearningStrip
        resume={resume}
        resumeError=""
        lastChat={responseWithTask({
          task_intent: "learn",
          source_policy: "local_only",
          closure_eligibility: "learning_summary",
          learning_state_enabled: true,
        })}
        visitedPhases={["scaffold"]}
        memoryStatus={null}
      />,
    );

    const text = container.textContent ?? "";
    expect(text).toContain("旧目标");
    expect(text).toContain("旧缺口");
    expect(text).toContain("旧记录 · 未升级");
    expect(text).not.toContain("已验证");
  });
});
