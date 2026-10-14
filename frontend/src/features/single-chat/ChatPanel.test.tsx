// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
// jsdom does not implement Element.scrollIntoView; ChatPanel calls it on a ref.
if (typeof Element !== "undefined" && !Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = function scrollIntoView() {};
}
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ChatResponse, ChatMessage, ChatResearchProgress } from "../../types";
import {
  clearPendingTaskIntentOverride,
  consumePendingTaskIntentOverride,
} from "../task/taskContract";
import { WorkspaceActions } from "./WorkspaceActions";
import { ChatPanel, searchMessage } from "./ChatPanel";

afterEach(cleanup);

type RenderOptions = {
  input?: string;
  selectedRole?: string;
  onSelectRole?: ReturnType<typeof vi.fn>;
  isSending?: boolean;
  canSteer?: boolean;
  canQueue?: boolean;
  onQueue?: ReturnType<typeof vi.fn>;
  messages?: ChatMessage[];
  researchProgress?: ChatResearchProgress;
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
      messages={options.messages ?? []}
      sessionId="session-secret-raw-id"
      sessionNavigation={null}
      input={options.input ?? ""}
      setInput={vi.fn()}
      selectedRole={options.selectedRole}
      onSelectRole={options.onSelectRole}
      isSending={options.isSending ?? false}
      canSteer={options.canSteer}
      canQueue={options.canQueue}
      onQueue={options.onQueue}
      researchProgress={options.researchProgress}
      onSubmit={options.onSubmit ?? vi.fn()}
      onStop={vi.fn()}
      streamRecovery={options.streamRecovery ?? null}
      onContinueInterruptedReply={vi.fn()}
      onRetry={options.onRetry ?? vi.fn()}
      onAbandonInterruptedReply={options.onAbandonInterruptedReply ?? vi.fn()}
      onCopyInterruptedReply={vi.fn()}
      onUploadClick={vi.fn()}
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

describe("continuous conversation input", () => {
  it("accepts an in-flight supplement while keeping stop independently available", () => {
    const submit = vi.fn();
    renderPanel({ isSending: true, canSteer: true, input: "add another comparison", onSubmit: submit });
    fireEvent.click(screen.getByRole("button", { name: "追加要求", exact: true }));
    expect(submit).toHaveBeenCalledWith(expect.anything(), "add another comparison");
    expect(screen.getByRole("button", { name: "停止", exact: true })).toBeEnabled();
  });

  it("queues without steering or stopping the current research", () => {
    const submit = vi.fn();
    const queue = vi.fn();
    renderPanel({ isSending: true, canSteer: true, canQueue: true, input: "next question", onSubmit: submit, onQueue: queue });
    fireEvent.click(screen.getByRole("button", { name: "完成后再做", exact: true }));
    fireEvent.click(screen.getByRole("button", { name: "加入下一轮", exact: true }));
    expect(queue).toHaveBeenCalledWith("next question");
    expect(submit).not.toHaveBeenCalled();
  });

  it("keeps the composer editable and blocks IME candidate confirmation", () => {
    const submit = vi.fn();
    renderPanel({ isSending: true, canSteer: true, input: "中文候选", onSubmit: submit });
    const input = screen.getByRole("textbox", { name: "输入学习问题" });
    expect(input).toBeEnabled();
    fireEvent.keyDown(input, { key: "Enter", keyCode: 229 });
    fireEvent.keyDown(input, { key: "Enter", isComposing: true });
    expect(submit).not.toHaveBeenCalled();
  });

  it("keeps streaming progress on the assistant after a user supplement is appended", () => {
    renderPanel({ isSending: true, canSteer: true, messages: [
      { role: "assistant", content: "partial answer" },
      { role: "user", content: "supplement", transient: true, researchSteering: { runId: "r", id: "s", status: "pending" } },
    ] });
    expect(screen.getByText("回答正在补充，可以先阅读")).toBeVisible();
    expect(screen.getByText("已纳入研究计划 · 等待相关搜索")).toBeVisible();
  });

  it("labels a queued task as saved-pending-send, never as auto-executing", () => {
    const { container } = renderPanel({ messages: [
      { role: "user", content: "回答完再解释得简单一点", researchQueued: { runId: "r", id: "q1", status: "pending" } },
    ] });
    expect(screen.getByText("下一轮任务")).toBeVisible();
    expect(screen.getByText("已保存，待发送")).toBeVisible();
    expect(container.textContent).not.toContain("条待执行");
  });

  it("distinguishes a plan-applied supplement from one that is really executing", () => {
    renderPanel({ isSending: true, messages: [
      { role: "user", content: "已进入计划", transient: true, researchSteering: { runId: "r", id: "a", status: "applied" } },
      { role: "user", content: "正在执行", transient: true, researchSteering: { runId: "r", id: "b", status: "executing" } },
      { role: "user", content: "迟到", transient: true, researchSteering: { runId: "r", id: "c", status: "late" } },
    ] });
    expect(screen.getByText("已应用到后续研究")).toBeVisible();
    expect(screen.getByText("正在按补充要求执行研究")).toBeVisible();
    expect(screen.getByText("本轮未应用这条补充，请在下一轮继续")).toBeVisible();
  });
});

describe("ChatPanel learning product boundary", () => {
  it("renders a single contextual level-one heading in normal chat", () => {
    const { container } = renderPanel();
    const headings = Array.from(container.querySelectorAll("h1"));
    expect(headings).toHaveLength(1);
    expect(headings[0]).toHaveTextContent("对话");
  });

  it("shows user-facing task state without leaking the raw session id", () => {
    const { container } = renderPanel();
    const statusTexts = Array.from(container.querySelectorAll("span")).map(
      (el) => el.textContent ?? "",
    );

    expect(statusTexts).toContain("任务 临时研究 · 手动");
    expect(statusTexts).toContain("会话 进行中");
    expect(container.innerHTML).not.toContain("session-secret-raw-id");
  });

  it("keeps only chat and search modes and moves utilities out of the conversation", () => {
    const {container}=renderPanel();
    expect(Array.from(container.querySelectorAll('.composer-modes button')).map(button=>button.textContent)).toEqual(["对话","搜索"]);
    expect(container.querySelector('.workspace-menu')).toBeNull();
    expect(container.querySelector('.turn-intent-chip-menu')).toBeNull();
    expect(container.textContent).not.toContain("系统学习");
    expect(container.textContent).toContain("今天想了解什么？");
  });
  it("keeps existing utility destinations in navigation",()=>{
    const open=vi.fn();
    const {container}=render(<WorkspaceActions onUploadClick={vi.fn()} onOpenDrawer={open} onEndSession={vi.fn()} isSending={false} canClose closureLabel="整理学习"/>);
    expect(container.textContent).toContain("资料与来源");
    expect(container.textContent).toContain("学习成果");
    expect(container.textContent).toContain("设置");
    expect(container.textContent).toContain("实验室");
    const lab=findByRoleAndText(container,"menuitem","实验室") as HTMLElement;
    fireEvent.click(lab);expect(open).toHaveBeenCalledWith("lab");
  });
  it("submits search through the same chat callback with an explicit natural-language request",async()=>{
    const submit=vi.fn();const {container}=renderPanel({input:"  注意力机制  ",onSubmit:submit});
    fireEvent.click(container.querySelectorAll('.composer-modes button')[1]);
    await act(async()=>fireEvent.submit(container.querySelector('.composer')!));
    expect(submit).toHaveBeenCalledWith(expect.anything(),"帮我搜索：注意力机制");
    expect(consumePendingTaskIntentOverride()).toBeUndefined();
    expect(searchMessage("帮我搜索：注意力机制")).toBe("帮我搜索：注意力机制");
  });
  it("passes an identical search request in chat mode without a task override",async()=>{
    const submit=vi.fn();const {container}=renderPanel({input:"帮我搜索：注意力机制",onSubmit:submit});
    await act(async()=>fireEvent.submit(container.querySelector('.composer')!));
    expect(submit).toHaveBeenCalledWith(expect.anything(),"帮我搜索：注意力机制");
    expect(consumePendingTaskIntentOverride()).toBeUndefined();
  });
  it("keeps interrupted-turn retry independent of the input mode",()=>{
    clearPendingTaskIntentOverride();const retry=vi.fn();
    const {container}=renderPanel({onRetry:retry,streamRecovery:{question:"原问题",reply:"部分回答",reason:"网络中断",turnId:"turn-1"}});
    fireEvent.click(container.querySelectorAll('.composer-modes button')[1]);
    fireEvent.click(Array.from(container.querySelectorAll('button')).find(button=>button.textContent?.includes("重新生成"))!);
    expect(retry).toHaveBeenCalledTimes(1);expect(consumePendingTaskIntentOverride()).toBeUndefined();
  });

  it("keeps four role choices inside a collapsed conversation setting",()=>{
    const select=vi.fn();const {container}=renderPanel({selectedRole:"nahida",onSelectRole:select});
    const toggle=container.querySelector('[aria-label="对话设置"]')!;
    expect(toggle).toHaveAttribute("aria-expanded","false");
    expect(container.querySelector('.chat-role-settings')).toBeNull();
    fireEvent.click(toggle);
    const choices=Array.from(container.querySelectorAll('.chat-role-options button'));
    expect(choices.map(button=>button.textContent)).toEqual(["三月七","刻晴","纳西妲","流萤"]);
    expect(choices[2]).toHaveAttribute("aria-pressed","true");
    fireEvent.click(choices[3]);expect(select).toHaveBeenCalledWith("firefly");
    expect(container.querySelector('.chat-role-settings')).toBeNull();
    expect(container.querySelector('textarea')).toHaveFocus();
  });
  it("can return to automatic selection and dismiss settings with Escape",()=>{
    const select=vi.fn();const {container}=renderPanel({selectedRole:"keqing",onSelectRole:select});
    const toggle=container.querySelector('[aria-label="对话设置"]')!;
    fireEvent.click(toggle);
    fireEvent.keyDown(container.querySelector('.chat-role-settings')!,{key:"Escape"});
    expect(toggle).toHaveFocus();expect(toggle).toHaveAttribute("aria-expanded","false");
    fireEvent.click(toggle);
    fireEvent.click(container.querySelector('.chat-role-settings-heading button')!);
    expect(select).toHaveBeenCalledWith("auto");
  });
  it("keeps the active turn immutable: no role switching, only adjust/after semantics",()=>{
    const select=vi.fn();const {container}=renderPanel({selectedRole:"march7",onSelectRole:select,isSending:true,canSteer:true,canQueue:true});
    // The role is fixed while a turn is running.
    expect(container.querySelector('[aria-label="对话设置"]')).toBeNull();
    expect(container.querySelector('.chat-role-settings')).toBeNull();
    // The composer only offers the two continuous-conversation semantics.
    expect(Array.from(container.querySelectorAll('.composer-modes button')).map(button=>button.textContent))
      .toEqual(["调整当前研究","完成后再做"]);
    expect(select).not.toHaveBeenCalled();
  });
  it("hides role settings when switching to search mode",()=>{
    const select=vi.fn();const {container}=renderPanel({selectedRole:"march7",onSelectRole:select});
    fireEvent.click(container.querySelector('[aria-label="对话设置"]')!);
    fireEvent.click(container.querySelectorAll('.composer-modes button')[1]);
    expect(container.querySelector('.chat-role-settings')).toBeNull();
    expect(container.querySelector('[aria-label="对话设置"]')).toBeNull();expect(select).not.toHaveBeenCalled();
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
