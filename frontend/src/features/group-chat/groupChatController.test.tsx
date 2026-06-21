import React from "react";
import { act, create } from "react-test-renderer";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { operationRegistry } from "../../app/operationRegistry";
import { WorkspaceProvider } from "../../app/WorkspaceProvider";
import type { WechatStateResponse } from "../../types";
import { useGroupChatController } from "./groupChatController";

const apiMocks = vi.hoisted(() => ({
  createWechatOpening: vi.fn(),
  markWechatRead: vi.fn(),
  resetWechat: vi.fn(),
  sendWechatMessageStream: vi.fn(),
}));

vi.mock("../../api", () => apiMocks);

const initialWechat: WechatStateResponse = {
  group_thread_id: "group-test",
  state: { mode: "interactive_group" },
  content: "",
  unread: "",
  has_unread: false,
  started: false,
  message_count: 0,
  unread_count: 0,
  summary: "",
};

describe("useGroupChatController", () => {
  beforeEach(() => {
    operationRegistry.cancelAll();
    vi.clearAllMocks();
  });

  it("owns streaming send and settles a user stop without stale busy", async () => {
    apiMocks.sendWechatMessageStream.mockImplementation(
      async (_message, _options, handlers, requestOptions) =>
        new Promise((_resolve, reject) => {
          handlers.onSession({
            groupThreadId: "group-test",
            messageId: "group-message",
            operationId: "group-operation",
          });
          handlers.onToken("【纳西妲】\npartial");
          requestOptions.signal.addEventListener("abort", () => {
            reject(new DOMException("stopped", "AbortError"));
          });
        })
    );
    const setWechat = vi.fn();
    let controller: ReturnType<typeof useGroupChatController> | undefined;

    function Harness() {
      controller = useGroupChatController({
        wechat: initialWechat,
        setWechat,
        chatSettings: {
          selectedRole: "auto",
          selectedMode: "auto",
          selectedModel: "flash",
          relationshipMode: "standard",
          contextMode: "fast",
        },
        ragSettings: {
          retrievalMode: "hybrid",
          topK: 5,
          chatTopK: 3,
          minScore: 0,
        },
        ragEnabled: false,
        clearAssociatedNews: vi.fn(),
      });
      return null;
    }

    await act(async () => {
      create(
        <WorkspaceProvider initialState={{ activeGroupThreadId: "group-test" }}>
          <Harness />
        </WorkspaceProvider>
      );
    });
    await act(async () => controller!.setInput("question"));

    let sendPromise: Promise<void> | undefined;
    await act(async () => {
      sendPromise = controller!.send({ preventDefault: vi.fn() } as never);
      await Promise.resolve();
    });
    expect(controller!.isBusy).toBe(true);

    await act(async () => {
      controller!.stop();
      await sendPromise;
    });

    expect(controller!.isBusy).toBe(false);
    expect(controller!.error).toContain("已停止生成");
    expect(apiMocks.sendWechatMessageStream).toHaveBeenCalledWith(
      "question",
      expect.objectContaining({ groupThreadId: "group-test" }),
      expect.any(Object),
      expect.any(Object)
    );
    expect(setWechat).toHaveBeenLastCalledWith(initialWechat);
    expect(operationRegistry.size).toBe(0);
  });
});
