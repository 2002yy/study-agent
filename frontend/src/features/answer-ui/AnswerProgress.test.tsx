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
  it("shows provisional synthesis while keeping its original quotes available on demand", () => {
    const { container, rerender } = render(<AnswerProgress hasContent={false} progress={progress({
      read_count: 1,
      approach: { status: "ready", summary: "Opening plan", focus: ["Focus"], origin: "model_plan", sequence: 1, mode: "deep" },
      narration: [{ block_id: "step1", text: "Reading sources" }],
      interim_analysis: { status: "provisional", text: "A tentative comparison, with remaining gaps.", citations: [
        { url: "https://example.org/source", title: "Real source", quote: "Original source statement." },
      ] },
      findings: [{ id: "f1", kind: "source_excerpt", title: "Real source", url: "https://example.org/source", text: "Original source statement." }],
    })} />);
    expect(screen.getByRole("region", { name: "阶段性分析" })).toBeVisible();
    expect(screen.getByText("A tentative comparison, with remaining gaps.")).toBeVisible();
    expect(container.querySelector(".research-status-line")).toBeNull();
    expect(container.querySelector(".answer-progress-approach")).toBeNull();
    expect(container.querySelectorAll("details")).toHaveLength(1);
    expect(screen.getByText(/阶段性判断，可能随新资料调整/)).not.toBeVisible();
    expect(container.querySelector("details.research-interim-citations")).not.toHaveAttribute("open");
    expect(screen.queryByRole("region", { name: "已读资料摘录" })).toBeNull();
    rerender(<AnswerProgress hasContent={false} progress={progress({ interim_analysis: null })} />);
    expect(screen.queryByRole("region", { name: "阶段性分析" })).toBeNull();
  });
  it("groups sources by actual questions and marks missing body without claiming support", () => {
    render(<AnswerProgress hasContent={false} progress={progress({
      read_count: 2,
      findings: [
        { id: "a1", kind: "source_excerpt", title: "Source A", url: "https://example.org/a", text: "A body", question: "Photoshop scripting" },
        { id: "b1", kind: "source_excerpt", title: "Source B", url: "https://example.org/b", text: "B body", question: "GIMP scripting" },
        { id: "a2", kind: "source_excerpt", title: "Source A2", url: "https://example.org/a2", text: "A2 body", question: "Photoshop scripting" },
      ], reading_gaps: ["PSD compatibility"],
    })} />);
    expect(screen.getAllByText("Photoshop scripting")).toHaveLength(1);
    expect(screen.getByText("GIMP scripting")).toBeVisible();
    expect(screen.getByText("暂无正文：PSD compatibility")).toBeVisible();
    expect(screen.queryByText(/已支持|全部完成/)).toBeNull();
  });
  it("shows read excerpts before an answer with attribution and provisional wording", () => {
    const { container } = render(<AnswerProgress hasContent={false} progress={progress({
      read_count: 1, findings: [{ id: "f1", kind: "source_excerpt", title: "Official source", url: "https://example.org/source", text: "Useful source content <script>test</script>" }],
    })} />);
    expect(screen.getByRole("region", { name: "已读资料摘录" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Official source" })).toHaveAttribute("href", "https://example.org/source");
    expect(screen.getByText("原文摘录，尚非结论")).toBeVisible();
    expect(screen.getByText("Useful source content <script>test</script>")).toBeVisible();
    expect(container.querySelector("script")).toBeNull();
  });

  it("rejects unsafe excerpt links and removes invalidated snapshots", () => {
    const { rerender } = render(<AnswerProgress hasContent={false} progress={progress({
      findings: [{ id: "f1", kind: "source_excerpt", title: "unsafe", url: "javascript:alert(1)", text: "unsafe" }],
    })} />);
    expect(screen.queryByRole("region", { name: "已读资料摘录" })).toBeNull();
    rerender(<AnswerProgress hasContent={false} progress={progress({ findings: [] })} />);
    expect(screen.queryByRole("region", { name: "已读资料摘录" })).toBeNull();
  });
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
    expect(screen.getByText(/查询 1/)).toBeTruthy();
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
    const { container } = render(
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
    // Terminal state must not keep a spinner alive.
    expect(container.querySelector(".spin")).toBeNull();
  });

  it("states honestly when no usable text has been read yet", () => {
    render(<AnswerProgress hasContent={false} progress={progress({ read_count: 0 })} />);
    expect(screen.getByText("查询 1 · 已读 0")).toBeTruthy();
    expect(screen.getByText("暂未取得可用正文，正在尝试其他来源。")).toBeTruthy();
  });

  it("does not claim missing text once a usable source was read", () => {
    render(<AnswerProgress hasContent={false} progress={progress({ read_count: 2 })} />);
    expect(screen.getByText("查询 1 · 已读 2")).toBeTruthy();
    expect(screen.queryByText("暂未取得可用正文，正在尝试其他来源。")).toBeNull();
  });

  it("keeps the search process collapsed and expends it on demand", () => {
    const { container } = render(<AnswerProgress hasContent progress={progress({
      status: "completed",
      narration: [{ block_id: "b1", text: "已开始检索候选资料。" }],
    })} />);
    expect(screen.getByText("研究过程已结束")).toBeTruthy();
    const details = container.querySelector("details.research-narration");
    expect(details).not.toHaveAttribute("open");
    expect(screen.getByText("查看搜索过程与失败原因")).toBeTruthy();
    expect(container.querySelector(".spin")).toBeNull();
  });
});
