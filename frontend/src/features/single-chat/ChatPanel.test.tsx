// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
// jsdom does not implement Element.scrollIntoView; ChatPanel calls it on a ref.
if (typeof Element !== "undefined" && !Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = function scrollIntoView() {};
}
import { act, fireEvent, render } from "@testing-library/react";
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

function renderPanel(options: RenderOptions = {}) {
  return render(
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
}

function findByRoleAndText(container: HTMLElement, role: string, text: string) {
  return Array.from(container.querySelectorAll(`[role="${role}"]`)).find((el) =>
    (el.textContent ?? "").includes(text),
  );
}

describe("ChatPanel learning product boundary", () => {
  it("shows user-facing task state without leaking the raw session id", () => {
    const { container } = renderPanel();
    const statusTexts = Array.from(container.querySelectorAll("span")).map(
      (el) => el.textContent ?? "",
    );

    expect(statusTexts).toContain("任务 临时研究 · 手动");
    expect(statusTexts).toContain("会话 进行中");
    expect(container.innerHTML).not.toContain("session-secret-raw-id");
  });

  it("keeps the primary dock focused on closure, upload, sessions, and More", () => {
    const { container } = renderPanel({
      taskIntent: "learn",
      closureEligibility: "learning_summary",
    });
    const actions = container.querySelector(".topbar-actions") as HTMLElement;
    const directButtonLabels = Array.from(actions.querySelectorAll(":scope > button")).map(
      (button) => button.getAttribute("aria-label"),
    );

    expect(directButtonLabels).toEqual(["整理学习", "上传学习资料", "打开会话历史"]);
    expect(actions.querySelector("summary")?.getAttribute("aria-label")).toBe(
      "打开更多学习工具",
    );
  });

  it("keeps only learning-facing destinations in the primary More section", () => {
    const { container } = renderPanel();
    const html = container.innerHTML;

    expect(html).toContain("资料与来源");
    expect(html).toContain("学习成果");
    expect(html).toContain("设置");
    expect(html).toContain("实验功能");
    expect(html).toContain("群聊讨论");
    expect(html).toContain("新闻研究");
    expect(html).toContain("受控工具");
    expect(html).toContain("开发者诊断");
    expect(html).not.toContain("检索当前问题");
    expect(html).not.toContain("工作流记录");
    expect(html).not.toContain("学习记忆");
  });

  it("opens an experimental workspace and closes the More menu", () => {
    const onOpenDrawer = vi.fn();
    const { container } = renderPanel({ onOpenDrawer });
    const details = container.querySelector("details.workspace-menu") as HTMLDetailsElement;
    const removeAttrSpy = vi.spyOn(details, "removeAttribute");
    const summary = details.querySelector("summary") as HTMLElement;
    const focusSpy = vi.spyOn(summary, "focus");
    const groupAction = findByRoleAndText(container, "menuitem", "群聊讨论") as HTMLElement;

    expect(groupAction).toBeTruthy();
    fireEvent.click(groupAction);

    expect(onOpenDrawer).toHaveBeenCalledWith("group");
    expect(removeAttrSpy).toHaveBeenCalledWith("open");
    expect(focusSpy).toHaveBeenCalledTimes(1);
  });

  it("replaces the permanent task selector with an optional one-shot task chip", async () => {
    let observedIntent: string | undefined;
    const onSubmit = vi.fn(async () => {
      observedIntent = consumePendingTaskIntentOverride();
    });
    const { container } = renderPanel({ input: "请帮我查资料", onSubmit });

    expect(container.querySelectorAll('[aria-label="下一条消息的任务类型"]')).toHaveLength(0);

    const chip = container.querySelector('[aria-label="调整下一条消息的任务方式"]');
    expect(chip?.textContent ?? "").toBe("自动 · 临时研究");

    const researchOption = findByRoleAndText(
      container,
      "menuitemradio",
      "临时研究",
    ) as HTMLElement;
    expect(researchOption).toBeTruthy();
    fireEvent.click(researchOption);
    expect(
      container.querySelector('[aria-label="调整下一条消息的任务方式"]')?.textContent ?? "",
    ).toBe("本次 · 临时研究");

    const form = container.querySelector(".composer") as HTMLFormElement;
    await act(async () => {
      fireEvent.submit(form);
    });

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(observedIntent).toBe("research");
    expect(
      container.querySelector('[aria-label="调整下一条消息的任务方式"]')?.textContent ?? "",
    ).toBe("自动 · 临时研究");
    expect(consumePendingTaskIntentOverride()).toBeUndefined();
  });

  it("does not attach a pending new-turn choice to retry", () => {
    clearPendingTaskIntentOverride();
    const onRetry = vi.fn();
    const { container } = renderPanel({
      onRetry,
      streamRecovery: {
        question: "原问题",
        reply: "部分回答",
        reason: "网络中断",
        turnId: "turn-1",
      },
    });

    const quickAnswerOption = findByRoleAndText(
      container,
      "menuitemradio",
      "快速问答",
    ) as HTMLElement;
    fireEvent.click(quickAnswerOption);

    const retryButton = Array.from(container.querySelectorAll("button")).find((button) =>
      (button.textContent ?? "").includes("重新生成"),
    ) as HTMLButtonElement;
    fireEvent.click(retryButton);

    expect(onRetry).toHaveBeenCalledTimes(1);
    expect(consumePendingTaskIntentOverride()).toBeUndefined();
    expect(
      container.querySelector('[aria-label="调整下一条消息的任务方式"]')?.textContent ?? "",
    ).toBe("本次 · 快速问答");
  });

  it("gives every remaining icon button an accessible label", () => {
    const { container } = renderPanel();
    const iconButtons = Array.from(
      container.querySelectorAll("button.icon-button"),
    ) as HTMLButtonElement[];

    expect(iconButtons.length).toBeGreaterThan(0);
    for (const button of iconButtons) {
      expect(button.getAttribute("aria-label")).toBeTruthy();
    }
  });
});
