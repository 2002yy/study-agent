// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ChatResponse } from "../../types";
import { ChatPanel } from "./ChatPanel";

if (!Element.prototype.scrollIntoView) Element.prototype.scrollIntoView = () => {};
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const rag = { status: "waiting", query: "", retrieval_mode: "", reason: "", context: "", sources: "", result_count: 0, results: [], debug: {}, attempts: [], rewritten_query: "" };

function view(copyInterrupted: () => Promise<void> | void = vi.fn(), recovery: { question: string; reply: string; reason: string; turnId: string } | null = null) {
  return render(<ChatPanel
    messages={[{ role: "assistant", content: "回答正文", avatarRole: "auto" }]}
    sessionId="session-1" sessionNavigation={null} input="" setInput={vi.fn()}
    isSending={false} onSubmit={vi.fn()} onStop={vi.fn()} streamRecovery={recovery}
    onContinueInterruptedReply={vi.fn()} onRetry={vi.fn()} onAbandonInterruptedReply={vi.fn()}
    onCopyInterruptedReply={copyInterrupted} onUploadClick={vi.fn()} onQuickPrompt={vi.fn()} onStartNewTopic={vi.fn()}
    lastChat={{ reply: "回答正文", session_id: "session-1", route: {}, rag } as ChatResponse}
    ragEnabled memoryStatus={null} onOpenDrawer={vi.fn()} onEndSession={vi.fn()}
    researchRun={null} isResearchBusy={false} canRetryResearch={false} canResumeResearch={false}
    useResearchInChat={false} onRetryResearch={vi.fn()} onResumeResearch={vi.fn()}
  />);
}

describe("ChatPanel copy feedback", () => {
  it("reports answer-copy denial", async () => {
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: vi.fn().mockRejectedValue(new Error("denied")) } });
    view();
    const button = screen.getByRole("button", { name: "复制回答正文" });
    fireEvent.click(button);
    await waitFor(() => expect(button).toHaveTextContent("复制失败"));
    expect(screen.getByRole("status")).toHaveTextContent("复制失败");
  });

  it("reports interrupted-copy denial", async () => {
    view(vi.fn().mockRejectedValue(new Error("denied")), { question: "原问题", reply: "部分回答", reason: "网络中断", turnId: "turn-1" });
    const button = screen.getByRole("button", { name: "复制已有内容" });
    fireEvent.click(button);
    await waitFor(() => expect(button).toHaveTextContent("复制失败"));
    expect(screen.getByRole("status")).toHaveTextContent("复制失败");
  });
});
