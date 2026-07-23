// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, type RenderResult } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { SemanticSessionRow } from "../sessions/sessionNavigation";
import type { TaskIntent } from "../task/taskContract";
import { RestoreCard } from "./RestoreCard";

type RenderOptions = {
  session?: SemanticSessionRow | null;
  streamRecovery?: {
    question: string;
    reply: string;
    reason: string;
    sessionId?: string;
    turnId?: string | null;
  } | null;
  onSelectEntry?: (intent: TaskIntent, prompt: string) => void;
  onContinueHere?: (prompt: string) => void;
  onContinueInterrupted?: () => void;
  onRetryInterrupted?: () => void;
  onAbandonInterrupted?: () => Promise<void> | void;
};

function renderCard(options: RenderOptions = {}): RenderResult {
  return render(
    <RestoreCard
      session={options.session ?? null}
      streamRecovery={options.streamRecovery ?? null}
      onSelectEntry={options.onSelectEntry ?? (() => undefined)}
      onUpload={() => undefined}
      onContinueHere={options.onContinueHere ?? (() => undefined)}
      onStartNewTopic={() => undefined}
      onContinueInterrupted={options.onContinueInterrupted ?? (() => undefined)}
      onRetryInterrupted={options.onRetryInterrupted ?? (() => undefined)}
      onAbandonInterrupted={options.onAbandonInterrupted ?? (() => undefined)}
    />,
  );
}

describe("RestoreCard", () => {
  it("shows five explicit entry points for a new session", () => {
    const onSelectEntry = vi.fn<(intent: TaskIntent, prompt: string) => void>();
    const { container } = renderCard({ onSelectEntry });
    const text = container.textContent ?? "";

    expect(text).toContain("快速问答");
    expect(text).toContain("系统学习");
    expect(text).toContain("联网研究");
    expect(text).toContain("项目推进");
    expect(text).toContain("上传资料");

    const learningButton = screen
      .getAllByRole("button")
      .find((button) => (button.textContent ?? "").includes("系统学习"));
    fireEvent.click(learningButton as HTMLButtonElement);
    expect(onSelectEntry).toHaveBeenCalledWith("learn", "我想系统学习：");
  });

  it("shows committed learning restore facts for returning users", () => {
    const onContinueHere = vi.fn<(prompt: string) => void>();
    const session: SemanticSessionRow = {
      session_id: "session-learning",
      kind: "current",
      name: "session-learning.md",
      path: "",
      size_bytes: 0,
      mtime_ns: 0,
      title: "二分查找复习",
      task_intent: "learn",
      objective: "理解二分查找复杂度",
      unresolved_gap: "边界条件",
      confirmed_points: ["区间每轮减半"],
      next_action: "完成一次边界迁移练习",
      has_completed_turns: true,
      summary: {
        thread_id: "session-learning",
        status: "needs_update",
        can_summarize: true,
      },
    };
    const { container } = renderCard({ session, onContinueHere });
    const text = container.textContent ?? "";

    expect(text).toContain("理解二分查找复杂度");
    expect(text).toContain("区间每轮减半");
    expect(text).toContain("边界条件");
    expect(text).toContain("完成一次边界迁移练习");
    expect(text).toContain("有新增内容");

    const continueButton = screen
      .getAllByRole("button")
      .find((button) => (button.textContent ?? "").includes("继续这里"));
    fireEvent.click(continueButton as HTMLButtonElement);
    expect(onContinueHere).toHaveBeenCalledWith(
      "继续当前任务，下一步是：完成一次边界迁移练习",
    );
  });

  it("shows disclosed sources instead of mastery points for research", () => {
    const session: SemanticSessionRow = {
      session_id: "session-research",
      kind: "current",
      name: "session-research.md",
      path: "",
      size_bytes: 0,
      mtime_ns: 0,
      title: "Python 研究",
      task_intent: "research",
      research_summary: "核对 Python 发布时间",
      disclosed_sources: [
        { source_id: "s1", type: "web", citation: "Python 官方发布说明" },
      ],
      has_completed_turns: true,
    };
    const { container } = renderCard({ session });
    const text = container.textContent ?? "";

    expect(text).toContain("已披露来源");
    expect(text).toContain("Python 官方发布说明");
    expect(text).not.toContain("已确认点");
  });

  it("prioritizes interrupted recovery actions over normal session restore", () => {
    const onContinueInterrupted = vi.fn<() => void>();
    const onRetryInterrupted = vi.fn<() => void>();
    const onAbandonInterrupted = vi.fn<() => void>();
    const { container } = renderCard({
      session: {
        session_id: "session-1",
        kind: "current",
        name: "session-1.md",
        path: "",
        size_bytes: 0,
        mtime_ns: 0,
        title: "已有会话",
        has_completed_turns: true,
      },
      streamRecovery: {
        question: "问题",
        reply: "部分回答",
        reason: "网络中断",
        sessionId: "session-1",
        turnId: "turn-1",
      },
      onContinueInterrupted,
      onRetryInterrupted,
      onAbandonInterrupted,
    });
    const buttons = screen.getAllByRole("button");

    fireEvent.click(buttons.find((button) => (button.textContent ?? "").includes("从断点继续")) as HTMLButtonElement);
    fireEvent.click(buttons.find((button) => (button.textContent ?? "").includes("重新生成")) as HTMLButtonElement);
    fireEvent.click(buttons.find((button) => (button.textContent ?? "").includes("放弃恢复")) as HTMLButtonElement);

    expect(onContinueInterrupted).toHaveBeenCalledTimes(1);
    expect(onRetryInterrupted).toHaveBeenCalledTimes(1);
    expect(onAbandonInterrupted).toHaveBeenCalledTimes(1);
    expect(container.textContent ?? "").not.toContain("已有会话");
  });
});
