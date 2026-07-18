import {
  act,
  create,
  type ReactTestInstance,
  type ReactTestRenderer,
} from "react-test-renderer";
import { describe, expect, it, vi } from "vitest";

import type { ChatResponse } from "../../types";
import {
  clearPendingTaskIntentOverride,
  consumePendingTaskIntentOverride,
} from "../task/taskContract";
import { ChatPanel } from "./ChatPanel";

type RenderOptions = {
  input?: string;
  taskIntent?: string;
  closureEligibility?: string;
  onOpenDrawer?: ReturnType<typeof vi.fn>;
  onSubmit?: ReturnType<typeof vi.fn>;
  onRetry?: ReturnType<typeof vi.fn>;
  onAbandonInterruptedReply?: ReturnType<typeof vi.fn>;
  streamRecovery?: {
    question: string;
    reply: string;
    reason: string;
    sessionId?: string;
    turnId?: string | null;
  } | null;
};

function renderPanel(options: RenderOptions = {}): ReactTestRenderer {
  let renderer!: ReactTestRenderer;
  act(() => {
    renderer = create(
      <ChatPanel
        messages={[]}
        sessionId="session-secret-raw-id"
        sessionNavigation={null}
        input={options.input ?? ""}
        setInput={vi.fn()}
        isSending={false}
        onSubmit={options.onSubmit ?? vi.fn()}
        onStop={vi.fn()}
        streamRecovery={options.streamRecovery ?? null}
        onContinueInterruptedReply={vi.fn()}
        onRetry={options.onRetry ?? vi.fn()}
        onAbandonInterruptedReply={options.onAbandonInterruptedReply ?? vi.fn()}
        onCopyInterruptedReply={vi.fn()}
        onUploadClick={vi.fn()}
        onSearchSources={vi.fn()}
        isSearching={false}
        hasSearchQuery={false}
        onQuickPrompt={vi.fn()}
        onStartNewTopic={vi.fn()}
        lastChat={{
          reply: "",
          session_id: "session-secret-raw-id",
          route: {
            task_contract: {
              task_intent: options.taskIntent ?? "research",
              source_policy: "web_only",
              closure_eligibility: options.closureEligibility ?? "research_summary",
              learning_state_enabled: options.taskIntent === "learn",
              explicit_override: true,
            },
          },
          rag: {
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
          },
        } as ChatResponse}
        ragEnabled
        memoryStatus={null}
        onOpenDrawer={options.onOpenDrawer ?? vi.fn()}
        onEndSession={vi.fn()}
        researchRun={null}
        isResearchBusy={false}
        canRetryResearch={false}
        canResumeResearch={false}
        useResearchInChat={false}
        onRetryResearch={vi.fn()}
        onResumeResearch={vi.fn()}
      />,
    );
  });
  return renderer;
}

function directText(node: { children: Array<string | object> }): string {
  return node.children.filter((child): child is string => typeof child === "string").join("");
}

function textContent(node: ReactTestInstance): string {
  return node.children
    .map((child) => (typeof child === "string" ? child : textContent(child)))
    .join("");
}

function menuClickTarget() {
  const removeAttribute = vi.fn();
  const focus = vi.fn();
  return {
    removeAttribute,
    focus,
    currentTarget: {
      closest: () => ({
        removeAttribute,
        querySelector: () => ({ focus }),
      }),
    },
  };
}

describe("ChatPanel learning product boundary", () => {
  it("shows user-facing task state without leaking the raw session id", () => {
    const renderer = renderPanel();
    const statusTexts = renderer.root.findAllByType("span").map(directText);
    const serialized = JSON.stringify(renderer.toJSON());

    expect(statusTexts).toContain("任务 临时研究 · 手动");
    expect(statusTexts).toContain("会话 进行中");
    expect(serialized).not.toContain("session-secret-raw-id");

    act(() => renderer.unmount());
  });

  it("keeps the primary dock focused on closure, upload, sessions, and More", () => {
    const renderer = renderPanel({
      taskIntent: "learn",
      closureEligibility: "learning_summary",
    });
    const actions = renderer.root.findByProps({ className: "topbar-actions" });
    const directButtonLabels = actions.children
      .filter(
        (child): child is ReactTestInstance =>
          typeof child !== "string" && child.type === "button",
      )
      .map((button) => button.props["aria-label"]);

    expect(directButtonLabels).toEqual([
      "整理学习",
      "上传学习资料",
      "打开会话历史",
    ]);
    expect(actions.findByType("summary").props["aria-label"]).toBe("打开更多学习工具");

    act(() => renderer.unmount());
  });

  it("keeps only learning-facing destinations in the primary More section", () => {
    const renderer = renderPanel();
    const serialized = JSON.stringify(renderer.toJSON());

    expect(serialized).toContain("资料与来源");
    expect(serialized).toContain("学习成果");
    expect(serialized).toContain("设置");
    expect(serialized).toContain("实验功能");
    expect(serialized).toContain("群聊讨论");
    expect(serialized).toContain("新闻研究");
    expect(serialized).toContain("受控工具");
    expect(serialized).toContain("开发者诊断");
    expect(serialized).not.toContain("检索当前问题");
    expect(serialized).not.toContain("工作流记录");
    expect(serialized).not.toContain("学习记忆");

    act(() => renderer.unmount());
  });

  it("opens an experimental workspace and closes the More menu", () => {
    const onOpenDrawer = vi.fn();
    const target = menuClickTarget();
    const renderer = renderPanel({ onOpenDrawer });
    const groupAction = renderer.root.findAllByProps({ role: "menuitem" }).find(
      (button) => textContent(button).includes("群聊讨论"),
    );

    expect(groupAction).toBeTruthy();
    act(() => groupAction?.props.onClick({ currentTarget: target.currentTarget }));

    expect(onOpenDrawer).toHaveBeenCalledWith("group");
    expect(target.removeAttribute).toHaveBeenCalledWith("open");
    expect(target.focus).toHaveBeenCalledTimes(1);

    act(() => renderer.unmount());
  });

  it("replaces the permanent task selector with an optional one-shot task chip", async () => {
    let observedIntent: string | undefined;
    const onSubmit = vi.fn(async () => {
      observedIntent = consumePendingTaskIntentOverride();
    });
    const renderer = renderPanel({ input: "请帮我查资料", onSubmit });

    expect(renderer.root.findAllByProps({
      "aria-label": "下一条消息的任务类型",
    })).toHaveLength(0);

    const chip = renderer.root.findByProps({
      "aria-label": "调整下一条消息的任务方式",
    });
    expect(directText(chip)).toBe("自动 · 临时研究");

    const target = menuClickTarget();
    const researchOption = renderer.root.findAllByProps({ role: "menuitemradio" }).find(
      (button) => textContent(button).includes("临时研究"),
    );
    expect(researchOption).toBeTruthy();

    act(() => researchOption?.props.onClick({ currentTarget: target.currentTarget }));
    expect(directText(renderer.root.findByProps({
      "aria-label": "调整下一条消息的任务方式",
    }))).toBe("本次 · 临时研究");

    const form = renderer.root.findByProps({ className: "composer" });
    await act(async () => {
      await form.props.onSubmit({ preventDefault: vi.fn() });
    });

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(observedIntent).toBe("research");
    expect(directText(renderer.root.findByProps({
      "aria-label": "调整下一条消息的任务方式",
    }))).toBe("自动 · 临时研究");
    expect(consumePendingTaskIntentOverride()).toBeUndefined();

    act(() => renderer.unmount());
  });

  it("does not attach a pending new-turn choice to retry", () => {
    clearPendingTaskIntentOverride();
    const onRetry = vi.fn();
    const renderer = renderPanel({
      onRetry,
      streamRecovery: {
        question: "原问题",
        reply: "部分回答",
        reason: "网络中断",
        turnId: "turn-1",
      },
    });
    const target = menuClickTarget();
    const quickAnswerOption = renderer.root.findAllByProps({ role: "menuitemradio" }).find(
      (button) => textContent(button).includes("快速问答"),
    );

    act(() => quickAnswerOption?.props.onClick({ currentTarget: target.currentTarget }));
    const retryButton = renderer.root.findAllByType("button").find(
      (button) => directText(button).includes("重新生成"),
    );

    act(() => retryButton?.props.onClick());
    expect(onRetry).toHaveBeenCalledTimes(1);
    expect(consumePendingTaskIntentOverride()).toBeUndefined();
    expect(directText(renderer.root.findByProps({
      "aria-label": "调整下一条消息的任务方式",
    }))).toBe("本次 · 快速问答");

    act(() => renderer.unmount());
  });

  it("gives every remaining icon button an accessible label", () => {
    const renderer = renderPanel();
    const iconButtons = renderer.root.findAll(
      (node) =>
        node.type === "button" &&
        typeof node.props.className === "string" &&
        node.props.className.split(" ").includes("icon-button"),
    );

    expect(iconButtons.length).toBeGreaterThan(0);
    for (const button of iconButtons) {
      expect(button.props["aria-label"]).toBeTruthy();
    }

    act(() => renderer.unmount());
  });
});
