import { describe, expect, it } from "vitest";
import { createWorkspaceRuntimeState, workspaceReducer } from "./workspaceReducer";

const summarized = {
  thread_id: "chat-1",
  status: "summarized" as const,
  source_thread_version: 4,
  last_completed_turn_id: "turn-1",
  current_last_completed_turn_id: "turn-1",
  closure_run_id: "closure-1",
  summarized_at: "now",
  can_summarize: false,
};

describe("workspaceReducer", () => {
  it("restores another chat without clearing group/news but clears chat closure scope", () => {
    const state = createWorkspaceRuntimeState({
      activeChatThreadId: "chat-old",
      activeGroupThreadId: "group-1",
      activeNewsRunId: "news-1",
      activeMemoryRunId: "memory-old",
      activeLearningClosureRunId: "closure-old",
      sessionSummary: summarized,
    });

    const next = workspaceReducer(state, { type: "RESTORE_CHAT_SESSION", threadId: "chat-new" });

    expect(next.activeChatThreadId).toBe("chat-new");
    expect(next.activeGroupThreadId).toBe("group-1");
    expect(next.activeNewsRunId).toBe("news-1");
    expect(next.activeMemoryRunId).toBeUndefined();
    expect(next.activeLearningClosureRunId).toBeUndefined();
    expect(next.sessionSummary?.thread_id).toBe("chat-new");
    expect(next.sessionSummary?.status).toBe("not_summarized");
    expect(next.transitionVersion).toBe(state.transitionVersion + 1);
  });

  it("keeps closure and summary scope when restoring the same chat thread", () => {
    const state = createWorkspaceRuntimeState({
      activeChatThreadId: "chat-1",
      activeMemoryRunId: "memory-1",
      activeLearningClosureRunId: "closure-1",
      sessionSummary: summarized,
    });

    const next = workspaceReducer(state, { type: "RESTORE_CHAT_SESSION", threadId: "chat-1" });

    expect(next.activeMemoryRunId).toBe("memory-1");
    expect(next.activeLearningClosureRunId).toBe("closure-1");
    expect(next.sessionSummary).toEqual(summarized);
  });

  it("marks a summarized session as needing update after a new completed turn", () => {
    const next = workspaceReducer(
      createWorkspaceRuntimeState({
        activeChatThreadId: "chat-1",
        sessionSummary: summarized,
      }),
      { type: "MARK_COMPLETED_TURN", turnId: "turn-2" }
    );

    expect(next.sessionSummary?.status).toBe("needs_update");
    expect(next.sessionSummary?.last_completed_turn_id).toBe("turn-1");
    expect(next.sessionSummary?.current_last_completed_turn_id).toBe("turn-2");
    expect(next.sessionSummary?.can_summarize).toBe(true);
  });

  it("does not reopen a summary for the already covered completed turn", () => {
    const next = workspaceReducer(
      createWorkspaceRuntimeState({ sessionSummary: summarized }),
      { type: "MARK_COMPLETED_TURN", turnId: "turn-1" }
    );

    expect(next.sessionSummary?.status).toBe("summarized");
    expect(next.sessionSummary?.can_summarize).toBe(false);
  });

  it("starts a new chat session and clears chat-scoped run state", () => {
    const state = createWorkspaceRuntimeState({
      activeChatThreadId: "chat-old",
      activeGroupThreadId: "group-1",
      activeNewsRunId: "news-1",
      activeToolRunId: "tool-1",
      activeMemoryRunId: "memory-1",
      activeLearningClosureRunId: "closure-1",
      sessionSummary: summarized,
    });

    const next = workspaceReducer(state, { type: "START_NEW_CHAT_SESSION", threadId: "chat-new" });

    expect(next.activeChatThreadId).toBe("chat-new");
    expect(next.activeGroupThreadId).toBe("group-1");
    expect(next.activeNewsRunId).toBeUndefined();
    expect(next.activeToolRunId).toBeUndefined();
    expect(next.activeMemoryRunId).toBeUndefined();
    expect(next.activeLearningClosureRunId).toBeUndefined();
    expect(next.sessionSummary?.thread_id).toBe("chat-new");
    expect(next.sessionSummary?.status).toBe("not_summarized");
  });

  it("tracks a learning closure run independently from its MemoryRun", () => {
    const closure = workspaceReducer(createWorkspaceRuntimeState(), {
      type: "SET_ACTIVE_LEARNING_CLOSURE_RUN",
      runId: "closure-1"
    });
    const memory = workspaceReducer(closure, {
      type: "SET_ACTIVE_MEMORY_RUN",
      runId: "memory-1"
    });

    expect(memory.activeLearningClosureRunId).toBe("closure-1");
    expect(memory.activeMemoryRunId).toBe("memory-1");
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

  it("transitions the complete chat workspace atomically", () => {
    const state = createWorkspaceRuntimeState({
      activeChatThreadId: "chat-old",
      activeMemoryRunId: "memory-old",
      activeLearningClosureRunId: "closure-old",
      sessionSummary: summarized,
      chatMessages: [{ role: "user", content: "old" }],
      streamRecovery: {
        question: "old",
        reply: "partial",
        reason: "interrupted",
        turnId: "turn-old"
      }
    });
    const lastChat = {
      reply: "restored partial",
      session_id: "chat-new",
      turn_id: "turn-new",
      route: {},
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
        rewritten_query: ""
      }
    };
    const restoredSummary = {
      ...summarized,
      thread_id: "chat-new",
      closure_run_id: "closure-new",
    };

    const next = workspaceReducer(state, {
      type: "TRANSITION_CHAT_SESSION",
      threadId: "chat-new",
      messages: [{ role: "assistant", content: "restored partial", avatarRole: "nahida" }],
      lastChat,
      summary: restoredSummary,
      streamRecovery: {
        question: "question",
        reply: "restored partial",
        reason: "上次生成中断",
        turnId: "turn-new"
      }
    });

    expect(next.activeChatThreadId).toBe("chat-new");
    expect(next.chatMessages[0].content).toBe("restored partial");
    expect(next.lastChat?.turn_id).toBe("turn-new");
    expect(next.streamRecovery?.turnId).toBe("turn-new");
    expect(next.activeMemoryRunId).toBeUndefined();
    expect(next.activeLearningClosureRunId).toBeUndefined();
    expect(next.sessionSummary).toEqual(restoredSummary);
    expect(next.transitionVersion).toBe(state.transitionVersion + 1);
  });

  it("opens and closes a slide-over drawer", () => {
    const opened = workspaceReducer(createWorkspaceRuntimeState(), { type: "OPEN_DRAWER", drawer: "settings" });
    expect(opened.activeDrawer).toBe("settings");
    expect(workspaceReducer(opened, { type: "CLOSE_DRAWER" }).activeDrawer).toBeNull();
  });

  it("opening a drawer replaces the previous one", () => {
    const next = workspaceReducer(createWorkspaceRuntimeState({ activeDrawer: "group" }), { type: "OPEN_DRAWER", drawer: "memory" });
    expect(next.activeDrawer).toBe("memory");
  });
});
