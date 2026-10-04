// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ChatResponse } from "../../types";
import { LearningPanel } from "./LearningPanel";
import type { LearningResumeResponse } from "./learningResumeApi";

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

function legacyChat(): ChatResponse {
  return {
    reply: "旧状态",
    session_id: "chat-1",
    route: {
      learning_state: {
        protocol: "socratic_rediscovery",
        objective: "旧目标不得覆盖 durable",
        phase: "scaffold",
        unresolved_gap: "旧缺口不得覆盖 durable",
        confirmed_points: ["旧 confirmed point 不得变 Claim"],
        hint_level: 1,
        turn_count: 4,
      },
    },
    rag,
  };
}

function durableResume(): LearningResumeResponse {
  return {
    source: "durable",
    status: "active",
    topic: { topic_id: "topic-1", title: "会话恢复" },
    goal: {
      goal_id: "goal-1",
      topic_id: "topic-1",
      objective: "理解 durable ResumeContext",
      status: "active",
    },
    claims: [
      {
        claim_id: "claim-1",
        revision_id: "rev-2",
        text: "最新 Revision 决定恢复时看到的 Claim 文本。",
        claim_kind: "invariant",
        scope: "session recovery",
        understanding_status: "confirmed",
        validation_result: "pass",
        latest_validation: {
          method: "explain",
          result: "pass",
          verified_at: "2026-08-09T10:00:00Z",
        },
        primary_evidence: {
          evidence_id: "evidence-1",
          role: "primary",
          repository: "2002yy/study-agent",
          commit_sha: "a".repeat(40),
          tree_sha: "b".repeat(40),
          path: "src/application/learning_resume.py",
          file_sha: "file-a",
          symbol: "LearningResumeService.build",
          symbol_kind: "method",
          start_line: 30,
          end_line: 80,
          evidence_kind: "search_result",
        },
        supporting_evidence: [
          {
            evidence_id: "evidence-2",
            role: "supporting_corroborating",
            repository: "2002yy/study-agent",
            commit_sha: "a".repeat(40),
            tree_sha: "b".repeat(40),
            path: "tests/test_learning_resume.py",
            file_sha: "file-b",
            symbol: "test_durable_resume_uses_latest_revision_and_bounded_semantic_state",
            symbol_kind: "function",
            start_line: 50,
            end_line: 100,
            evidence_kind: "search_result",
          },
        ],
      },
    ],
    claim_count: 1,
    unresolved: [
      {
        hypothesis_id: "hyp-1",
        text: "跨设备恢复仍需后续验证",
        reason: "missing_source",
      },
    ],
    next_step: {
      next_step_id: "step-1",
      text: "验证恢复 API 的浏览器行为",
      status: "active",
      is_primary: true,
    },
    optional_next_steps: [],
  };
}

describe("LearningPanel durable resume", () => {
  it("renders durable Goal, latest Claim, understanding and exact source evidence", () => {
    const { container } = render(
      <LearningPanel
        resume={durableResume()}
        resumeError=""
        lastChat={legacyChat()}
        visitedPhases={["orientation", "scaffold"]}
        memoryStatus={null}
      />,
    );

    const text = container.textContent ?? "";
    expect(text).toContain("理解 durable ResumeContext");
    expect(text).toContain("最新 Revision 决定恢复时看到的 Claim 文本");
    expect(text).toContain("已验证理解");
    expect(text).toContain("主要证据");
    expect(text).toContain("LearningResumeService.build");
    expect(text).toContain("跨设备恢复仍需后续验证");
    expect(text).toContain("验证恢复 API 的浏览器行为");
    expect(text).not.toContain("旧 confirmed point 不得变 Claim");
    expect(container.querySelector(".mastery-ring")).toBeNull();
  });

  it("does not resurrect legacy learning_state when durable context has no active Goal", () => {
    const resume: LearningResumeResponse = {
      source: "durable",
      status: "no_active_goal",
      topic: {},
      goal: {},
      claims: [],
      claim_count: 0,
      unresolved: [],
      next_step: {},
      optional_next_steps: [],
    };

    const { container } = render(
      <LearningPanel
        resume={resume}
        resumeError=""
        lastChat={legacyChat()}
        visitedPhases={["scaffold"]}
        memoryStatus={null}
      />,
    );

    const text = container.textContent ?? "";
    expect(text).toContain("当前没有进行中的已保存的学习目标");
    expect(text).toContain("不会读取旧学习状态");
    expect(text).not.toContain("旧目标不得覆盖 durable");
    expect(text).not.toContain("旧 confirmed point 不得变 Claim");
  });

  it("shows legacy confirmed_points only as unverified compatibility data", () => {
    const resume: LearningResumeResponse = {
      source: "legacy_fallback",
      status: "legacy",
      topic: {},
      goal: { objective: "旧目标不得覆盖 durable", status: "legacy_unverified" },
      claims: [],
      claim_count: 0,
      unresolved: [],
      next_step: {},
      optional_next_steps: [],
      legacy_confirmed_points: ["旧 confirmed point 不得变 Claim"],
    };

    const { container } = render(
      <LearningPanel
        resume={resume}
        resumeError=""
        lastChat={legacyChat()}
        visitedPhases={["scaffold"]}
        memoryStatus={null}
      />,
    );

    const text = container.textContent ?? "";
    expect(text).toContain("旧版已确认点");
    expect(text).toContain("旧 confirmed point 不得变 Claim");
    expect(text).toContain("不是学习命题");
    expect(text).not.toContain("Durable Claims");
    expect(text).not.toContain("已掌握知识点");
  });

  describe("durable claim freshness", () => {
    afterEach(() => vi.unstubAllGlobals());

    it("surfaces a stale source claim with a revalidate action and refreshes after success", async () => {
      const fetchMock = vi.fn(
        async (_input: RequestInfo | URL, _init?: RequestInit) =>
          new Response(
            JSON.stringify({
              claim_id: "claim-1",
              outcome: "revalidated",
              revision_id: "rev-3",
              head_commit: "c".repeat(40),
              freshness_status: "current",
            }),
            {
              status: 200,
              headers: { "Content-Type": "application/json" },
            },
          ),
      );
      vi.stubGlobal("fetch", fetchMock);

      const resume = durableResume();
      if (resume.claims[0]) {
        resume.claims[0].freshness = {
          status: "stale_candidate",
          head_commit: "f".repeat(40),
          reason: "Primary 源码已实质变更",
          primary: {
            role: "primary",
            path: "src/application/learning_resume.py",
            materially_changed: true,
            reason: "Primary 源码已实质变更",
          },
        };
      }
      const onRevalidated = vi.fn();
      const { container } = render(
        <LearningPanel
          resume={resume}
          resumeError=""
          sessionId="session-1"
          onRevalidated={onRevalidated}
          lastChat={null}
          visitedPhases={[]}
          memoryStatus={null}
        />,
      );

      const text = container.textContent ?? "";
      expect(text).toContain("源码已变动");
      expect(text).toContain("原因待确认");
      const button = within(container).getByRole("button", { name: /重新验证/ });
      expect(button).toBeInTheDocument();
      fireEvent.click(button);

      await waitFor(() => expect(onRevalidated).toHaveBeenCalledTimes(1));
      expect(fetchMock).toHaveBeenCalledTimes(1);
      const [url, options] = fetchMock.mock.calls[0];
      expect(String(url)).toBe(
        "/sessions/session-1/claims/claim-1/revalidate",
      );
      expect(options?.method).toBe("POST");
    });

    it("does not offer revalidation when freshness is unavailable", () => {
      const resume = durableResume();
      if (resume.claims[0]) {
        resume.claims[0].freshness = {
          status: "unavailable",
          unavailable_reason: "unavailable: NetworkError: boom",
        };
      }
      const { container } = render(
        <LearningPanel
          resume={resume}
          resumeError=""
          sessionId="session-1"
          onRevalidated={() => undefined}
          lastChat={null}
          visitedPhases={[]}
          memoryStatus={null}
        />,
      );

      const text = container.textContent ?? "";
      expect(text).toContain("源码新鲜度暂不可用");
      expect(text).toContain("评估失败，请稍后重试。");
      expect(
        within(container).queryByRole("button", { name: /重新验证/ }),
      ).toBeNull();
    });

    it("keeps current claims unobtrusive", () => {
      const resume = durableResume();
      if (resume.claims[0]) {
        resume.claims[0].freshness = {
          status: "current",
          head_commit: "c".repeat(40),
        };
      }
      const { container } = render(
        <LearningPanel
          resume={resume}
          resumeError=""
          sessionId="session-1"
          onRevalidated={() => undefined}
          lastChat={null}
          visitedPhases={[]}
          memoryStatus={null}
        />,
      );

      const text = container.textContent ?? "";
      expect(text).not.toContain("源码已变动");
      expect(text).not.toContain("源码新鲜度暂不可用");
      expect(
        within(container).queryByRole("button", { name: /重新验证/ }),
      ).toBeNull();
    });
  });
});
