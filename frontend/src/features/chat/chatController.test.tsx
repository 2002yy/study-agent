// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { act, renderHook } from "@testing-library/react";
import { type Dispatch, type SetStateAction } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { operationRegistry } from "../../app/operationRegistry";
import { WorkspaceProvider } from "../../app/WorkspaceProvider";
import type { ChatSettings, RagSettings, ChatResearchProgress } from "../../types";
import { useChatController } from "./chatController";

const apiMocks = vi.hoisted(() => ({
  archiveSession: vi.fn(),
  cancelChatResearchRuns: vi.fn(),
  cancelChatTurn: vi.fn(),
  getChatTurnStatus: vi.fn(),
  commitTurn: vi.fn(),
  createNewSession: vi.fn(),
  loadSessionDetail: vi.fn(),
  sendChatStream: vi.fn(),
  steerResearchRun: vi.fn(),
  queueResearchFollowup: vi.fn(),
  completeResearchFollowup: vi.fn(),
  loadResearchQueue: vi.fn().mockResolvedValue({ messages: [] }),
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

describe("continuous research conversation", () => {
  let callbacks: NonNullable<Parameters<typeof import("../../api").sendChatStream>[3]>;
  let finish: () => void;
  let signal: AbortSignal | undefined;
  const progress = (overrides: Partial<ChatResearchProgress> = {}): ChatResearchProgress => ({
    run_id: "run-live", status: "running", stage: "searching", provider_status: "",
    stop_reason: "", error: "", query_attempt_count: 1, selected_source_count: 0,
    version: 1, steering_supported: true, ...overrides,
  });
  beforeEach(() => {
    operationRegistry.cancelAll();
    vi.resetAllMocks();
    apiMocks.loadResearchQueue.mockResolvedValue({ messages: [] });
    apiMocks.sendChatStream.mockImplementation((_q, _h, _o, cb, request) => {
      callbacks = cb;
      signal = request.signal;
      cb.onSession("chat-live", { turnId: "turn-live" });
      cb.onResearch(progress());
      return new Promise(resolve => { finish = () => resolve({
        reply: "final answer", session_id: "chat-live", turn_id: "turn-live", route: {}, rag: {},
      }); });
    });
    apiMocks.steerResearchRun.mockImplementation((_run, _question, request) => Promise.resolve({
      id: "run-live", research_context: { claim_engine_steering: [{
        id: "steer-1", request_id: request.requestId, content: "add omega", status: "pending",
      }] },
    }));
  });

  it("submits into the same run, keeps streaming to the assistant, and reflects application", async () => {
    const { result } = controllerHarness(undefined, { activeChatThreadId: "chat-live" });
    let stream: ReturnType<typeof result.current.send>;
    await act(async () => { stream = result.current.send("compare alpha"); });
    expect(result.current.canSteer).toBe(true);
    await act(async () => { await result.current.send("add omega"); });
    expect(apiMocks.steerResearchRun).toHaveBeenCalledWith("run-live", "add omega", { requestId: expect.stringMatching(/^steer_/) });
    expect(apiMocks.sendChatStream).toHaveBeenCalledTimes(1);
    expect(apiMocks.cancelChatTurn).not.toHaveBeenCalled();
    expect(signal?.aborted).toBe(false);
    expect(result.current.messages[result.current.messages.length - 1].researchSteering?.status).toBe("pending");
    await act(async () => {
      callbacks.onToken?.("continued output");
      callbacks.onResearch?.(progress({ version: 2, steering: [{ id: "steer-1", content: "add omega", status: "applied" }] }));
    });
    expect(result.current.messages.find(message => message.role === "assistant" && message.content === "continued output")).toBeTruthy();
    expect(result.current.messages[result.current.messages.length - 1].researchSteering?.status).toBe("applied");
    await act(async () => { finish(); await stream!; });
    expect(result.current.canSteer).toBe(false);
  });

  it("guards duplicate submits and discards receipts after a session transition", async () => {
    const { result } = controllerHarness(undefined, { activeChatThreadId: "chat-live" });
    let stream: ReturnType<typeof result.current.send>;
    await act(async () => { stream = result.current.send("compare alpha"); });
    let receive: (value: unknown) => void = () => {};
    apiMocks.steerResearchRun.mockImplementation(() => new Promise(resolve => { receive = resolve; }));
    let supplement: ReturnType<typeof result.current.send>;
    await act(async () => {
      supplement = result.current.send("add omega");
      await result.current.send("duplicate");
    });
    expect(apiMocks.steerResearchRun).toHaveBeenCalledTimes(1);
    await act(async () => {
      result.current.transitionSession("chat-other", [{ role: "user", content: "other session" }], null);
      receive({ research_context: { deep: { steering: [{ id: "steer-1", content: "add omega" }] } } });
      await supplement!;
    });
    expect(result.current.messages).toEqual([{ role: "user", content: "other session" }]);
    expect(result.current.researchProgress).toBeNull();
    await act(async () => { finish(); await stream!; });
    expect(result.current.messages).toEqual([{ role: "user", content: "other session" }]);
  });

  it("keeps selected attachments and the request identity on a failed supplement retry", async () => {
    const { result } = controllerHarness(undefined, { activeChatThreadId: "chat-live" });
    let stream: ReturnType<typeof result.current.send>;
    await act(async () => { stream = result.current.send("compare alpha"); });
    apiMocks.steerResearchRun.mockRejectedValueOnce(new Error("response lost"));
    let accepted: unknown;
    await act(async () => {
      accepted = await result.current.send("use these files", undefined, { attachmentIds: ["att-b", "att-a"] });
    });
    expect(accepted).toBe(false);
    const firstRequest = apiMocks.steerResearchRun.mock.calls[0][2];
    expect(firstRequest.attachmentIds).toEqual(["att-a", "att-b"]);
    await act(async () => {
      accepted = await result.current.send("use these files", undefined, { attachmentIds: ["att-a", "att-b", "att-a"] });
    });
    expect(accepted).toBe(true);
    expect(apiMocks.steerResearchRun.mock.calls[1][2]).toEqual(firstRequest);
    expect(apiMocks.sendChatStream).toHaveBeenCalledTimes(1);
    expect(signal?.aborted).toBe(false);
    await act(async () => { finish(); await stream!; });
  });

  it("uses a new request identity when the attachment selection changes after failure", async () => {
    const { result } = controllerHarness(undefined, { activeChatThreadId: "chat-live" });
    let stream: ReturnType<typeof result.current.send>;
    await act(async () => { stream = result.current.send("compare alpha"); });
    apiMocks.steerResearchRun.mockRejectedValue(new Error("response lost"));
    await act(async () => {
      await result.current.send("use this file", undefined, { attachmentIds: ["att-a"] });
      await result.current.send("use this file", undefined, { attachmentIds: ["att-b"] });
    });
    const requests = apiMocks.steerResearchRun.mock.calls.map(call => call[2]);
    expect(requests[1].requestId).not.toBe(requests[0].requestId);
    expect(requests[1].attachmentIds).toEqual(["att-b"]);
    await act(async () => { finish(); await stream!; });
  });

  it("never sends a new chat turn when the current executor cannot steer", async () => {
    const { result } = controllerHarness(undefined, { activeChatThreadId: "chat-live" });
    let stream: ReturnType<typeof result.current.send>;
    await act(async () => { stream = result.current.send("compare alpha"); });
    await act(async () => { callbacks.onResearch?.(progress({ version: 2, steering_supported: false })); });
    expect(result.current.canSteer).toBe(false);
    await act(async () => { await result.current.send("add omega"); });
    expect(apiMocks.steerResearchRun).not.toHaveBeenCalled();
    expect(apiMocks.sendChatStream).toHaveBeenCalledTimes(1);
    await act(async () => { finish(); await stream!; });
  });

  it("persists a queued next question without touching the active stream", async () => {
    const { result } = controllerHarness(undefined, { activeChatThreadId: "chat-live" });
    apiMocks.queueResearchFollowup.mockResolvedValue({ id: "run-live" });
    let stream: ReturnType<typeof result.current.send>;
    await act(async () => { stream = result.current.send("compare alpha"); });
    await act(async () => { await result.current.queue("next question"); });
    expect(apiMocks.queueResearchFollowup).toHaveBeenCalledWith("run-live", "next question", expect.stringMatching(/^queue_/));
    expect(apiMocks.steerResearchRun).not.toHaveBeenCalled();
    expect(apiMocks.sendChatStream).toHaveBeenCalledTimes(1);
    expect(signal?.aborted).toBe(false);
    expect(result.current.messages[result.current.messages.length - 1].researchQueued?.status).toBe("pending");
    await act(async () => { finish(); await stream!; });
  });
});

describe("useChatController stop behavior", () => {
  beforeEach(() => {
    operationRegistry.cancelAll();
    vi.clearAllMocks();
    apiMocks.cancelChatResearchRuns.mockResolvedValue([]);
    apiMocks.cancelChatTurn.mockResolvedValue({
      turn_id: "turn-stop",
      outcome: "accepted",
      status: "streaming",
      cancel_requested_at: "2026-08-21T00:00:00+00:00",
    });
    apiMocks.getChatTurnStatus.mockResolvedValue({
      turn_id: "turn-stop",
      status: "interrupted",
      assistant_message: "partial token",
    });
  });

  it("registers a cooperative cancel, polls the durable state, and never commits partials", async () => {
    apiMocks.cancelChatResearchRuns.mockResolvedValue([{ id: "research-stop" }]);
    apiMocks.sendChatStream.mockImplementation(
      async (_question, _history, _options, callbacks, requestOptions) =>
        new Promise((resolve, reject) => {
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
          // The cooperative cancel closes the stream from the server side:
          // the cancelled SSE event arrives, then the request ends normally.
          apiMocks.cancelChatTurn.mockImplementation(async () => {
            callbacks.onCancelled({
              turn_id: "turn-stop",
              operation_id: "op-stop",
              stage: "generation",
              partial: "partial token",
            });
            resolve({
              reply: "partial token",
              session_id: "chat-stop",
              turn_id: "turn-stop",
              route: { role: "nahida" },
              rag: {},
            });
            return {
              turn_id: "turn-stop",
              outcome: "accepted",
              status: "streaming",
              cancel_requested_at: "2026-08-21T00:00:00+00:00",
            };
          });
        }),
    );

    const { result, onResearchRunDiscovered } = controllerHarness(
      { source: "", runId: "", use: false },
      { activeChatThreadId: "chat-stop" },
    );

    let sendPromise: ReturnType<typeof result.current.send> | undefined;
    await act(async () => {
      sendPromise = result.current.send("question");
      await Promise.resolve();
    });
    expect(result.current.isSending).toBe(true);

    await act(async () => {
      result.current.stop();
      await sendPromise;
    });

    // G12 decision 20: the POST carries the client's expected operation id
    // and only confirms registration.
    expect(apiMocks.cancelChatTurn).toHaveBeenCalledWith(
      "turn-stop",
      expect.any(String),
    );
    // eslint-disable-next-line no-console
    console.log(
      "DEBUG cancel impl used:",
      apiMocks.cancelChatTurn.getMockImplementation() ? "custom" : "default",
    );
    // The cancelled SSE event delivered the durable terminal state; the UI
    // must reflect it (cancelled with no output, interrupted with partial).
    await vi.waitFor(() => {
      const lastMessage =
        result.current.messages[result.current.messages.length - 1];
      expect(lastMessage?.turnStatus).toBe("interrupted");
      expect(lastMessage?.content).toContain("partial token");
    });
    // Decision 13: the frontend never commits partials.
    expect(apiMocks.commitTurn).not.toHaveBeenCalled();
    expect(result.current.isSending).toBe(false);
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
