import React, { type Dispatch, type SetStateAction } from "react";
import { act, create } from "react-test-renderer";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { operationRegistry } from "../../app/operationRegistry";
import { WorkspaceProvider } from "../../app/WorkspaceProvider";
import type { ChatSettings, RagSettings } from "../../types";
import { useChatController } from "./chatController";

const apiMocks = vi.hoisted(() => ({
  archiveSession: vi.fn(),
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

describe("useChatController stop behavior", () => {
  beforeEach(() => {
    operationRegistry.cancelAll();
    vi.clearAllMocks();
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

    await act(async () => {
      create(
        <WorkspaceProvider initialState={{ activeChatThreadId: "chat-stop" }}>
          <Harness />
        </WorkspaceProvider>
      );
    });

    let sendPromise: Promise<void> | undefined;
    await act(async () => {
      sendPromise = controller!.send("question");
      await Promise.resolve();
    });
    expect(controller!.isSending).toBe(true);

    await act(async () => {
      controller!.stop();
      await sendPromise;
    });

    expect(controller!.isSending).toBe(false);
    expect(controller!.streamRecovery).toEqual({
      question: "question",
      reply: "partial token",
      reason: "已停止生成",
      sessionId: "chat-stop",
      turnId: "turn-stop",
    });
    const lastMessage = controller!.messages[controller!.messages.length - 1];
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
    expect(operationRegistry.size).toBe(0);
  });
});
