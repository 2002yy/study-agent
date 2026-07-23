// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { act, renderHook } from "@testing-library/react";
import { type Dispatch, type SetStateAction } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { operationRegistry } from "../../app/operationRegistry";
import { WorkspaceProvider } from "../../app/WorkspaceProvider";
import type { ChatSettings, RagSettings } from "../../types";
import { useChatController } from "./chatController";

const apiMocks = vi.hoisted(() => ({
  archiveSession: vi.fn(),
  cancelChatResearchRuns: vi.fn(),
  commitTurn: vi.fn(),
  createNewSession: vi.fn(),
  loadSessionDetail: vi.fn(),
  sendChatStream: vi.fn(),
}));

vi.mock("../../api", () => apiMocks);

const chatSettings: ChatSettings = {
  selectedRole: "auto",
  selectedMode: "auto",
  selectedModel: "auto",
  relationshipMode: "default",
  contextMode: "fast",
};
const ragSettings: RagSettings = {
  retrievalMode: "hybrid",
  topK: 5,
  chatTopK: 3,
  minScore: 0,
};

function setter<T>(): Dispatch<SetStateAction<T>> {
  return vi.fn<(value: SetStateAction<T>) => void>();
}

function controllerHarness(
  recoveredResearch: { source: string; runId: string; use: boolean } = {
    source: "",
    runId: "",
    use: false,
  },
  initialState?: Record<string, unknown>,
) {
  const onResearchRunDiscovered = vi.fn();
  const setUseWebLookup = setter<boolean>();
  const { result } = renderHook(
    () =>
      useChatController({
        chatSettings,
        chatSettingsDefaults: chatSettings,
        setChatSettings: setter<ChatSettings>(),
        ragSettings,
        ragSettingsDefaults: ragSettings,
        setRagSettings: setter<RagSettings>(),
        ragEnabled: false,
        setRagEnabled: setter<boolean>(),
        keepCurrentRole: false,
        setKeepCurrentRole: setter<boolean>(),
        conversationInstruction: "",
        setConversationInstruction: setter<string>(),
        webLookupSource: recoveredResearch.source,
        webLookupRunId: recoveredResearch.runId || undefined,
        useWebLookup: recoveredResearch.use,
        setUseWebLookup,
        setInput: setter<string>(),
        setOperationError: setter<string>(),
        clearChatArtifacts: vi.fn(),
        refresh: vi.fn().mockResolvedValue(undefined),
        onResearchRunDiscovered,
      }),
    {
      wrapper: ({ children }) =>
        initialState ? (
          <WorkspaceProvider initialState={initialState}>{children}</WorkspaceProvider>
        ) : (
          <WorkspaceProvider>{children}</WorkspaceProvider>
        ),
    },
  );
  return { result, onResearchRunDiscovered, setUseWebLookup };
}

describe("useChatController stop behavior", () => {
  beforeEach(() => {
    operationRegistry.cancelAll();
    vi.clearAllMocks();
    apiMocks.cancelChatResearchRuns.mockResolvedValue([]);
  });

  it("preserves partial output, commits it, exposes recovery, and clears busy", async () => {
    apiMocks.commitTurn.mockResolvedValue({ committed: true });
    apiMocks.cancelChatResearchRuns.mockResolvedValue([{ id: "research-stop" }]);
    apiMocks.sendChatStream.mockImplementation(
      async (_question, _history, _options, callbacks, requestOptions) =>
        new Promise((_resolve, reject) => {
          callbacks.onSession("chat-stop", {
            turnId: "turn-stop",
            operationId: "op-stop",
          });
          callbacks.onRoute({ role: "nahida", mode: "normal", model_profile: "flash" });
          callbacks.onRag({ web_tools: { run_id: "research-rag" } });
          callbacks.onResearch({
            run_id: "research-stop",
            status: "running",
            stage: "searching",
            provider_status: "",
            stop_reason: "",
            error: "",
            query_attempt_count: 0,
            selected_source_count: 0,
            version: 1,
          });
          callbacks.onToken("partial token");
          requestOptions.signal.addEventListener("abort", () => {
            reject(new DOMException("stopped", "AbortError"));
          });
        }),
    );

    const { result, onResearchRunDiscovered } = controllerHarness(
      { source: "", runId: "", use: false },
      { activeChatThreadId: "chat-stop" },
    );

    let sendPromise: Promise<void> | undefined;
    await act(async () => {
      sendPromise = result.current.send("question");
      await Promise.resolve();
    });
    expect(result.current.isSending).toBe(true);

    await act(async () => {
      result.current.stop();
      await sendPromise;
    });

    expect(result.current.isSending).toBe(false);
    expect(result.current.streamRecovery).toEqual({
      question: "question",
      reply: "partial token",
      reason: "已停止生成",
      sessionId: "chat-stop",
      turnId: "turn-stop",
    });
    const lastMessage = result.current.messages[result.current.messages.length - 1];
    expect(lastMessage).toMatchObject({
      role: "assistant",
      transient: true,
      turnId: "turn-stop",
      turnStatus: "interrupted",
    });
    expect(lastMessage?.content).toContain("partial token");
    expect(apiMocks.commitTurn).toHaveBeenCalledWith(
      "chat-stop",
      expect.objectContaining({
        userInput: "question",
        agentReply: "partial token",
        turnId: "turn-stop",
        operationId: "op-stop",
      }),
    );
    expect(apiMocks.cancelChatResearchRuns).toHaveBeenCalledWith("turn-stop");
    await vi.waitFor(() => {
      expect(onResearchRunDiscovered).toHaveBeenCalledWith("research-rag");
      expect(onResearchRunDiscovered).toHaveBeenCalledWith("research-stop", true);
      expect(result.current.researchProgress).toBeNull();
    });
    expect(operationRegistry.size).toBe(0);
  });

  it("consumes one recovered ResearchRun and keeps its id in turn evidence", async () => {
    const recoveredRag = {
      status: "found",
      query: "recovered",
      retrieval_mode: "hybrid",
      reason: "",
      context: "",
      sources: "",
      result_count: 0,
      results: [],
      debug: {},
      attempts: [],
      rewritten_query: "",
      web_context: {
        used: true,
        run_id: "research-recovered-1",
        source: "research_run",
      },
    };
    apiMocks.sendChatStream.mockImplementation(
      async (_question, _history, _options, callbacks) => {
        callbacks.onSession("chat-recovered", { turnId: "turn-recovered" });
        callbacks.onRoute({ role: "nahida" });
        callbacks.onRag(recoveredRag);
        callbacks.onDone({
          session_id: "chat-recovered",
          turn_id: "turn-recovered",
          reply: "answer from recovered sources",
        });
        return {
          reply: "answer from recovered sources",
          session_id: "chat-recovered",
          turn_id: "turn-recovered",
          route: { role: "nahida" },
          rag: recoveredRag,
        };
      },
    );

    const { result, setUseWebLookup } = controllerHarness(
      { source: "RECOVERED SOURCE BLOCK", runId: "research-recovered-1", use: true },
      { activeChatThreadId: "chat-recovered" },
    );

    await act(async () => {
      await result.current.send("use the recovered evidence");
    });

    expect(apiMocks.sendChatStream.mock.calls[0]?.[2]).toEqual(
      expect.objectContaining({
        webContext: "RECOVERED SOURCE BLOCK",
        webContextRunId: "research-recovered-1",
      }),
    );
    expect(setUseWebLookup).toHaveBeenCalledWith(false);
    const messages = result.current.messages;
    const assistant = messages[messages.length - 1];
    expect(assistant?.evidence?.rag?.web_context?.run_id).toBe("research-recovered-1");
  });

  it("restores committed learning state instead of interrupted attempted state", async () => {
    apiMocks.loadSessionDetail.mockResolvedValue({
      session_id: "chat-restore",
      kind: "active",
      path: "",
      messages: [
        { role: "user", content: "继续", turnId: "turn-interrupted", turnStatus: "interrupted" },
        { role: "assistant", content: "partial", avatarRole: "nahida", turnId: "turn-interrupted", turnStatus: "interrupted" },
      ],
      settings: {},
      route: {
        learning_state: {
          protocol: "socratic_rediscovery",
          objective: "planned objective must not win",
          phase: "complete",
          unresolved_gap: "planned gap",
        },
      },
      rag: {},
      learning_state: {
        protocol: "socratic_rediscovery",
        objective: "committed objective",
        phase: "repair",
        unresolved_gap: "committed gap",
        hint_level: 0,
        turn_count: 2,
        payload: { pedagogy_evaluation: { final_decision: "reject", reasons: ["reasoning_incomplete"] } },
      },
      summary: {},
      navigation: {},
      pedagogy: { mode: "socratic_rediscovery", phase: "repair", move: "minimal_repair" },
      latest_attempted_pedagogy: { phase: "complete" },
      conversation_instruction: "",
      turns: [
        { turn_id: "turn-completed", status: "completed", user_message: "explain", assistant_message: "answer", pedagogy_snapshot: { committed_learning_state: { phase: "repair" } } },
        { turn_id: "turn-interrupted", status: "interrupted", user_message: "继续", assistant_message: "partial", pedagogy_snapshot: { learning_state_after: { phase: "complete" } } },
      ],
      raw: "",
    });

    const { result } = controllerHarness();
    await act(async () => {
      await result.current.restoreSession("chat-restore");
    });

    const restoredLearningState = result.current.lastChat?.route?.learning_state as
      | Record<string, unknown>
      | undefined;
    expect(restoredLearningState?.objective).toBe("committed objective");
    expect(restoredLearningState?.phase).toBe("repair");
    expect(restoredLearningState?.unresolved_gap).toBe("committed gap");
    expect(restoredLearningState?.objective).not.toBe("planned objective must not win");
  });
});
