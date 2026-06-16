import { afterEach, describe, expect, it, vi } from "vitest";
import { sendChatStream } from "./api";
import type { ChatSettings, RagSettings } from "./types";

const chatSettings: ChatSettings = {
  selectedRole: "auto",
  selectedMode: "auto",
  selectedModel: "flash",
  relationshipMode: "standard",
  contextMode: ""
};

const ragSettings: RagSettings = {
  retrievalMode: "hybrid",
  topK: 5,
  minScore: 0.01,
  chatTopK: 3
};

function sseResponse(chunks: string[]): Response {
  const encoder = new TextEncoder();
  return new Response(
    new ReadableStream({
      start(controller) {
        for (const chunk of chunks) {
          controller.enqueue(encoder.encode(chunk));
        }
        controller.close();
      }
    }),
    {
      status: 200,
      headers: { "Content-Type": "text/event-stream" }
    }
  );
}

describe("sendChatStream", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("parses backend SSE events that send route and rag as direct objects", async () => {
    const tokens: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        sseResponse([
          'event: route\ndata: {"role":"march7","mode":"苏格拉底"}\n\n',
          'event: rag\ndata: {"status":"found","query":"RAG","retrieval_mode":"hybrid","reason":"","context":"","sources":"","result_count":1,"results":[],"debug":{},"attempts":[],"rewritten_query":"RAG"}\n\n',
          'event: token\ndata: {"text":"RAG"}\n\n',
          'event: token\ndata: {"text":" 是检索增强生成。"}\n\n',
          'event: usage\ndata: {"estimated":true,"output_chars":12}\n\n',
          'event: done\ndata: {"session_id":"session-1","reply":"RAG 是检索增强生成。"}\n\n'
        ])
      )
    );

    const response = await sendChatStream(
      "解释 RAG",
      [{ role: "user", content: "解释 RAG", avatarRole: "user" }],
      { ragEnabled: true, chatSettings, ragSettings },
      { onToken: (token) => tokens.push(token) }
    );

    expect(response.session_id).toBe("session-1");
    expect(response.route.role).toBe("march7");
    expect(response.rag.query).toBe("RAG");
    expect(response.reply).toBe("RAG 是检索增强生成。");
    expect(tokens).toEqual(["RAG", " 是检索增强生成。"]);
  });
});
