import { afterEach, describe, expect, it, vi } from "vitest";
import {
  callLocalKnowledge,
  archiveSession,
  digestNewsStage,
  discussNewsStage,
  enrichNewsStage,
  loadApiSnapshot,
  lookupNews,
  previewLocalKnowledge,
  queryRag,
  searchWechat,
  searchNewsStage,
  sendChatStream,
  sendWechatMessage,
  sendWechatMessageStream,
  runNewsSearch,
  uploadDocuments
} from "./api";
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
        keepCurrentRole: true,
        previousMode: "苏格拉底",
        conversationInstruction: "不要转交给其他角色。",
        scene: "single"
      }
    );

    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    const body = JSON.parse(String(init.body));
    expect(body.scene).toBe("single");
    expect(body.conversation_instruction).toBe("不要转交给其他角色。");
    expect(body.performance_mode).toBe("deep");
    expect(body.previous_mode).toBe("苏格拉底");
    expect(body.rag_min_score).toBe(0.42);
    expect(body.rag_search_top_k).toBe(ragSettings.topK);
    expect(body.rag_chat_top_k).toBe(ragSettings.chatTopK);
    expect(body.keep_current_role).toBe(true);
    expect(body.chat_history[0].avatarRole).toBe("user");
  });

  it("passes an abort signal to the streaming request", async () => {
    const fetchMock = vi.fn(async () =>
      sseResponse([
        'event: done\ndata: {"session_id":"session-3","reply":"done"}\n\n'
      ])
    );
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await sendChatStream(
      "stop-aware",
      [],
      { ragEnabled: false, chatSettings, ragSettings },
      {},
      { signal: controller.signal }
    );

    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(init.signal).toBe(controller.signal);
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

describe("RAG API calls", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("uses search topK for standalone RAG queries", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(
        JSON.stringify({
          query: "RAG",
          retrieval_mode: "hybrid",
          status: "found",
          reason: "",
          context: "",
          sources: "",
          results: [],
          result_count: 0,
          debug: {},
          attempts: [],
          rewritten_query: "RAG"
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      )
    );
    vi.stubGlobal("fetch", fetchMock);

    await queryRag("RAG", { ...ragSettings, topK: 8, chatTopK: 2 });

    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    const body = JSON.parse(String(init.body));
    expect(body.top_k).toBe(8);
  });

  it("parses local and vector upload stages", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(
        JSON.stringify({
          documents: 1,
          chunks: 2,
          index_path: "logs/rag_index.json",
          stages: [
            { name: "local", status: "completed", documents: 1, chunks: 2 },
            { name: "vector", status: "failed", detail: "vector offline" }
          ]
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      )
    );
    vi.stubGlobal("fetch", fetchMock);

    const response = await uploadDocuments([new File(["hello"], "note.md", { type: "text/markdown" })]);

    expect(response.stages?.[0].name).toBe("local");
    expect(response.stages?.[1].status).toBe("failed");
  });
});

describe("wechat API calls", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends chat RAG settings with group messages", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(
        JSON.stringify({
          reply: "ok",
          content: "group",
          state: {},
          session_id: "wechat-session",
          rag: { status: "found" }
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      )
    );
    vi.stubGlobal("fetch", fetchMock);

    await sendWechatMessage("hello", {
      sessionId: "session-1",
      ragEnabled: true,
      chatSettings,
      ragSettings: { ...ragSettings, topK: 9, chatTopK: 4, minScore: 0.37 }
    });

    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    const body = JSON.parse(String(init.body));
    expect(body.rag_min_score).toBe(0.37);
    expect(body.rag_chat_top_k).toBe(4);
    expect(body.rag_top_k).toBe(4);
  });

  it("parses streaming group message events", async () => {
    const tokens: string[] = [];
    const fetchMock = vi.fn(async () =>
      sseResponse([
        'event: rag\ndata: {"status":"found","result_count":1}\n\n',
        'event: token\ndata: {"text":"【纳西妲】\\n"}\n\n',
        'event: token\ndata: {"text":"先看结构。"}\n\n',
        'event: done\ndata: {"reply":"【纳西妲】\\n先看结构。","content":"group content","state":{"mode":"interactive_group"},"session_id":"wechat-session","rag":{"status":"found"}}\n\n'
      ])
    );
    vi.stubGlobal("fetch", fetchMock);

    const response = await sendWechatMessageStream(
      "hello",
      {
        sessionId: "session-1",
        ragEnabled: true,
        chatSettings,
        ragSettings: { ...ragSettings, minScore: 0.37 }
      },
      { onToken: (token) => tokens.push(token) }
    );

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    const body = JSON.parse(String(init.body));
    expect(url).toBe("/wechat/message/stream");
    expect(body.rag_min_score).toBe(0.37);
    expect(tokens).toEqual(["【纳西妲】\n", "先看结构。"]);
    expect(response.reply).toBe("【纳西妲】\n先看结构。");
    expect(response.content).toBe("group content");
    expect(response.session_id).toBe("wechat-session");
  });
});

describe("wechat search API", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("posts the keyword and max result limit to the backend", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ keyword: "RAG", results: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      })
    );
    vi.stubGlobal("fetch", fetchMock);

    const response = await searchWechat("RAG", 12);

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/wechat/search");
    expect(JSON.parse(String(init.body))).toEqual({ keyword: "RAG", max_results: 12 });
    expect(response.keyword).toBe("RAG");
  });
});

describe("session API calls", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("archives a session by id", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ session_id: "abc", kind: "archived", path: "session.md", archived: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      })
    );
    vi.stubGlobal("fetch", fetchMock);

    const response = await archiveSession("abc");

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/sessions/abc/archive");
    expect(init.method).toBe("POST");
    expect(response.archived).toBe(true);
  });
});

describe("news API calls", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("keeps the compatibility news round on /news/round", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(
        JSON.stringify({
          query_text: "AI",
          news_items: [],
          digest: "digest",
          discussion: "discussion",
          group_content: "group",
          source_block: "source",
          article_coverage: {},
          elapsed_ms: 1,
          warnings: [],
          audit_markdown_path: "",
          audit_json_path: "",
          session_id: "news-session"
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      )
    );
    vi.stubGlobal("fetch", fetchMock);

    await runNewsSearch("AI", { sessionId: "session-1", readArticles: false, chatSettings });

    const [url] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/news/round");
  });

  it("posts phased news requests to the stage endpoints", async () => {
    const fetchMock = vi.fn(async (url: string, _init?: RequestInit) => {
      const payloads: Record<string, unknown> = {
        "/news/search": { query_text: "AI", news_items: [{ title: "A" }] },
        "/news/enrich": { query_text: "AI", news_items: [{ title: "A", article_text: "body" }] },
        "/news/digest": { query_text: "AI", digest: "digest", source_block: "source", article_coverage: {}, warnings: [] },
        "/news/discuss": { discussion: "discussion", group_content: "group", session_id: "news-session" }
      };
      return new Response(JSON.stringify(payloads[url]), { status: 200, headers: { "Content-Type": "application/json" } });
    });
    vi.stubGlobal("fetch", fetchMock);

    const search = await searchNewsStage("AI", 4);
    const enrich = await enrichNewsStage({ queryText: search.query_text, newsItems: search.news_items, maxArticles: 2 });
    const digest = await digestNewsStage({ queryText: enrich.query_text, newsItems: enrich.news_items, chatSettings });
    const discuss = await discussNewsStage({ digest: digest.digest, sourceBlock: digest.source_block, sessionId: "session-1", chatSettings });

    const calls = fetchMock.mock.calls.map(([url, init]) => [url, JSON.parse(String(init?.body))]);
    expect(calls[0][0]).toBe("/news/search");
    expect(calls[0][1]).toMatchObject({ query: "AI", max_items: 4 });
    expect(calls[1][0]).toBe("/news/enrich");
    expect(calls[1][1]).toMatchObject({ query_text: "AI", max_articles: 2 });
    expect(calls[2][0]).toBe("/news/digest");
    expect(calls[3][0]).toBe("/news/discuss");
    expect(discuss.session_id).toBe("news-session");
  });

  it("passes AbortSignal through news stage requests", async () => {
    const fetchMock = vi.fn(async (url: string, _init?: RequestInit) => {
      const payloads: Record<string, unknown> = {
        "/news/search": { query_text: "AI", news_items: [] },
        "/news/enrich": { query_text: "AI", news_items: [] },
        "/news/digest": { query_text: "AI", digest: "digest", source_block: "source", article_coverage: {}, warnings: [] },
        "/news/discuss": { discussion: "discussion", group_content: "group", session_id: "news-session" },
        "/news/round": {
          query_text: "AI",
          news_items: [],
          digest: "digest",
          discussion: "discussion",
          group_content: "group",
          source_block: "source",
          article_coverage: {},
          elapsed_ms: 1,
          warnings: [],
          audit_markdown_path: "",
          audit_json_path: "",
          session_id: "news-session"
        },
        "/news/lookup": { query_text: "AI", news_items: [], source_block: "", elapsed_ms: 1 }
      };
      return new Response(JSON.stringify(payloads[url]), { status: 200, headers: { "Content-Type": "application/json" } });
    });
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await searchNewsStage("AI", 4, { signal: controller.signal });
    await enrichNewsStage({ queryText: "AI", newsItems: [], maxArticles: 2 }, { signal: controller.signal });
    await digestNewsStage({ queryText: "AI", newsItems: [], chatSettings }, { signal: controller.signal });
    await discussNewsStage({ digest: "digest", sourceBlock: "source", sessionId: "thread-1", chatSettings }, { signal: controller.signal });
    await runNewsSearch("AI", { sessionId: "thread-1", readArticles: false, chatSettings }, { signal: controller.signal });
    await lookupNews("AI", 8, { signal: controller.signal });

    for (const [, init] of fetchMock.mock.calls) {
      expect((init as RequestInit).signal).toBe(controller.signal);
    }
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
