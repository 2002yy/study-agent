import { act, create, type ReactTestInstance } from "react-test-renderer";
import { describe, expect, it, vi } from "vitest";

import { UploadLearningPrompt } from "./UploadLearningPrompt";

function textContent(node: ReactTestInstance): string {
  return node.children
    .map((child) => (typeof child === "string" ? child : textContent(child)))
    .join("");
}

describe("UploadLearningPrompt", () => {
  it("turns a completed upload into two clear learning actions", () => {
    const onStartLearning = vi.fn();
    const onAskDirectly = vi.fn();
    let renderer!: ReturnType<typeof create>;

    act(() => {
      renderer = create(
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
    });

    const serialized = JSON.stringify(renderer.toJSON());
    expect(serialized).toContain("资料已准备好");
    expect(serialized).toContain("开始系统学习");
    expect(serialized).toContain("直接提问");
    expect(serialized).not.toContain("rebuild");
    expect(serialized).not.toContain("topK");
    expect(serialized).not.toContain("vector backend");

    const buttons = renderer.root.findAllByType("button");
    act(() => buttons.find((button) => textContent(button).includes("开始系统学习"))?.props.onClick());
    act(() => buttons.find((button) => textContent(button).includes("直接提问"))?.props.onClick());

    expect(onStartLearning).toHaveBeenCalledTimes(1);
    expect(onAskDirectly).toHaveBeenCalledTimes(1);

    act(() => renderer.unmount());
  });

  it("shows parsing progress before actions become available", () => {
    let renderer!: ReturnType<typeof create>;
    act(() => {
      renderer = create(
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
    });

    const serialized = JSON.stringify(renderer.toJSON());
    expect(serialized).toContain("正在准备学习资料");
    expect(serialized).toContain("正在解析 1 份资料");
    expect(serialized).not.toContain("开始系统学习");
    expect(serialized).not.toContain("直接提问");

    act(() => renderer.unmount());
  });
});
