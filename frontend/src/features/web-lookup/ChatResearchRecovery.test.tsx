import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { describe, expect, it, vi } from "vitest";
import { ChatResearchRecovery } from "./ChatResearchRecovery";
import type { ResearchLookupResponse } from "./researchApi";

function run(status: ResearchLookupResponse["status"]): ResearchLookupResponse {
  return {
    run_id: "research-chat-1",
    query_text: "latest framework release",
    news_items: [],
    source_block: "",
    warnings: [],
    status,
    stage: status === "cancelled" ? "cancelled" : "failed",
    research_context: { run_kind: "chat_tool_loop" },
    query_attempts: [{ status: "provider_failed" }],
    selected_sources: [],
    rejected_sources: [],
    provider_status: "provider_failed",
    stop_reason: status === "cancelled" ? "user_cancelled" : "chat_tool_loop_failed",
    answer_confidence: "",
    error: status === "failed" ? "provider timeout" : "",
    max_items: 8,
    version: 2,
    created_at: "2026-07-15T00:00:00Z",
    updated_at: "2026-07-15T00:00:01Z",
  };
}

describe("ChatResearchRecovery", () => {
  it("offers a formal retry for a failed chat-owned ResearchRun", () => {
    const onRetry = vi.fn();
    let renderer!: ReactTestRenderer;
    act(() => {
      renderer = create(
        <ChatResearchRecovery
          run={run("failed")}
          isBusy={false}
          canRetry
          canResume={false}
          useInChat={false}
          onRetry={onRetry}
          onResume={vi.fn()}
        />
      );
    });

    const button = renderer.root.findByType("button");
    act(() => button.props.onClick());

    expect(JSON.stringify(renderer.toJSON())).toContain("provider timeout");
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("does not expose standalone research as chat recovery", () => {
    let renderer!: ReactTestRenderer;
    act(() => {
      renderer = create(
        <ChatResearchRecovery
          run={{ ...run("failed"), research_context: { run_kind: "standalone" } }}
          isBusy={false}
          canRetry
          canResume={false}
          useInChat={false}
          onRetry={vi.fn()}
          onResume={vi.fn()}
        />
      );
    });

    expect(renderer.toJSON()).toBeNull();
  });
});
