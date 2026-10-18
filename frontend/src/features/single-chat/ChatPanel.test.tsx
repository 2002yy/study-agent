// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
// jsdom does not implement Element.scrollIntoView; ChatPanel calls it on a ref.
if (typeof Element !== "undefined" && !Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = function scrollIntoView() {};
}
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ChatResponse, ChatMessage, ChatResearchProgress, ChatResearchReply } from "../../types";
import {
  clearPendingTaskIntentOverride,
  consumePendingTaskIntentOverride,
} from "../task/taskContract";
import { WorkspaceActions } from "./WorkspaceActions";
import { ChatPanel, searchMessage } from "./ChatPanel";

afterEach(cleanup);

type RenderOptions = {
  input?: string;
  sessionId?: string;
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
  researchReplies?: ChatResearchReply[];
  answerTurnId?: string | null;
};

function renderPanel(options: RenderOptions = {}) {
  return render(
    panelElement(options),
  );
}

function panelElement(options: RenderOptions = {}) {
  return (
    <ChatPanel
      messages={options.messages ?? []}
      sessionId={options.sessionId ?? "session-secret-raw-id"}
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
      researchReplies={options.researchReplies}
      answerTurnId={options.answerTurnId}
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
    />
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
    fireEvent.change(screen.getByRole("combobox", { name: "追加方式" }), { target: { value: "queue" } });
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

  it("offers a multimodal attachment input in the composer", () => {
    renderPanel({ sessionId: "session-1" });
    expect(screen.getByRole("button", { name: "添加附件" })).toBeInTheDocument();
  });

  it("labels a queued task as saved-pending-send, never as auto-executing", () => {
    const { container } = renderPanel({ messages: [
      { role: "user", content: "回答完再解释得简单一点", researchQueued: { runId: "r", id: "q1", status: "pending" } },
    ] });
    expect(screen.getByText("下一轮任务")).toBeVisible();
    expect(screen.getByText("已保存，待发送")).toBeVisible();
    expect(container.textContent).not.toContain("条待执行");
  });

  it("renders a bound computation result inside the conversation", () => {
    renderPanel({ messages: [{
      role: "assistant", content: "结果如下",
      computation: {
        schema_version: "1", run_id: "r", tool_run_id: "t", status: "succeeded", input_revision: 1,
        source_refs: ["s1"], engine: "deterministic", result: { columns: ["方案", "耗时"], rows: [["A", 1]], unit: "s" },
      },
    }] });
    expect(screen.getByRole("figure", { name: "计算结果" })).toBeVisible();
  });

  it("shows what a supplement actually changed instead of leaving it blank", () => {
    renderPanel({ isSending: true, messages: [
      { role: "assistant", content: "partial answer" },
      { role: "user", content: "再考虑 Agent 自动编辑", transient: true, researchSteering: {
        runId: "r", id: "s", status: "executing",
        effects: {
          questions: [{ text: "再考虑 Agent 自动编辑", created: true }],
          sources: [{ title: "自动化接口文档", url: "https://example.org/automation" }],
        },
      } },
    ] });
    expect(screen.getByText("正在按补充要求执行研究")).toBeVisible();
    expect(screen.getByText("新增核查：再考虑 Agent 自动编辑")).toBeVisible();
    expect(screen.getByText("关联已读材料（尚非结论）：")).toBeVisible();
    expect(screen.getByRole("link", { name: "自动化接口文档" })).toHaveAttribute("href", "https://example.org/automation");
  });

  it("never calls a pre-existing check new, and never links an unvalidated url", () => {
    const { container } = renderPanel({ isSending: true, messages: [
      { role: "user", content: "再考虑 Agent 自动编辑", transient: true, researchSteering: {
        runId: "r", id: "s", status: "applied",
        effects: {
          questions: [{ text: "compare；新增研究目标：再考虑 Agent 自动编辑", created: false }],
          sources: [{ title: "可疑来源", url: "javascript:alert(1)" }],
        },
      } },
    ] });
    expect(screen.getByText("本次补充涉及的核查：compare；新增研究目标：再考虑 Agent 自动编辑")).toBeVisible();
    expect(screen.queryByText("新增核查：compare；新增研究目标：再考虑 Agent 自动编辑")).toBeNull();
    // A url that is not a real http(s) address stays readable text, not a link.
    expect(screen.queryByRole("link", { name: "可疑来源" })).toBeNull();
    expect(container.textContent).toContain("可疑来源");
  });

  it("keeps a supplement that changed nothing to one receipt line", () => {
    const { container } = renderPanel({ isSending: true, messages: [
      { role: "user", content: "再考虑 Agent 自动编辑", transient: true,
        researchSteering: { runId: "r", id: "s", status: "pending" } },
    ] });
    expect(screen.getByText("已纳入研究计划 · 等待相关搜索")).toBeVisible();
    expect(container.querySelectorAll(".research-steering-effect")).toHaveLength(0);
  });

  it("renders a supplement reply as its own provisional block, never as the answer", () => {
    const { container } = renderPanel({
      isSending: true,
      messages: [
        { role: "assistant", content: "partial answer" },
        { role: "user", content: "再考虑 Agent 自动编辑", transient: true,
          researchSteering: { runId: "run1", id: "s1", status: "executing" } },
      ],
      researchReplies: [{
        schema: "steering-reply-v1", reply_id: "run1:steer:s1", scope: "steering",
        steering_id: "s1", turn_id: "t1", lifecycle: "open", stage: "analysis",
        content_version: 2, stale: false, analysis_state: "ready",
        focus: "比较标准扩展到脚本控制", reason: "需要重新核对接口",
        questions: ["支持哪些批量操作"],
        text: "评估重点变化：比较标准扩展到脚本控制\\n需要重新核查的原因：需要重新核对接口",
        citations: [], updated_at: "2026-10-18T00:00:00+00:00",
      }],
    });
    expect(screen.getByRole("region", { name: "阶段性回复" })).toBeVisible();
    expect(screen.getByText("初步分析")).toBeVisible();
    expect(container.textContent).toContain("比较标准扩展到脚本控制");
    // The turn answer is untouched by a provisional reply.
    expect(container.querySelector(".message-bubble")?.textContent).toContain("partial answer");
    expect(screen.queryByText("有来源，尚非结论")).toBeNull();
  });

  it("marks a sourced provisional judgment and links only validated sources", () => {
    renderPanel({
      isSending: true,
      messages: [{ role: "assistant", content: "partial answer" }],
      researchReplies: [{
        schema: "steering-reply-v1", reply_id: "run1:research", scope: "research",
        steering_id: "", turn_id: "t1", lifecycle: "open", stage: "evidence_update",
        content_version: 3, stale: false, analysis_state: "ready",
        focus: "", reason: "", questions: [],
        text: "根据已读材料，初步看两种方案都能接脚本。",
        citations: [
          { url: "https://example.org/open-tool", title: "开源工具文档", quote: "支持批量导出" },
          { url: "javascript:alert(1)", title: "可疑来源", quote: "未经验证" },
        ],
        updated_at: "2026-10-18T00:00:00+00:00",
      }],
    });
    expect(screen.getByText("阶段性判断")).toBeVisible();
    expect(screen.getByText("有来源，尚非结论")).toBeVisible();
    expect(screen.getByRole("link", { name: "开源工具文档" })).toHaveAttribute("href", "https://example.org/open-tool");
    expect(screen.queryByRole("link", { name: "可疑来源" })).toBeNull();
  });

  it("shows why a judgment no longer covers the current task", () => {
    renderPanel({
      isSending: false,
      messages: [
        { role: "assistant", content: "answer" },
        { role: "user", content: "再考虑 Agent 自动编辑", transient: true,
          researchSteering: { runId: "run1", id: "s1", status: "applied" } },
      ],
      researchReplies: [{
        schema: "steering-reply-v1", reply_id: "run1:steer:s1", scope: "steering",
        steering_id: "s1", turn_id: "t1", lifecycle: "open", stage: "analysis",
        content_version: 4, stale: true, analysis_state: "ready",
        focus: "", reason: "", questions: [], text: "评估重点变化：图层控制",
        citations: [], updated_at: "2026-10-18T00:00:00+00:00",
      }],
    });
    expect(screen.getByText("尚未覆盖后续新增的条件")).toBeVisible();
  });

  it("tells the reader when an accepted requirement is not in the result", () => {
    const { container } = renderPanel({
      isSending: false,
      answerTurnId: "turn1",
      messages: [{ role: "assistant", content: "final answer", turnId: "turn1", turnStatus: "completed" }],
      researchReplies: [{
        schema: "steering-reply-v1", reply_id: "run1:research", scope: "research",
        steering_id: "", turn_id: "turn1", lifecycle: "closed",
        lifecycle_closed_by: "run_terminal", closed_run_status: "partial",
        stage: "acknowledgement", content_version: 2, stale: false,
        analysis_state: "not_generated", result_state: "not_included",
        focus: "", reason: "", questions: [],
        text: "已收到补充：再补充一下导出格式的限制",
        citations: [], updated_at: "2026-10-18T00:00:00+00:00",
      }],
    });
    const block = container.querySelector("[data-reply-id='run1:research']");
    expect(block?.textContent).toContain("未包含此要求");
    expect(block?.textContent).toContain("排队下一轮");
  });

  it("binds a research-level reply to its own turn, not to the last message", () => {
    const { container } = renderPanel({
      isSending: false,
      messages: [
        { role: "assistant", content: "first answer", turnId: "turn1", turnStatus: "completed" },
        { role: "assistant", content: "second answer", turnId: "turn2", turnStatus: "completed" },
      ],
      researchReplies: [{
        schema: "steering-reply-v1", reply_id: "run1:research", scope: "research",
        steering_id: "", turn_id: "turn1", lifecycle: "open", stage: "evidence_update",
        content_version: 3, stale: false, analysis_state: "pending",
        focus: "", reason: "", questions: [],
        text: "根据已读材料，初步看可行。",
        citations: [], updated_at: "2026-10-18T00:00:00+00:00",
      }],
    });
    const block = container.querySelector("[data-reply-id='run1:research']");
    expect(block).not.toBeNull();
    // .message is the turn container; the reply block is itself an <article>.
    const owner = block?.closest(".message")?.textContent ?? "";
    expect(owner).toContain("first answer");
    expect(owner).not.toContain("second answer");
  });

  it("still shows a research-level reply when its turn has no message yet", () => {
    const { container } = renderPanel({
      isSending: true,
      messages: [{ role: "assistant", content: "", turnId: "turn2" }],
      researchReplies: [{
        schema: "steering-reply-v1", reply_id: "run1:research", scope: "research",
        steering_id: "", turn_id: "turn9", lifecycle: "open", stage: "evidence_update",
        content_version: 3, stale: false, analysis_state: "pending",
        focus: "", reason: "", questions: [],
        text: "根据已读材料，初步看可行。",
        citations: [], updated_at: "2026-10-18T00:00:00+00:00",
      }],
    });
    const orphan = container.querySelector("[data-reply-id='run1:research']");
    expect(orphan).not.toBeNull();
    // No message owns this turn, so it must not be attributed to turn2.
    expect(orphan?.closest(".message")).toBeNull();
    expect(screen.getByRole("region", { name: "阶段性回复" })).toBeVisible();
  });

  it("mounts the answer-visibility probe only for the observed turn", () => {
    const { container, rerender } = render(panelElement({
      isSending: true,
      answerTurnId: "turn1",
      messages: [{ role: "assistant", content: "streaming", turnId: "turn1" }],
    }));
    // Still streaming: not an answer yet.
    expect(container.querySelector(".answer-visibility-probe")).toBeNull();
    // A previous turn's completed answer must not report into this window.
    rerender(panelElement({
      isSending: true,
      answerTurnId: "turn2",
      messages: [{ role: "assistant", content: "earlier answer", turnId: "turn1", turnStatus: "completed" }],
    }));
    expect(container.querySelector(".answer-visibility-probe")).toBeNull();
    rerender(panelElement({
      isSending: false,
      answerTurnId: "turn1",
      messages: [{ role: "assistant", content: "final answer", turnId: "turn1", turnStatus: "completed" }],
    }));
    expect(container.querySelector(".answer-visibility-probe")).not.toBeNull();
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
    expect(Array.from(container.querySelectorAll('.composer-research-mode option')).map(option=>option.textContent))
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

// Extracted from PR #229 so Rev 3 keeps its behaviour and tests.
describe("ChatPanel conversation interaction safety", () => {
  it("does not send the message when Enter confirms Chinese IME composition", async () => {
    const onSubmit = vi.fn();
    const { container } = renderPanel({ input: "待输入的中文", onSubmit });
    const textarea = container.querySelector("textarea")!;
    const form = container.querySelector("form.composer")! as HTMLFormElement;
    const requestSubmit = vi.spyOn(form, "requestSubmit")
      .mockImplementation(() => fireEvent.submit(form));

    fireEvent.compositionStart(textarea);
    fireEvent.keyDown(textarea, { key: "Enter", keyCode: 13 });
    expect(requestSubmit).not.toHaveBeenCalled();

    fireEvent.compositionEnd(textarea);
    fireEvent.keyDown(textarea, { key: "Enter", keyCode: 229 });
    fireEvent.keyDown(textarea, { key: "Enter", shiftKey: true });
    expect(requestSubmit).not.toHaveBeenCalled();

    await act(async () => {
      fireEvent.keyDown(textarea, { key: "Enter", keyCode: 13 });
    });
    expect(requestSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit).toHaveBeenCalledWith(expect.anything(), "待输入的中文");
  });

  it("respects manual reading scroll, but resets the lock on session switch", () => {
    const oldMessage: ChatMessage = { role: "assistant", content: "旧会话" };
    const { container, rerender } = renderPanel({
      sessionId: "old", messages: [oldMessage],
    });
    const viewport = container.querySelector(".conversation")! as HTMLElement;
    Object.defineProperty(viewport, "scrollHeight", { configurable: true, value: 900 });
    Object.defineProperty(viewport, "clientHeight", { configurable: true, value: 200 });
    viewport.scrollTop = 50;
    fireEvent.scroll(viewport);
    expect(container.querySelector(".back-to-latest")).not.toBeNull();

    rerender(panelElement({
      sessionId: "old",
      messages: [oldMessage, { role: "user", content: "下一条消息" }],
    }));
    expect(viewport.scrollTop).toBe(50); // streaming/history must not yank the reader

    rerender(panelElement({
      sessionId: "new",
      messages: [{ role: "assistant", content: "新会话内容" }],
    }));
    expect(viewport.scrollTop).toBe(900);
    expect(container.querySelector(".back-to-latest")).toBeNull();
  });

  it("labels live updates when the user scrolls away during generation", () => {
    const { container } = renderPanel({
      isSending: true,
      messages: [{ role: "assistant", content: "正在补全的内容" }],
    });
    const viewport = container.querySelector(".conversation")! as HTMLElement;
    Object.defineProperty(viewport, "scrollHeight", { configurable: true, value: 1000 });
    Object.defineProperty(viewport, "clientHeight", { configurable: true, value: 200 });
    viewport.scrollTop = 10;
    fireEvent.scroll(viewport);
    expect(container.querySelector(".back-to-latest")).toHaveTextContent("正在生成 · 回到最新");
  });
});
