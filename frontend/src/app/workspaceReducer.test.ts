import { describe, expect, it } from "vitest";
import { createWorkspaceRuntimeState, workspaceReducer } from "./workspaceReducer";

describe("workspaceReducer", () => {
  it("restores a chat session without clearing group or news scopes", () => {
    const state = createWorkspaceRuntimeState({
      activeChatThreadId: "chat-old",
      activeGroupThreadId: "group-1",
      activeNewsRunId: "news-1"
    });

    const next = workspaceReducer(state, { type: "RESTORE_CHAT_SESSION", threadId: "chat-new" });

    expect(next.activeChatThreadId).toBe("chat-new");
    expect(next.activeGroupThreadId).toBe("group-1");
    expect(next.activeNewsRunId).toBe("news-1");
    expect(next.transitionVersion).toBe(state.transitionVersion + 1);
  });

  it("starts a new chat session and clears stale news run state", () => {
    const state = createWorkspaceRuntimeState({
      activeChatThreadId: "chat-old",
      activeGroupThreadId: "group-1",
      activeNewsRunId: "news-1"
    });

    const next = workspaceReducer(state, { type: "START_NEW_CHAT_SESSION", threadId: "chat-new" });

    expect(next.activeChatThreadId).toBe("chat-new");
    expect(next.activeGroupThreadId).toBe("group-1");
    expect(next.activeNewsRunId).toBeUndefined();
  });

  it("resets group thread and clears the associated news run", () => {
    const state = createWorkspaceRuntimeState({
      activeChatThreadId: "chat-1",
      activeGroupThreadId: "group-old",
      activeNewsRunId: "news-1"
    });

    const next = workspaceReducer(state, { type: "RESET_GROUP_THREAD", threadId: undefined });

    expect(next.activeChatThreadId).toBe("chat-1");
    expect(next.activeGroupThreadId).toBeUndefined();
    expect(next.activeNewsRunId).toBeUndefined();
  });
});
