import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { describe, expect, it, vi } from "vitest";

import type { ChatResponse } from "../../types";
import { ChatPanel } from "./ChatPanel";

function renderPanel(): ReactTestRenderer {
  let renderer!: ReactTestRenderer;
  act(() => {
    renderer = create(
      <ChatPanel
        messages={[]}
        sessionId="session-secret-raw-id"
        input=""
        setInput={vi.fn()}
        isSending={false}
        onSubmit={vi.fn()}
        onStop={vi.fn()}
        streamRecovery={null}
        onContinueInterruptedReply={vi.fn()}
        onRetry={vi.fn()}
        onCopyInterruptedReply={vi.fn()}
        onUploadClick={vi.fn()}
        onSearchSources={vi.fn()}
        isSearching={false}
        hasSearchQuery={false}
        onQuickPrompt={vi.fn()}
        lastChat={{
          reply: "",
          session_id: "session-secret-raw-id",
          route: {
            task_contract: {
              task_intent: "research",
              source_policy: "web_only",
              closure_eligibility: "research_summary",
              learning_state_enabled: false,
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
        onOpenDrawer={vi.fn()}
        onEndSession={vi.fn()}
      />
    );
  });
  return renderer;
}

describe("ChatPanel practical workspace navigation", () => {
  it("shows user-facing task state without leaking the raw session id", () => {
    const renderer = renderPanel();
    const serialized = JSON.stringify(renderer.toJSON());

    expect(serialized).toContain("任务 临时研究 · 手动");
    expect(serialized).toContain("会话 进行中");
    expect(serialized).not.toContain("session-secret-raw-id");

    act(() => renderer.unmount());
  });

  it("keeps low-frequency workspaces in a labelled menu", () => {
    const renderer = renderPanel();
    const serialized = JSON.stringify(renderer.toJSON());

    expect(serialized).toContain("群聊讨论");
    expect(serialized).toContain("新闻研究");
    expect(serialized).toContain("受控工具");
    expect(serialized).toContain("学习记忆");
    expect(serialized).toContain("工作流记录");

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
