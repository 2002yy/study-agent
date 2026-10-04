// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { MemoryRunResponse } from "../../types";
import type { LearningClosureRunResponse } from "./closureTypes";
import {
  buildClosureReviewModel,
  LearningClosureReview,
} from "./LearningClosureReview";

const memoryRun = {
  id: "memory-1",
  status: "previewed",
  updates: [
    { target: "progress", content: "模型生成的学习进展摘要", append: true },
    { target: "revision_notes", content: "模型生成的待补强摘要", append: true },
    { target: "current_focus", content: "下一步解释证据充分性", append: false },
  ],
  preview: {
    writable: true,
    updates: [],
  },
  result: { results: [], errors: [] },
} as unknown as MemoryRunResponse;

const closureRun = {
  id: "closure-1",
  thread_id: "chat-1",
  source_thread_version: 3,
  last_completed_turn_id: "turn-3",
  source_hash: "hash",
  closure_eligibility: "learning_summary",
  status: "preview_ready",
  committed_snapshot: {
    structured_input: {
      committed_learning_state: {
        confirmed_points: ["理解了索引激活边界"],
        unresolved_gap: "还需练习拒答判断",
      },
      committed_project_state: {},
    },
  },
  generated_result: {
    candidates: [
      { target: "progress", content: "模型生成的学习进展摘要" },
      { target: "revision_notes", content: "模型生成的待补强摘要" },
      { target: "current_focus", content: "下一步解释证据充分性" },
    ],
    durable_learning_candidate: null,
  },
  memory_run_id: "memory-1",
  memory_run: memoryRun,
  thread_summary: {
    thread_id: "chat-1",
    status: "not_summarized",
    can_summarize: true,
  },
  error: "",
  reason: "",
  created_at: "",
  updated_at: "",
  version: 1,
} as LearningClosureRunResponse;

const durableCandidate = {
  source_ref: "github_source:turn-3:0",
  claim_text: "恢复 durable learning state 不需要重放完整聊天 turns。",
  claim_kind: "invariant",
  scope: "project",
  next_step: "刷新后检查同一 Goal 是否仍可直接读取。",
  evaluation_id: "eval-1",
  evaluation_turn_id: "turn-3",
};

const durableOnlyRun = {
  ...closureRun,
  id: "closure-durable",
  source_hash: "durable-hash",
  generated_result: {
    candidates: [],
    durable_learning_candidate: durableCandidate,
  },
  memory_run_id: null,
  memory_run: null,
} as LearningClosureRunResponse;

afterEach(cleanup);

describe("LearningClosureReview", () => {
  it("uses committed facts for confirmation and gaps while keeping the frozen next step", () => {
    expect(buildClosureReviewModel(closureRun, memoryRun)).toEqual({
      confirmed: ["理解了索引激活边界"],
      unresolved: ["还需练习拒答判断"],
      next: ["下一步解释证据充分性"],
      pendingDurable: [],
      impactLabels: [
        "已经确认的学习进展",
        "仍需补强的内容",
        "下一次继续学习的重点",
      ],
    });
  });

  it("does not promote model-generated progress or revision summaries into committed truth", () => {
    const review = buildClosureReviewModel(closureRun, memoryRun);
    expect(review.confirmed).not.toContain("模型生成的学习进展摘要");
    expect(review.unresolved).not.toContain("模型生成的待补强摘要");
  });

  it("shows review-first copy and keeps internal targets out of the default layer", () => {
    render(
      <LearningClosureReview
        isCommitting={false}
        memoryRun={memoryRun}
        onConfirm={vi.fn()}
        onContinue={vi.fn()}
        run={closureRun}
      />,
    );

    expect(screen.getByRole("heading", { name: "回顾这次学习" })).toBeTruthy();
    expect(screen.getByText("理解了索引激活边界")).toBeTruthy();
    expect(screen.getByText("还需练习拒答判断")).toBeTruthy();
    expect(screen.getByText("下一步解释证据充分性")).toBeTruthy();
    expect(screen.queryByText("模型生成的学习进展摘要")).toBeNull();
    expect(screen.queryByText("模型生成的待补强摘要")).toBeNull();
    expect(
      (screen.getByRole("button", {
        name: "确认并保存学习成果",
      }) as HTMLButtonElement).disabled,
    ).toBe(false);
    expect(screen.queryByText("current_focus")).toBeNull();
    expect(screen.queryByText("append")).toBeNull();
  });

  it("keeps a durable-only claim pending but explicitly confirmable without a MemoryRun", () => {
    const review = buildClosureReviewModel(durableOnlyRun, null);
    expect(review.pendingDurable).toEqual([
      "恢复 durable learning state 不需要重放完整聊天 turns。",
    ]);
    expect(review.confirmed).not.toContain(
      "恢复 durable learning state 不需要重放完整聊天 turns。",
    );
    expect(review.impactLabels).toContain("可恢复的源码学习命题与证据");

    render(
      <LearningClosureReview
        isCommitting={false}
        memoryRun={null}
        onConfirm={vi.fn()}
        onContinue={vi.fn()}
        run={durableOnlyRun}
      />,
    );

    expect(screen.getByRole("heading", { name: "待确认源码命题" })).toBeTruthy();
    expect(
      screen.getByText("恢复 durable learning state 不需要重放完整聊天 turns。"),
    ).toBeTruthy();
    expect(screen.getByText("可恢复的源码学习命题与证据")).toBeTruthy();
    expect(
      (screen.getByRole("button", {
        name: "确认并保存学习成果",
      }) as HTMLButtonElement).disabled,
    ).toBe(false);
  });

  it("does not let an already-succeeded memory channel block durable confirmation", () => {
    const succeededMemory = {
      ...memoryRun,
      status: "succeeded",
      preview: { ...memoryRun.preview, writable: false },
    } as MemoryRunResponse;
    const combinedRun = {
      ...closureRun,
      id: "closure-combined",
      source_hash: "combined-hash",
      generated_result: {
        ...closureRun.generated_result,
        durable_learning_candidate: durableCandidate,
      },
      memory_run: succeededMemory,
    } as LearningClosureRunResponse;

    render(
      <LearningClosureReview
        isCommitting={false}
        memoryRun={succeededMemory}
        onConfirm={vi.fn()}
        onContinue={vi.fn()}
        run={combinedRun}
      />,
    );

    expect(screen.getByRole("heading", { name: "待确认源码命题" })).toBeTruthy();
    expect(
      (screen.getByRole("button", {
        name: "确认并保存学习成果",
      }) as HTMLButtonElement).disabled,
    ).toBe(false);
  });

  it("does not enable confirmation when neither durable nor memory output exists", () => {
    const emptyRun = {
      ...durableOnlyRun,
      id: "closure-empty",
      generated_result: { candidates: [], durable_learning_candidate: null },
    } as LearningClosureRunResponse;

    render(
      <LearningClosureReview
        isCommitting={false}
        memoryRun={null}
        onConfirm={vi.fn()}
        onContinue={vi.fn()}
        run={emptyRun}
      />,
    );

    expect(
      (screen.getByRole("button", {
        name: "确认并保存学习成果",
      }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });
});
