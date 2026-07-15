import {
  act,
  create,
  type ReactTestInstance,
  type ReactTestRenderer,
} from "react-test-renderer";
import { describe, expect, it, vi } from "vitest";

import type { ChatResponse } from "../../types";
import {
  consumePendingTaskIntentOverride,
  clearPendingTaskIntentOverride,
} from "../task/taskContract";
import { ChatPanel } from "./ChatPanel";

type RenderOptions = {
  input?: string;
  hasSearchQuery?: boolean;
  taskIntent?: string;
  closureEligibility?: string;
  onOpenDrawer?: ReturnType<typeof vi.fn>;
  onSearchSources?: ReturnType<typeof vi.fn>;
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
        onSearchSources={options.onSearchSources ?? vi.fn()}
        isSearching={false}
        hasSearchQuery={options.hasSearchQuery ?? false}
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
      />
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

describe("ChatPanel practical workspace navigation", () => {
  it("shows user-facing task state without leaking the raw session id", () => {
    const renderer = renderPanel();
    const statusTexts = renderer.root.findAllByType("span").map(directText);
    const serialized = JSON.stringify(renderer.toJSON());

    expect(statusTexts).toContain("任务 临时研究 · 手动");
    expect(statusTexts).toContain("会话 进行中");
    expect(serialized).not.toContain("session-secret-raw-id");

    act(() => renderer.unmount());
  });

  it("keeps the primary dock focused on task closure, upload, sessions, and More", () => {
    const renderer = renderPanel({
      taskIntent: "learn",
      closureEligibility: "learning_summary",
    });
    const actions = renderer.root.findByProps({ className: "topbar-actions" });
    const directButtonLabels = actions.children
      .filter(
        (child): child is ReactTestInstance =>
          typeof child !== "string" && child.type === "button"
      )
      .map((button) => button.props["aria-label"]);

    expect(directButtonLabels).toEqual([
      "整理学习",
      "上传学习资料",
      "打开会话历史",
    ]);
    expect(actions.findByType("summary").props["aria-label"]).toBe("打开更多学习工具");
    expect(directButtonLabels).not.toContain("检索当前问题的资料来源");
    expect(directButtonLabels).not.toContain("打开引用来源与知识库");
    expect(directButtonLabels).not.toContain("打开设置");

    act(() => renderer.unmount());
  });

  it("keeps secondary and low-frequency workspaces in a labelled menu", () => {
    const renderer = renderPanel();
    const serialized = JSON.stringify(renderer.toJSON());

    expect(serialized).toContain("检索当前问题");
    expect(serialized).toContain("引用来源");
    expect(serialized).toContain("设置");
    expect(serialized).toContain("群聊讨论");
    expect(serialized).toContain("新闻研究");
    expect(serialized).toContain("受控工具");
    expect(serialized).toContain("学习记忆");
    expect(serialized).toContain("工作流记录");

    act(() => renderer.unmount());
  });

  it("opens a selected low-frequency workspace and closes the menu", () => {
    const onOpenDrawer = vi.fn();
    const removeAttribute = vi.fn();
    const focus = vi.fn();
    const renderer = renderPanel({ onOpenDrawer });
    const groupAction = renderer.root.findAllByProps({ role: "menuitem" }).find(
      (button) => textContent(button).includes("群聊讨论")
    );

    expect(groupAction).toBeTruthy();
    act(() => {
      groupAction?.props.onClick({
        currentTarget: {
          closest: () => ({
            removeAttribute,
            querySelector: () => ({ focus }),
          }),
        },
      });
    });

    expect(onOpenDrawer).toHaveBeenCalledWith("group");
    expect(removeAttribute).toHaveBeenCalledWith("open");
    expect(focus).toHaveBeenCalledTimes(1);

    act(() => renderer.unmount());
  });

  it("keeps source search reachable from More and closes the menu after use", () => {
    const onSearchSources = vi.fn();
    const removeAttribute = vi.fn();
    const focus = vi.fn();
    const renderer = renderPanel({ hasSearchQuery: true, onSearchSources });
    const searchButton = renderer.root.findByProps({
      "aria-label": "检索当前问题的资料来源",
    });

    act(() => searchButton.props.onClick({
      currentTarget: {
        closest: () => ({
          removeAttribute,
          querySelector: () => ({ focus }),
        }),
      },
    }));
    expect(onSearchSources).toHaveBeenCalledTimes(1);
    expect(removeAttribute).toHaveBeenCalledWith("open");
    expect(focus).toHaveBeenCalledTimes(1);

    act(() => renderer.unmount());
  });

  it("applies a manual task choice to one new message and then resets", async () => {
    let observedIntent: string | undefined;
    const onSubmit = vi.fn(async () => {
      observedIntent = consumePendingTaskIntentOverride();
    });
    const renderer = renderPanel({ input: "请帮我查资料", onSubmit });
    const selector = renderer.root.findByProps({
      "aria-label": "下一条消息的任务类型",
    });

    act(() => selector.props.onChange({ target: { value: "research" } }));
    expect(renderer.root.findByProps({
      "aria-label": "下一条消息的任务类型",
    }).props.value).toBe("research");

    const form = renderer.root.findByProps({ className: "composer" });
    await act(async () => {
      await form.props.onSubmit({ preventDefault: vi.fn() });
    });

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(observedIntent).toBe("research");
    expect(renderer.root.findByProps({
      "aria-label": "下一条消息的任务类型",
    }).props.value).toBe("");
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
    const selector = renderer.root.findByProps({
      "aria-label": "下一条消息的任务类型",
    });
    act(() => selector.props.onChange({ target: { value: "quick_answer" } }));
    const retryButton = renderer.root.findAllByType("button").find(
      (button) => directText(button).includes("重新生成")
    );

    act(() => retryButton?.props.onClick());
    expect(onRetry).toHaveBeenCalledTimes(1);
    expect(consumePendingTaskIntentOverride()).toBeUndefined();
    expect(renderer.root.findByProps({
      "aria-label": "下一条消息的任务类型",
    }).props.value).toBe("quick_answer");

    act(() => renderer.unmount());
  });

  it("gives every remaining icon button an accessible label", () => {
    const renderer = renderPanel();
    const iconButtons = renderer.root.findAll(
      (node) =>
        node.type === "button" &&
        typeof node.props.className === "string" &&
        node.props.className.split(" ").includes("icon-button")
    );

    expect(iconButtons.length).toBeGreaterThan(0);
    for (const button of iconButtons) {
      expect(button.props["aria-label"]).toBeTruthy();
    }

    act(() => renderer.unmount());
  });
});
