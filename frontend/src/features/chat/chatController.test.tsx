import React, { type Dispatch, type SetStateAction } from "react";
import { act, create } from "react-test-renderer";
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

function controllerHarness() {
  let controller: ReturnType<typeof useChatController> | undefined;
  function Harness() {
    controller = useChatController({
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
      webLookupSource: "",
      useWebLookup: false,
      setUseWebLookup: setter<boolean>(),
      setInput: setter<string>(),
      setOperationError: setter<string>(),
      clearChatArtifacts: vi.fn(),
      refresh: vi.fn().mockResolvedValue(undefined),
    });
    return null;
  }
  return { Harness, getController: () => controller };
}

describe("useChatController stop behavior", () => {
  beforeEach(() => {
    operationRegistry.cancelAll();
    vi.clearAllMocks();
    apiMocks.cancelChatResearchRuns.mockResolvedValue([]);
  });

  it("preserves partial output, commits it, exposes recovery, and clears busy", async () => {
    apiMocks.commitTurn.mockResolvedValue({ committed: true });
    apiMocks.sendChatStream.mockImplementation(
      async (_question, _history, _options, callbacks, requestOptions) =>
        new Promise((_resolve, reject) => {
          callbacks.onSession("chat-stop", {
            turnId: "turn-stop",
            operationId: "op-stop",
          });
          callbacks.onRoute({ role: "nahida", mode: "normal", model_profile: "flash" });
          callbacks.onToken("partial token");
          requestOptions.signal.addEventListener("abort", () => {
            reject(new DOMException("stopped", "AbortError"));
          });
        })
    );

    const { Harness, getController } = controllerHarness();
    await act(async () => {
      create(
        <WorkspaceProvider initialState={{ activeChatThreadId: "chat-stop" }}>
          <Harness />
        </WorkspaceProvider>
      );
    });

    let sendPromise: Promise<void> | undefined;
    await act(async () => {
      sendPromise = getController()!.send("question");
      await Promise.resolve();
    });
    expect(getController()!.isSending).toBe(true);

    await act(async () => {
      getController()!.stop();
      await sendPromise;
    });

    expect(getController()!.isSending).toBe(false);
    expect(getController()!.streamRecovery).toEqual({
      question: "question",
      reply: "partial token",
      reason: "已停止生成",
      sessionId: "chat-stop",
      turnId: "turn-stop",
    });
    const lastMessage = getController()!.messages[getController()!.messages.length - 1];
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
      })
    );
    expect(apiMocks.cancelChatResearchRuns).toHaveBeenCalledWith("turn-stop");
    expect(operationRegistry.size).toBe(0);
  });

  it("restores committed learning state instead of interrupted attempted state", async () => {
    apiMocks.loadSessionDetail.mockResolvedValue({
      session_id: "chat-restore",
      kind: "active",
      path: "",
      messages: [
        {
          role: "user",
          content: "继续",
          turnId: "turn-interrupted",
          turnStatus: "interrupted",
        },
        {
          role: "assistant",
          content: "partial",
          avatarRole: "nahida",
          turnId: "turn-interrupted",
          turnStatus: "interrupted",
        },
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
        payload: {
          pedagogy_evaluation: {
            final_decision: "reject",
            reasons: ["reasoning_incomplete"],
          },
        },
      },
      summary: {},
      navigation: {},
      pedagogy: { mode: "socratic_rediscovery", phase: "repair", move: "minimal_repair" },
      latest_attempted_pedagogy: { phase: "complete" },
      conversation_instruction: "",
      turns: [
        {
          turn_id: "turn-completed",
          status: "completed",
          user_message: "explain",
          assistant_message: "answer",
          pedagogy_snapshot: {
            committed_learning_state: { phase: "repair" },
          },
        },
        {
          turn_id: "turn-interrupted",
          status: "interrupted",
          user_message: "继续",
          assistant_message: "partial",
          pedagogy_snapshot: {
            learning_state_after: { phase: "complete" },
          },
        },
      ],
      raw: "",
    });

    const { Harness, getController } = controllerHarness();
    await act(async () => {
      create(
        <WorkspaceProvider>
          <Harness />
        </WorkspaceProvider>
      );
    });
    await act(async () => {
      await getController()!.restoreSession("chat-restore");
    });

    const restoredLearningState = getController()!.lastChat?.route?.learning_state as
      | Record<string, unknown>
      | undefined;
    expect(restoredLearningState?.objective).toBe("committed objective");
    expect(restoredLearningState?.phase).toBe("repair");
    expect(restoredLearningState?.unresolved_gap).toBe("committed gap");
    expect(restoredLearningState?.objective).not.toBe("planned objective must not win");
  });
});
