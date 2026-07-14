import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { describe, expect, it, vi } from "vitest";

import type { ChatResponse } from "../../types";
import { ChatPanel } from "./ChatPanel";

type RenderOptions = {
  hasSearchQuery?: boolean;
  onOpenDrawer?: ReturnType<typeof vi.fn>;
  onSearchSources?: ReturnType<typeof vi.fn>;
};

function renderPanel(options: RenderOptions = {}): ReactTestRenderer {
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
        onSearchSources={options.onSearchSources ?? vi.fn()}
        isSearching={false}
        hasSearchQuery={options.hasSearchQuery ?? false}
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
        onOpenDrawer={options.onOpenDrawer ?? vi.fn()}
        onEndSession={vi.fn()}
      />
    );
  });
  return renderer;
}

function directText(node: { children: Array<string | object> }): string {
  return node.children.filter((child): child is string => typeof child === "string").join("");
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

  it("opens a selected low-frequency workspace and closes the menu", () => {
    const onOpenDrawer = vi.fn();
    const removeAttribute = vi.fn();
    const renderer = renderPanel({ onOpenDrawer });
    const groupAction = renderer.root.findAllByProps({ role: "menuitem" })[0];

    act(() => {
      groupAction.props.onClick({
        currentTarget: {
          closest: () => ({ removeAttribute }),
        },
      });
    });

    expect(onOpenDrawer).toHaveBeenCalledWith("group");
    expect(removeAttribute).toHaveBeenCalledWith("open");

    act(() => renderer.unmount());
  });

  it("keeps direct source search available in the primary workspace", () => {
    const onSearchSources = vi.fn();
    const renderer = renderPanel({ hasSearchQuery: true, onSearchSources });
    const searchButton = renderer.root.findByProps({
      "aria-label": "检索当前问题的资料来源",
    });

    act(() => searchButton.props.onClick());
    expect(onSearchSources).toHaveBeenCalledTimes(1);

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
