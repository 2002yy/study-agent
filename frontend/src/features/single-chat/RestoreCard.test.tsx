import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { describe, expect, it, vi } from "vitest";

import type { SemanticSessionRow } from "../sessions/sessionNavigation";
import { RestoreCard } from "./RestoreCard";

function renderCard(options: {
  session?: SemanticSessionRow | null;
  streamRecovery?: {
    question: string;
    reply: string;
    reason: string;
    sessionId?: string;
    turnId?: string | null;
  } | null;
  onSelectEntry?: ReturnType<typeof vi.fn>;
  onContinueHere?: ReturnType<typeof vi.fn>;
  onContinueInterrupted?: ReturnType<typeof vi.fn>;
  onRetryInterrupted?: ReturnType<typeof vi.fn>;
  onAbandonInterrupted?: ReturnType<typeof vi.fn>;
} = {}): ReactTestRenderer {
  let renderer!: ReactTestRenderer;
  act(() => {
    renderer = create(
      <RestoreCard
        session={options.session ?? null}
        streamRecovery={options.streamRecovery ?? null}
        onSelectEntry={options.onSelectEntry ?? vi.fn()}
        onUpload={vi.fn()}
        onContinueHere={options.onContinueHere ?? vi.fn()}
        onStartNewTopic={vi.fn()}
        onContinueInterrupted={options.onContinueInterrupted ?? vi.fn()}
        onRetryInterrupted={options.onRetryInterrupted ?? vi.fn()}
        onAbandonInterrupted={options.onAbandonInterrupted ?? vi.fn()}
      />
    );
  });
  return renderer;
}

describe("RestoreCard", () => {
  it("shows five explicit entry points for a new session", () => {
    const onSelectEntry = vi.fn();
    const renderer = renderCard({ onSelectEntry });
    const serialized = JSON.stringify(renderer.toJSON());

    expect(serialized).toContain("快速问答");
    expect(serialized).toContain("系统学习");
    expect(serialized).toContain("联网研究");
    expect(serialized).toContain("项目推进");
    expect(serialized).toContain("上传资料");

    const learningButton = renderer.root.findAllByType("button").find((button) =>
      JSON.stringify(button.props.children).includes("系统学习")
    );
    act(() => learningButton?.props.onClick());
    expect(onSelectEntry).toHaveBeenCalledWith("learn", "我想系统学习：");
  });

  it("shows committed learning restore facts for returning users", () => {
    const onContinueHere = vi.fn();
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
    const renderer = renderCard({ session, onContinueHere });
    const serialized = JSON.stringify(renderer.toJSON());

    expect(serialized).toContain("理解二分查找复杂度");
    expect(serialized).toContain("区间每轮减半");
    expect(serialized).toContain("边界条件");
    expect(serialized).toContain("完成一次边界迁移练习");
    expect(serialized).toContain("有新增内容");

    const continueButton = renderer.root.findAllByType("button").find((button) =>
      JSON.stringify(button.props.children).includes("继续这里")
    );
    act(() => continueButton?.props.onClick());
    expect(onContinueHere).toHaveBeenCalledWith(
      "继续当前任务，下一步是：完成一次边界迁移练习"
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
    const serialized = JSON.stringify(renderCard({ session }).toJSON());

    expect(serialized).toContain("已披露来源");
    expect(serialized).toContain("Python 官方发布说明");
    expect(serialized).not.toContain("已确认点");
  });

  it("prioritizes interrupted recovery actions over normal session restore", () => {
    const onContinueInterrupted = vi.fn();
    const onRetryInterrupted = vi.fn();
    const onAbandonInterrupted = vi.fn();
    const renderer = renderCard({
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
    const buttons = renderer.root.findAllByType("button");

    act(() => buttons.find((button) => JSON.stringify(button.props.children).includes("从断点继续"))?.props.onClick());
    act(() => buttons.find((button) => JSON.stringify(button.props.children).includes("重新生成"))?.props.onClick());
    act(() => buttons.find((button) => JSON.stringify(button.props.children).includes("放弃恢复"))?.props.onClick());

    expect(onContinueInterrupted).toHaveBeenCalledTimes(1);
    expect(onRetryInterrupted).toHaveBeenCalledTimes(1);
    expect(onAbandonInterrupted).toHaveBeenCalledTimes(1);
    expect(JSON.stringify(renderer.toJSON())).not.toContain("已有会话");
  });
});
