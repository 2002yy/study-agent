// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
// jsdom does not implement Element.scrollIntoView; ChatPanel calls it on a ref.
if (typeof Element !== "undefined" && !Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = function scrollIntoView() {};
}
import { act, cleanup, fireEvent, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ChatResponse } from "../../types";
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
      selectedRole={options.selectedRole}
      onSelectRole={options.onSelectRole}
      isSending={options.isSending ?? false}
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
  it("keeps active-turn role settings immutable and hides them in search mode",()=>{
    const select=vi.fn();const {container}=renderPanel({selectedRole:"march7",onSelectRole:select,isSending:true});
    fireEvent.click(container.querySelector('[aria-label="对话设置"]')!);
    for(const button of container.querySelectorAll('.chat-role-settings button'))expect(button).toBeDisabled();
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