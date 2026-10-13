// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { AnswerProgress } from "./AnswerProgress";
import type { ChatResearchProgress } from "../../types";

afterEach(cleanup);

function progress(overrides: Partial<ChatResearchProgress> = {}): ChatResearchProgress {
  return {
    run_id: "research_1",
    status: "running",
    stage: "searching",
    provider_status: "ok",
    stop_reason: "",
    error: "",
    query_attempt_count: 1,
    selected_source_count: 0,
    version: 1,
    ...overrides,
  };
}

describe("AnswerProgress research opening", () => {
  it("renders the opening summary and focus while researching", () => {
    render(
      <AnswerProgress
        hasContent={false}
        progress={progress({
          approach: {
            status: "ready",
            summary: "我会比较功能覆盖与兼容性。",
            focus: ["功能覆盖"],
            origin: "model_plan",
            sequence: 1,
            mode: "standard",
          },
        })}
      />,
    );
    expect(screen.getByText("我会比较功能覆盖与兼容性。")).toBeTruthy();
    expect(screen.getByText("功能覆盖")).toBeTruthy();
    expect(screen.getByText(/已查询 1 次/)).toBeTruthy();
  });

  it("shows no opening when it is still pending", () => {
    render(
      <AnswerProgress
        hasContent={false}
        progress={progress({
          approach: { status: "pending", summary: "", focus: [], origin: "fallback", sequence: 0, mode: "standard" },
        })}
      />,
    );
    expect(screen.queryByText("我会比较功能覆盖与兼容性。")).toBeNull();
  });

  it("renders a cancelled run as stopped, never as a completed opening", () => {
    render(
      <AnswerProgress
        hasContent={false}
        progress={progress({
          status: "cancelled",
          approach: {
            status: "ready",
            summary: "我会比较功能覆盖与兼容性。",
            focus: [],
            origin: "model_plan",
            sequence: 1,
            mode: "standard",
          },
        })}
      />,
    );
    expect(screen.getByText("研究已停止")).toBeTruthy();
  });
});
