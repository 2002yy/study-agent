// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
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
  it("shows live progress from the chat preparation stream", () => {
    const { container } = render(
      <ChatResearchRecovery
        run={null}
        progress={{
          run_id: "research-chat-live",
          status: "running",
          stage: "reading",
          provider_status: "",
          stop_reason: "",
          error: "",
          query_attempt_count: 2,
          selected_source_count: 1,
          version: 3,
        }}
        isBusy={false}
        canRetry={false}
        canResume
        useInChat={false}
        onRetry={vi.fn()}
        onResume={vi.fn()}
      />,
    );

    expect(screen.getByRole("status")).toBeTruthy();
    expect(container.querySelector(".spin")).toBeTruthy();
    expect(container.textContent ?? "").toContain("2");
  });

  it("offers a formal retry for a failed chat-owned ResearchRun", () => {
    const onRetry = vi.fn();
    const { container } = render(
      <ChatResearchRecovery
        run={run("failed")}
        isBusy={false}
        canRetry
        canResume={false}
        useInChat={false}
        onRetry={onRetry}
        onResume={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button"));

    expect(container.textContent ?? "").toContain("provider timeout");
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("does not expose standalone research as chat recovery", () => {
    const { container } = render(
      <ChatResearchRecovery
        run={{ ...run("failed"), research_context: { run_kind: "standalone" } }}
        isBusy={false}
        canRetry
        canResume={false}
        useInChat={false}
        onRetry={vi.fn()}
        onResume={vi.fn()}
      />,
    );

    expect(container).toBeEmptyDOMElement();
  });
});
