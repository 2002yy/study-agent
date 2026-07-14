import { afterEach, describe, expect, it, vi } from "vitest";

import { sendChatStream } from "../../api";
import type { ChatSettings, RagSettings } from "../../types";
import {
  clearPendingTaskIntentOverride,
  setPendingTaskIntentOverride,
} from "./taskContract";

const chatSettings: ChatSettings = {
  selectedRole: "auto",
  selectedMode: "auto",
  selectedModel: "flash",
  relationshipMode: "standard",
  contextMode: "",
};

const ragSettings: RagSettings = {
  retrievalMode: "hybrid",
  topK: 5,
  minScore: 0.01,
  chatTopK: 3,
};

function sseResponse(chunks: string[]): Response {
  const encoder = new TextEncoder();
  return new Response(
    new ReadableStream({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
        controller.close();
      },
    }),
    { status: 200, headers: { "Content-Type": "text/event-stream" } }
  );
}

describe("task intent chat transport", () => {
  afterEach(() => {
    clearPendingTaskIntentOverride();
    vi.unstubAllGlobals();
  });

  it("sends a selected intent with the next streaming turn only", async () => {
    const fetchMock = vi.fn(async () =>
      sseResponse([
        'event: done\ndata: {"session_id":"session-1","reply":"ok"}\n\n',
      ])
    );
    vi.stubGlobal("fetch", fetchMock);
    setPendingTaskIntentOverride("research");

    await sendChatStream(
      "查一下最新进展",
      [],
      { ragEnabled: true, chatSettings, ragSettings }
    );

    const [, firstInit] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    const firstBody = JSON.parse(String(firstInit.body));
    expect(firstBody.task_intent).toBe("research");

    await sendChatStream(
      "第二条自动判断",
      [],
      { ragEnabled: true, chatSettings, ragSettings }
    );

    const [, secondInit] = fetchMock.mock.calls[1] as unknown as [string, RequestInit];
    const secondBody = JSON.parse(String(secondInit.body));
    expect(secondBody.task_intent).toBeNull();
  });

  it("reuses the same override when streaming falls back to non-stream chat", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(null, { status: 200 }))
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            reply: "fallback",
            session_id: "session-fallback",
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
              rewritten_query: "",
            },
          }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        )
      );
    vi.stubGlobal("fetch", fetchMock);
    setPendingTaskIntentOverride("quick_answer");

    const response = await sendChatStream(
      "只回答当前问题",
      [],
      { ragEnabled: false, chatSettings, ragSettings }
    );

    expect(response.reply).toBe("fallback");
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const [, streamInit] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    const [, fallbackInit] = fetchMock.mock.calls[1] as unknown as [string, RequestInit];
    expect(JSON.parse(String(streamInit.body)).task_intent).toBe("quick_answer");
    expect(JSON.parse(String(fallbackInit.body)).task_intent).toBe("quick_answer");
  });
});
