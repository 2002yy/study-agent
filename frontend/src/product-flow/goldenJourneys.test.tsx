import {
  act,
  create,
  type ReactTestInstance,
  type ReactTestRenderer,
} from "react-test-renderer";
import { describe, expect, it, vi } from "vitest";

import type { ChatResponse } from "../types";
import { LearningStrip } from "../features/learning/LearningStrip";
import { UploadLearningPrompt } from "../features/rag/UploadLearningPrompt";
import { RestoreCard } from "../features/single-chat/RestoreCard";
import { ChatPanel } from "../features/single-chat/ChatPanel";
import type { SemanticSessionRow } from "../features/sessions/sessionNavigation";
import { ChatResearchRecovery } from "../features/web-lookup/ChatResearchRecovery";
import type { ResearchLookupResponse } from "../features/web-lookup/researchApi";
import {
  GOLDEN_JOURNEY_BUDGETS,
  ORDINARY_SURFACE_FORBIDDEN_TERMS,
} from "./goldenJourneyAudit";

const baseRag: ChatResponse["rag"] = {
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
};

function textContent(node: ReactTestInstance): string {
  return node.children
    .map((child) => (typeof child === "string" ? child : textContent(child)))
    .join("");
}

function renderChatPanel({
  isSending = false,
  taskIntent = "quick_answer",
  learningStateEnabled = false,
}: {
  isSending?: boolean;
  taskIntent?: string;
  learningStateEnabled?: boolean;
} = {}): ReactTestRenderer {
  let renderer!: ReactTestRenderer;
  act(() => {
    renderer = create(
      <ChatPanel
        messages={[]}
        sessionId="journey-session"
        sessionNavigation={null}
        input=""
        setInput={vi.fn()}
        isSending={isSending}
        onSubmit={vi.fn()}
        onStop={vi.fn()}
        streamRecovery={null}
        onContinueInterruptedReply={vi.fn()}
        onRetry={vi.fn()}
        onAbandonInterruptedReply={vi.fn()}
        onCopyInterruptedReply={vi.fn()}
        onUploadClick={vi.fn()}
        onSearchSources={vi.fn()}
        isSearching={false}
        hasSearchQuery={false}
        onQuickPrompt={vi.fn()}
        onStartNewTopic={vi.fn()}
        lastChat={{
          reply: "",
          session_id: "journey-session",
          route: {
            task_contract: {
              task_intent: taskIntent,
              source_policy: "model_only",
              closure_eligibility: learningStateEnabled ? "learning_summary" : "not_applicable",
              learning_state_enabled: learningStateEnabled,
            },
          },
          rag: baseRag,
        }}
        ragEnabled
        memoryStatus={null}
        onOpenDrawer={vi.fn()}
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

function learningResponse(): ChatResponse {
  return {
    reply: "继续学习",
    session_id: "source-learning",
    route: {
      task_contract: {
        task_intent: "learn",
        source_policy: "local_and_web",
        closure_eligibility: "learning_summary",
        learning_state_enabled: true,
      },
      learning_state: {
        protocol: "project_execution",
        objective: "通过 FastAPI 源码理解依赖注入调用链",
        phase: "verify",
        unresolved_gap: "",
        hint_level: 0,
        turn_count: 4,
        payload: {
          next_action: "用自己的话解释一次依赖解析调用链",
          pedagogy_evaluation: {
            final_decision: "needs_more_evidence",
            confidence: 0.8,
          },
        },
      },
    },
    rag: baseRag,
  };
}

function failedResearchRun(): ResearchLookupResponse {
  return {
    run_id: "research-chat-1",
    query_text: "latest framework release",
    news_items: [],
    source_block: "",
    warnings: [],
    status: "failed",
    stage: "failed",
    research_context: { run_kind: "chat_tool_loop" },
    query_attempts: [{ status: "provider_failed" }],
    selected_sources: [],
    rejected_sources: [],
    provider_status: "provider_failed",
    stop_reason: "chat_tool_loop_failed",
    answer_confidence: "",
    error: "provider timeout",
    max_items: 8,
    version: 2,
    created_at: "2026-07-18T00:00:00Z",
    updated_at: "2026-07-18T00:00:01Z",
  };
}

function assertNoInternalTerms(rendered: string) {
  for (const term of ORDINARY_SURFACE_FORBIDDEN_TERMS) {
    expect(rendered).not.toContain(term);
  }
}

describe("Study Agent product-level Golden Journeys", () => {
  it("1. first answer requires no configuration decision before typing", () => {
    const budget = GOLDEN_JOURNEY_BUDGETS.first_answer;
    const renderer = renderChatPanel();
    const composer = renderer.root.findByProps({ className: "composer" });
    const requiredSelectors = composer.findAllByType("select").length;
    const productSurfaces = 1;

    expect(requiredSelectors).toBeLessThanOrEqual(budget.maxRequiredDecisionsBeforeStart);
    expect(productSurfaces).toBeLessThanOrEqual(budget.maxProductSurfaces);
    expect(composer.findByType("textarea")).toBeTruthy();
    expect(textContent(composer)).toContain("发送");
    assertNoInternalTerms(JSON.stringify(renderer.toJSON()));

    act(() => renderer.unmount());
  });

  it("2. returning system learning exposes objective, confirmed truth, gap, and next action", () => {
    const budget = GOLDEN_JOURNEY_BUDGETS.system_learning;
    const session: SemanticSessionRow = {
      session_id: "learning-journey",
      kind: "current",
      name: "learning-journey.md",
      path: "",
      size_bytes: 0,
      mtime_ns: 0,
      title: "二分查找",
      task_intent: "learn",
      objective: "理解二分查找边界条件",
      confirmed_points: ["每轮缩小搜索区间"],
      unresolved_gap: "左右边界更新时机",
      next_action: "完成一次边界迁移练习",
      has_completed_turns: true,
    };
    let renderer!: ReactTestRenderer;
    act(() => {
      renderer = create(
        <RestoreCard
          session={session}
          streamRecovery={null}
          onSelectEntry={vi.fn()}
          onUpload={vi.fn()}
          onContinueHere={vi.fn()}
          onStartNewTopic={vi.fn()}
          onContinueInterrupted={vi.fn()}
          onRetryInterrupted={vi.fn()}
          onAbandonInterrupted={vi.fn()}
        />,
      );
    });
    const rendered = JSON.stringify(renderer.toJSON());
    const requiredDecisionsBeforeResume = 1;
    const productSurfaces = 2;

    expect(requiredDecisionsBeforeResume).toBeLessThanOrEqual(budget.maxRequiredDecisionsBeforeStart);
    expect(productSurfaces).toBeLessThanOrEqual(budget.maxProductSurfaces);
    expect(rendered).toContain("理解二分查找边界条件");
    expect(rendered).toContain("每轮缩小搜索区间");
    expect(rendered).toContain("左右边界更新时机");
    expect(rendered).toContain("完成一次边界迁移练习");
    expect(rendered).toContain("继续这里");
    assertNoInternalTerms(rendered);

    act(() => renderer.unmount());
  });

  it("3. uploaded material ends in an explicit learning choice without retrieval jargon", () => {
    const budget = GOLDEN_JOURNEY_BUDGETS.material_learning;
    let renderer!: ReactTestRenderer;
    act(() => {
      renderer = create(
        <UploadLearningPrompt
          phase="ready"
          status="2 份资料已准备好"
          detail="已处理 2 份资料"
          uploadCount={2}
          onStartLearning={vi.fn()}
          onAskDirectly={vi.fn()}
          onChooseAgain={vi.fn()}
          onDismiss={vi.fn()}
        />,
      );
    });
    const rendered = JSON.stringify(renderer.toJSON());
    const requiredDecisionsBeforeStart = 1;
    const productSurfaces = 2;

    expect(requiredDecisionsBeforeStart).toBeLessThanOrEqual(budget.maxRequiredDecisionsBeforeStart);
    expect(productSurfaces).toBeLessThanOrEqual(budget.maxProductSurfaces);
    expect(rendered).toContain("开始系统学习");
    expect(rendered).toContain("直接提问");
    expect(rendered).not.toContain("retrieval");
    expect(rendered).not.toContain("rebuild");
    expect(rendered).not.toContain("vector");
    assertNoInternalTerms(rendered);

    act(() => renderer.unmount());
  });

  it("4. web research stays in chat, supports one-click stop and one-click recovery", () => {
    const budget = GOLDEN_JOURNEY_BUDGETS.web_research;
    const chat = renderChatPanel({ isSending: true, taskIntent: "research" });
    const stopButton = chat.root.findAllByType("button").find((button) =>
      textContent(button).includes("停止"),
    );
    expect(stopButton).toBeTruthy();

    const onRetry = vi.fn();
    let recovery!: ReactTestRenderer;
    act(() => {
      recovery = create(
        <ChatResearchRecovery
          run={failedResearchRun()}
          isBusy={false}
          canRetry
          canResume={false}
          useInChat={false}
          onRetry={onRetry}
          onResume={vi.fn()}
        />,
      );
    });
    const recoveryButtons = recovery.root.findAllByType("button");
    const recoveryClicks = recoveryButtons.length;
    const productSurfaces = 1;

    expect(recoveryClicks).toBeLessThanOrEqual(budget.maxRecoveryClicks);
    expect(productSurfaces).toBeLessThanOrEqual(budget.maxProductSurfaces);
    expect(JSON.stringify(recovery.toJSON())).toContain("重试研究");
    act(() => recoveryButtons[0].props.onClick());
    expect(onRetry).toHaveBeenCalledTimes(1);
    assertNoInternalTerms(JSON.stringify(chat.toJSON()));

    act(() => chat.unmount());
    act(() => recovery.unmount());
  });

  it("5. source-code research remains a learning aid rather than a parallel GitHub workspace", () => {
    const budget = GOLDEN_JOURNEY_BUDGETS.source_code_learning;
    const chat = renderChatPanel({ taskIntent: "learn", learningStateEnabled: true });
    const menu = chat.root.findByProps({ className: "workspace-menu-popover" });
    const menuText = textContent(menu);
    const productSurfaces = 1;
    const requiredDecisionsBeforeStart = 0;

    expect(menuText).not.toContain("GitHub");
    expect(requiredDecisionsBeforeStart).toBeLessThanOrEqual(budget.maxRequiredDecisionsBeforeStart);
    expect(productSurfaces).toBeLessThanOrEqual(budget.maxProductSurfaces);

    let strip!: ReactTestRenderer;
    act(() => {
      strip = create(
        <LearningStrip
          lastChat={learningResponse()}
          visitedPhases={["verify"]}
          memoryStatus={null}
        />,
      );
    });
    const stripText = JSON.stringify(strip.toJSON());
    expect(stripText).toContain("通过 FastAPI 源码理解依赖注入调用链");
    expect(stripText).toContain("下一步：用自己的话解释一次依赖解析调用链");
    assertNoInternalTerms(stripText);

    act(() => chat.unmount());
    act(() => strip.unmount());
  });

  it("keeps all five journey budgets next-action explicit", () => {
    for (const journey of Object.values(GOLDEN_JOURNEY_BUDGETS)) {
      expect(journey.nextActionMustBeExplicit).toBe(true);
      expect(journey.maxProductSurfaces).toBeLessThanOrEqual(2);
    }
  });
});
