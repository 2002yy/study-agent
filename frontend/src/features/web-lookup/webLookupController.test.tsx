// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { operationRegistry } from "../../app/operationRegistry";
import { useWebLookupController } from "./webLookupController";

const apiMocks = vi.hoisted(() => ({
  createResearchRun: vi.fn(),
  executeResearchRun: vi.fn(),
  retryResearchRun: vi.fn(),
  resumeResearchRun: vi.fn(),
  cancelResearchRun: vi.fn(),
  loadResearchRun: vi.fn(),
  loadResearchFollowUpCandidate: vi.fn(),
  steerResearchRun: vi.fn(),
}));

vi.mock("./researchApi", () => apiMocks);

function runPayload(overrides: Record<string, unknown> = {}) {
  return {
    run_id: "web_lookup_1",
    query_text: "Python docs",
    news_items: [{ title: "Python" }],
    source_block: "source",
    warnings: [],
    status: "completed",
    stage: "completed",
    research_context: {},
    query_attempts: [{ status: "found" }],
    selected_sources: [
      {
        item: { title: "Python", url: "https://python.org/doc" },
        assessment: { url: "https://python.org/doc", worth_reading: true },
      },
    ],
    rejected_sources: [],
    provider_status: "found",
    stop_reason: "sources_read",
    answer_confidence: "medium",
    error: "",
    max_items: 8,
    version: 1,
    created_at: "2026-07-13T00:00:00+00:00",
    updated_at: "2026-07-13T00:00:01+00:00",
    completed_at: "2026-07-13T00:00:01+00:00",
    ...overrides,
  };
}

describe("useWebLookupController", () => {
  beforeEach(() => {
    operationRegistry.cancelAll();
    vi.clearAllMocks();
  });

  it("creates a durable run before executing research", async () => {
    apiMocks.createResearchRun.mockResolvedValue(
      runPayload({ status: "pending", stage: "planned", news_items: [], source_block: "" }),
    );
    apiMocks.executeResearchRun.mockResolvedValue(runPayload());
    const errors: string[] = [];
    const setActiveRunId = vi.fn();

    const { result } = renderHook(() =>
      useWebLookupController({
        query: "Python docs",
        setOperationError: (message: string) => errors.push(message),
        activeRunId: undefined,
        setActiveRunId,
      }),
    );

    await act(async () => {
      await result.current.lookup();
    });

    expect(apiMocks.createResearchRun).toHaveBeenCalledWith(
      "Python docs",
      8,
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(apiMocks.executeResearchRun).toHaveBeenCalledWith(
      "web_lookup_1",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(result.current.result?.run_id).toBe("web_lookup_1");
    expect(result.current.useInChat).toBe(true);
    expect(setActiveRunId).toHaveBeenCalledWith("web_lookup_1");
    expect(errors[errors.length - 1]).toBe("");
  });

  it("restores a completed run for inspection without selecting it for chat", async () => {
    apiMocks.loadResearchRun.mockResolvedValue(
      runPayload({ run_id: "web_lookup_saved" }),
    );

    const { result } = renderHook(() =>
      useWebLookupController({
        query: "saved",
        setOperationError: vi.fn(),
        activeRunId: "web_lookup_saved",
        setActiveRunId: vi.fn(),
      }),
    );

    await act(async () => {
      await Promise.resolve();
    });

    expect(result.current.result?.run_id).toBe("web_lookup_saved");
    expect(result.current.result?.status).toBe("completed");
    expect(result.current.useInChat).toBe(false);
  });

  it("refreshes a chat-owned run without attaching its sources to the next question", async () => {
    apiMocks.loadResearchRun.mockResolvedValue(runPayload({
      run_id: "chat-owned", research_context: { run_kind: "chat_tool_loop" },
    }));
    const { result } = renderHook(() => useWebLookupController({
      query: "opus5.5", setOperationError: vi.fn(), activeRunId: undefined,
      setActiveRunId: vi.fn(),
    }));
    await act(async () => { await result.current.refreshRun("chat-owned"); });
    expect(result.current.result?.run_id).toBe("chat-owned");
    expect(result.current.useInChat).toBe(false);
    act(() => result.current.setUseInChat(true));
    expect(result.current.useInChat).toBe(true);
  });

  it("rehydrates and resumes a pending run instead of creating another", async () => {
    apiMocks.loadResearchRun.mockResolvedValue(
      runPayload({ run_id: "web_lookup_saved", query_text: "saved", status: "pending", stage: "planned", news_items: [] }),
    );
    apiMocks.resumeResearchRun.mockResolvedValue(
      runPayload({ run_id: "web_lookup_saved", query_text: "saved" }),
    );

    const { result } = renderHook(() =>
      useWebLookupController({
        query: "saved",
        setOperationError: vi.fn(),
        activeRunId: "web_lookup_saved",
        setActiveRunId: vi.fn(),
      }),
    );

    await act(async () => {
      await Promise.resolve();
    });
    await act(async () => {
      await result.current.lookup();
    });

    expect(apiMocks.loadResearchRun).toHaveBeenCalledWith("web_lookup_saved");
    expect(apiMocks.resumeResearchRun).toHaveBeenCalledWith(
      "web_lookup_saved",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(apiMocks.createResearchRun).not.toHaveBeenCalled();
  });

  it("retries a failed same-query run", async () => {
    apiMocks.loadResearchRun.mockResolvedValue(
      runPayload({
        run_id: "web_lookup_failed",
        status: "failed",
        stage: "failed",
        provider_status: "provider_failed",
        error: "provider unavailable",
        news_items: [],
      }),
    );
    apiMocks.retryResearchRun.mockResolvedValue(runPayload({ run_id: "web_lookup_failed" }));

    const { result } = renderHook(() =>
      useWebLookupController({
        query: "Python docs",
        setOperationError: vi.fn(),
        activeRunId: "web_lookup_failed",
        setActiveRunId: vi.fn(),
      }),
    );

    await act(async () => {
      await Promise.resolve();
    });
    await act(async () => {
      await result.current.lookup();
    });

    expect(apiMocks.retryResearchRun).toHaveBeenCalled();
    expect(apiMocks.createResearchRun).not.toHaveBeenCalled();
  });

  it("does not automatically use partial research in chat", async () => {
    apiMocks.createResearchRun.mockResolvedValue(
      runPayload({ status: "pending", stage: "planned", news_items: [], source_block: "" }),
    );
    apiMocks.executeResearchRun.mockResolvedValue(
      runPayload({ status: "partial", stage: "completed", provider_status: "partial" }),
    );

    const { result } = renderHook(() =>
      useWebLookupController({
        query: "Python docs",
        setOperationError: vi.fn(),
        setActiveRunId: vi.fn(),
      }),
    );

    await act(async () => {
      await result.current.lookup();
    });

    expect(result.current.result?.status).toBe("partial");
    expect(result.current.useInChat).toBe(false);
    expect(result.current.canRetry).toBe(true);
  });

  it("asks before pinning an exact same-thread follow-up parent", async () => {
    apiMocks.loadResearchFollowUpCandidate.mockResolvedValue({
      available: true,
      reason: "deterministic_query_overlap",
      parent_run_id: "web_lookup_parent",
      parent_query: "Python annotations guide",
      parent_status: "completed",
      source_count: 2,
      note_count: 1,
      overlap_tokens: ["python", "annotations"],
      requires_explicit_confirmation: false,
      steering_required: false,
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    apiMocks.createResearchRun.mockResolvedValue(
      runPayload({
        run_id: "web_lookup_child",
        status: "pending",
        stage: "planned",
        news_items: [],
        source_block: "",
        parent_run_id: "web_lookup_parent",
      }),
    );
    apiMocks.executeResearchRun.mockResolvedValue(
      runPayload({ run_id: "web_lookup_child", parent_run_id: "web_lookup_parent" }),
    );

    const { result } = renderHook(() =>
      useWebLookupController({
        query: "Python annotations best practices",
        activeThreadId: "thread-1",
        setOperationError: vi.fn(),
        setActiveRunId: vi.fn(),
      }),
    );
    await act(async () => {
      await result.current.lookup();
    });

    expect(apiMocks.loadResearchFollowUpCandidate).toHaveBeenCalledWith(
      "thread-1",
      "Python annotations best practices",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(apiMocks.createResearchRun).toHaveBeenCalledWith(
      "Python annotations best practices",
      8,
      expect.objectContaining({
        ownerThreadId: "thread-1",
        parentRunId: "web_lookup_parent",
        createRequestId: expect.stringMatching(/^follow-up-/),
        suggestionStatus: "accepted",
      }),
    );
  });

  it("uses steering instead of spawning a child for a related active run", async () => {
    apiMocks.loadResearchFollowUpCandidate.mockResolvedValue({
      available: false,
      reason: "active_parent_requires_steering",
      parent_run_id: "web_lookup_active",
      parent_query: "Python annotations guide",
      parent_status: "running",
      source_count: 1,
      note_count: 0,
      overlap_tokens: ["python"],
      requires_explicit_confirmation: false,
      steering_required: true,
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    apiMocks.steerResearchRun.mockResolvedValue(
      runPayload({
        run_id: "web_lookup_active",
        query_text: "Python annotations guide",
        status: "running",
        stage: "reading",
        news_items: [],
        source_block: "",
      }),
    );

    const { result } = renderHook(() =>
      useWebLookupController({
        query: "Python annotations best practices",
        activeThreadId: "thread-1",
        setOperationError: vi.fn(),
        setActiveRunId: vi.fn(),
      }),
    );
    await act(async () => {
      await result.current.lookup();
    });

    expect(apiMocks.steerResearchRun).toHaveBeenCalledWith(
      "web_lookup_active",
      "Python annotations best practices",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(apiMocks.createResearchRun).not.toHaveBeenCalled();
    expect(apiMocks.executeResearchRun).not.toHaveBeenCalled();
  });

  it("falls back to an independent root when candidate lookup is unavailable", async () => {
    apiMocks.loadResearchFollowUpCandidate.mockRejectedValue(new Error("busy"));
    apiMocks.createResearchRun.mockResolvedValue(
      runPayload({ status: "pending", stage: "planned", news_items: [], source_block: "" }),
    );
    apiMocks.executeResearchRun.mockResolvedValue(runPayload());

    const { result } = renderHook(() =>
      useWebLookupController({
        query: "Python docs",
        activeThreadId: "thread-1",
        setOperationError: vi.fn(),
        setActiveRunId: vi.fn(),
      }),
    );
    await act(async () => {
      await result.current.lookup();
    });

    expect(apiMocks.createResearchRun).toHaveBeenCalledWith(
      "Python docs",
      8,
      expect.objectContaining({
        ownerThreadId: "thread-1",
        parentRunId: undefined,
        suggestionStatus: "unavailable",
      }),
    );
    expect(apiMocks.executeResearchRun).toHaveBeenCalled();
  });

  it("does not use a false-positive found run without durable sources", async () => {
    apiMocks.createResearchRun.mockResolvedValue(
      runPayload({ status: "pending", stage: "planned", news_items: [], source_block: "" }),
    );
    apiMocks.executeResearchRun.mockResolvedValue(
      runPayload({ selected_sources: [], source_block: "" }),
    );

    const { result } = renderHook(() =>
      useWebLookupController({
        query: "Python docs",
        setOperationError: vi.fn(),
        setActiveRunId: vi.fn(),
      }),
    );

    await act(async () => {
      await result.current.lookup();
    });

    expect(result.current.result?.provider_status).toBe("found");
    expect(result.current.useInChat).toBe(false);
  });

  it("sends server cancellation before invalidating the browser request", async () => {
    apiMocks.loadResearchRun.mockResolvedValue(
      runPayload({ status: "running", stage: "reading", active_operation_id: "op_1" }),
    );
    apiMocks.cancelResearchRun.mockResolvedValue(
      runPayload({ status: "cancelled", stage: "cancelled", provider_status: "partial" }),
    );

    const { result } = renderHook(() =>
      useWebLookupController({
        query: "Python docs",
        setOperationError: vi.fn(),
        activeRunId: "web_lookup_1",
        setActiveRunId: vi.fn(),
      }),
    );

    await act(async () => {
      await Promise.resolve();
    });
    await act(async () => {
      result.current.cancel();
      await Promise.resolve();
    });

    expect(apiMocks.cancelResearchRun).toHaveBeenCalledWith("web_lookup_1");
    expect(result.current.result?.status).toBe("cancelled");
    expect(result.current.useInChat).toBe(false);
  });
});
