import { afterEach, describe, expect, it, vi } from "vitest";
import { callLocalKnowledge, loadApiSnapshot, previewLocalKnowledge, sendChatStream } from "./api";
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

  it("sends scene and conversation instruction in the chat payload", async () => {
    const fetchMock = vi.fn(async () =>
      sseResponse([
        'event: done\ndata: {"session_id":"session-2","reply":"done"}\n\n'
      ])
    );
    vi.stubGlobal("fetch", fetchMock);

    await sendChatStream(
      "直接回答",
      [{ role: "user", content: "上文", avatarRole: "user" }],
      {
        ragEnabled: false,
        chatSettings: { ...chatSettings, contextMode: "deep" },
        ragSettings: { ...ragSettings, minScore: 0.42 },
        conversationInstruction: "不要转交给其他角色。",
        scene: "single"
      }
    );

    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    const body = JSON.parse(String(init.body));
    expect(body.scene).toBe("single");
    expect(body.conversation_instruction).toBe("不要转交给其他角色。");
    expect(body.performance_mode).toBe("deep");
    expect(body.rag_min_score).toBe(0.42);
  });
});

describe("local knowledge tool calls", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("uses the same invocation snapshot for preview and call", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(
        JSON.stringify({
          tool_name: "retrieve_local_knowledge",
          status: "preview",
          output: {},
          reason: "ok",
          elapsed_ms: 0,
          run_id: "preview-1"
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      )
    );
    vi.stubGlobal("fetch", fetchMock);
    const invocation = {
      query: "RAG",
      retrievalMode: "hybrid" as const,
      topK: 7,
      minScore: 0.33,
      previewId: "preview-1"
    };

    await previewLocalKnowledge(invocation);
    await callLocalKnowledge(invocation);

    const [, previewInit] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    const [, callInit] = fetchMock.mock.calls[1] as unknown as [string, RequestInit];
    const previewBody = JSON.parse(String(previewInit.body));
    const callBody = JSON.parse(String(callInit.body));
    expect(previewBody.args).toEqual({
      query: "RAG",
      retrieval_mode: "hybrid",
      top_k: 7,
      min_score: 0.33
    });
    expect(callBody.run_id).toBe("preview-1");
    expect(callBody.args).toEqual(previewBody.args);
  });
});

describe("loadApiSnapshot", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("keeps healthy API data when one auxiliary endpoint fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (url.endsWith("/workflows/runs")) {
          return new Response("workflow down", { status: 500, statusText: "Internal Server Error" });
        }
        const payloads: Record<string, unknown> = {
          "/health": { status: "ok", service: "study-agent", rag_index_exists: true },
          "/rag/status": { index_exists: true, documents: 0, chunks: 0, index_path: "", vector_backend: { name: "local" } },
          "/tools": { tools: [] },
          "/sessions": { sessions: [] },
          "/runtime/settings": { settings: {}, options: {}, runtime_profile: {}, warnings: [] },
          "/memory": { writable: false, memory_mode: "preview", safe_mode: false, reason: "preview", context_mode: "light", groups: {}, files: [] },
          "/wechat": { state: {}, content: "", unread: "", has_unread: false, started: false, message_count: 0, unread_count: 0, summary: "" }
        };
        const path = new URL(url, "http://localhost").pathname;
        return new Response(JSON.stringify(payloads[path]), { status: 200, headers: { "Content-Type": "application/json" } });
      })
    );

    const snapshot = await loadApiSnapshot();

    expect(snapshot.health?.status).toBe("ok");
    expect(snapshot.error).toBe("");
    expect(snapshot.errors.workflows).toContain("500");
  });
});
