import { afterEach, describe, expect, it, vi } from "vitest";

import {
  cancelLearningClosure,
  commitLearningClosure,
  createLearningClosure,
  loadLearningClosure,
  retryLearningClosure,
} from "./closureApi";

const closure = {
  id: "closure-1",
  thread_id: "chat-1",
  source_thread_version: 3,
  last_completed_turn_id: "turn-1",
  source_hash: "hash",
  closure_eligibility: "learning_summary",
  status: "preview_ready",
  committed_snapshot: {},
  generated_result: {},
  memory_run_id: "memory-1",
  memory_run: null,
  error: "",
  reason: "",
  active_operation_id: null,
  active_operation_started_at: null,
  cancel_requested_at: null,
  created_at: "2026-07-15T00:00:00Z",
  updated_at: "2026-07-15T00:00:00Z",
  completed_at: null,
  version: 1,
};

describe("learning closure API", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("uses the durable create/get/retry/cancel/commit endpoints", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify(closure), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );
    vi.stubGlobal("fetch", fetchMock);

    await createLearningClosure("chat / 1");
    await loadLearningClosure("closure / 1");
    await retryLearningClosure("closure / 1");
    await cancelLearningClosure("closure / 1");
    await commitLearningClosure("closure / 1");

    expect(fetchMock.mock.calls.map(([url]) => String(url))).toEqual([
      "/sessions/chat%20%2F%201/learning-closure-runs",
      "/learning-closure-runs/closure%20%2F%201",
      "/learning-closure-runs/closure%20%2F%201/retry",
      "/learning-closure-runs/closure%20%2F%201/cancel",
      "/learning-closure-runs/closure%20%2F%201/commit",
    ]);
    expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe("POST");
    expect((fetchMock.mock.calls[1][1] as RequestInit).method).toBeUndefined();
  });

  it("surfaces server eligibility errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response('{"detail":"TaskContract does not allow learning closure"}', {
          status: 409,
          statusText: "Conflict",
        })
      )
    );

    await expect(createLearningClosure("chat-1")).rejects.toThrow(
      "TaskContract does not allow learning closure"
    );
  });
});
