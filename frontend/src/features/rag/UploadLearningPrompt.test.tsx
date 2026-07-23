// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { UploadLearningPrompt } from "./UploadLearningPrompt";

describe("UploadLearningPrompt", () => {
  it("turns a completed upload into two clear learning actions", () => {
    const onStartLearning = vi.fn();
    const onAskDirectly = vi.fn();
    const { container } = render(
      <UploadLearningPrompt
        phase="ready"
        status="2 份资料已准备好"
        detail="已索引 2 个文档、18 个片段"
        uploadCount={2}
        onStartLearning={onStartLearning}
        onAskDirectly={onAskDirectly}
        onChooseAgain={vi.fn()}
        onDismiss={vi.fn()}
      />,
    );

    const text = container.textContent ?? "";
    expect(text).toContain("资料已准备好");
    expect(text).toContain("开始系统学习");
    expect(text).toContain("直接提问");
    expect(text).not.toContain("rebuild");
    expect(text).not.toContain("topK");
    expect(text).not.toContain("vector backend");

    fireEvent.click(screen.getByRole("button", { name: /开始系统学习/ }));
    fireEvent.click(screen.getByRole("button", { name: /直接提问/ }));

    expect(onStartLearning).toHaveBeenCalledTimes(1);
    expect(onAskDirectly).toHaveBeenCalledTimes(1);
  });

  it("shows parsing progress before actions become available", () => {
    const { container } = render(
      <UploadLearningPrompt
        phase="processing"
        status="正在解析 1 份资料…"
        detail=""
        uploadCount={1}
        onStartLearning={vi.fn()}
        onAskDirectly={vi.fn()}
        onChooseAgain={vi.fn()}
        onDismiss={vi.fn()}
      />,
    );

    const text = container.textContent ?? "";
    expect(text).toContain("正在准备学习资料");
    expect(text).toContain("正在解析 1 份资料");
    expect(text).not.toContain("开始系统学习");
    expect(text).not.toContain("直接提问");
  });
});
