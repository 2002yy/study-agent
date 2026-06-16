import type {
  ApiSnapshot,
  ChatMessage,
  ChatResponse,
  ChatSettings,
  HealthResponse,
  MemoryCommitResponse,
  MemoryPreviewResponse,
  MemoryStatusResponse,
  MemoryUpdate,
  NewsLookupResponse,
  NewsSearchResponse,
  RagSettings,
  RagIndexResponse,
  RagQueryResponse,
  RagStatusResponse,
  RoleResponse,
  SessionRow,
  ToolInvocationResponse,
  ToolSpec,
  WechatMessageResponse,
  WechatStateResponse,
  WorkflowRunDetail,
  WorkflowRunSummary,
  RuntimeSettingsResponse
} from "./types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";
const API_TOKEN = import.meta.env.VITE_STUDY_AGENT_API_TOKEN ?? "";

function authHeaders(): HeadersInit {
  return API_TOKEN ? { "X-Study-Agent-Token": API_TOKEN } : {};
}

async function requestJson<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
      ...(options?.headers ?? {})
    },
    ...options
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`${response.status} ${response.statusText}${body ? `: ${body}` : ""}`);
  }
  return (await response.json()) as T;
}

async function uploadForm<T>(path: string, formData: FormData): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: authHeaders(),
    body: formData
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`${response.status} ${response.statusText}${body ? `: ${body}` : ""}`);
  }
  return (await response.json()) as T;
}

type ChatRequestOptions = {
  ragEnabled: boolean;
  sessionId?: string;
  chatSettings: ChatSettings;
  ragSettings: RagSettings;
  webContext?: string;
  conversationInstruction?: string;
  scene?: "single" | "group";
};

type ChatStreamHandlers = {
  onRoute?: (route: Record<string, unknown>) => void;
  onRag?: (rag: ChatResponse["rag"]) => void;
  onToken?: (token: string) => void;
  onUsage?: (usage: Record<string, unknown>) => void;
  onDone?: (done: Record<string, unknown>) => void;
  onError?: (error: Record<string, unknown>) => void;
};

type SseMessage = {
  event: string;
  data: Record<string, unknown>;
};

function buildChatPayload(userInput: string, history: ChatMessage[], options: ChatRequestOptions): Record<string, unknown> {
  return {
    user_input: userInput,
    selected_role: options.chatSettings.selectedRole,
    selected_mode: options.chatSettings.selectedMode,
    selected_model: options.chatSettings.selectedModel,
    relationship_mode: options.chatSettings.relationshipMode,
    scene: options.scene ?? "single",
    conversation_instruction: options.conversationInstruction ?? "",
    performance_mode: performanceModeFromContext(options.chatSettings.contextMode),
    context_mode: options.chatSettings.contextMode || null,
    chat_history: history.map((message) => ({
      role: message.role,
      content: message.content
    })),
    session_id: options.sessionId,
    rag_enabled: options.ragEnabled,
    rag_top_k: options.ragSettings.chatTopK,
    rag_retrieval_mode: options.ragSettings.retrievalMode,
    web_context: options.webContext ?? ""
  };
}

function performanceModeFromContext(contextMode: string): "fast" | "standard" | "deep" | null {
  if (contextMode === "fast") {
    return "fast";
  }
  if (contextMode === "deep") {
    return "deep";
  }
  if (contextMode === "light") {
    return "standard";
  }
  return null;
}

function parseSseMessages(raw: string): SseMessage[] {
  return raw
    .split(/\r?\n\r?\n/)
    .map((block) => block.trim())
    .filter(Boolean)
    .map((block) => {
      let event = "message";
      const dataLines: string[] = [];
      for (const line of block.split(/\r?\n/)) {
        if (line.startsWith("event:")) {
          event = line.slice("event:".length).trim();
        } else if (line.startsWith("data:")) {
          dataLines.push(line.slice("data:".length).trimStart());
        }
      }
      const dataText = dataLines.join("\n") || "{}";
      return {
        event,
        data: JSON.parse(dataText) as Record<string, unknown>
      };
    });
}

export async function loadApiSnapshot(): Promise<ApiSnapshot> {
  try {
    const [health, ragStatus, tools, workflows, sessions, runtimeSettings, memoryStatus, wechat] = await Promise.all([
      requestJson<HealthResponse>("/health"),
      requestJson<RagStatusResponse>("/rag/status"),
      requestJson<{ tools: ToolSpec[] }>("/tools"),
      requestJson<{ runs: WorkflowRunSummary[] }>("/workflows/runs"),
      requestJson<{ sessions: SessionRow[] }>("/sessions"),
      requestJson<RuntimeSettingsResponse>("/runtime/settings"),
      requestJson<MemoryStatusResponse>("/memory"),
      requestJson<WechatStateResponse>("/wechat")
    ]);
    return {
      health,
      ragStatus,
      tools: tools.tools,
      workflowRuns: workflows.runs,
      sessions: sessions.sessions,
      runtimeSettings,
      memoryStatus,
      wechat,
      error: ""
    };
  } catch (error) {
    return {
      health: null,
      ragStatus: null,
      tools: [],
      workflowRuns: [],
      sessions: [],
      runtimeSettings: null,
      memoryStatus: null,
      wechat: null,
      error: error instanceof Error ? error.message : "API unavailable"
    };
  }
}

export async function saveRuntimeSettings(payload: Partial<RuntimeSettingsResponse["settings"]>): Promise<RuntimeSettingsResponse> {
  return requestJson<RuntimeSettingsResponse>("/runtime/settings", {
    method: "PATCH",
    body: JSON.stringify(payload)
  });
}

export async function loadRole(roleId: string): Promise<RoleResponse> {
  return requestJson<RoleResponse>(`/roles/${encodeURIComponent(roleId)}`);
}

export async function previewMemoryUpdates(updates: MemoryUpdate[]): Promise<MemoryPreviewResponse> {
  return requestJson<MemoryPreviewResponse>("/memory/preview", {
    method: "POST",
    body: JSON.stringify({ updates })
  });
}

export async function commitMemoryUpdates(updates: MemoryUpdate[]): Promise<MemoryCommitResponse> {
  return requestJson<MemoryCommitResponse>("/memory/commit", {
    method: "POST",
    body: JSON.stringify({ updates })
  });
}

export async function loadWechatState(): Promise<WechatStateResponse> {
  return requestJson<WechatStateResponse>("/wechat");
}

export async function resetWechat(): Promise<WechatStateResponse> {
  return requestJson<WechatStateResponse>("/wechat/reset", { method: "POST" });
}

export async function markWechatRead(sessionId?: string): Promise<WechatStateResponse> {
  const suffix = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : "";
  return requestJson<WechatStateResponse>(`/wechat/mark-read${suffix}`, { method: "POST" });
}

export async function createWechatOpening(chatSettings: ChatSettings): Promise<WechatStateResponse> {
  return requestJson<WechatStateResponse>("/wechat/opening", {
    method: "POST",
    body: JSON.stringify({
      selected_role: chatSettings.selectedRole,
      selected_model: chatSettings.selectedModel,
      relationship_mode: chatSettings.relationshipMode,
      performance_mode: performanceModeFromContext(chatSettings.contextMode)
    })
  });
}

export async function sendWechatMessage(
  message: string,
  options: {
    sessionId?: string;
    ragEnabled: boolean;
    chatSettings: ChatSettings;
    ragSettings: RagSettings;
  }
): Promise<WechatMessageResponse> {
  return requestJson<WechatMessageResponse>("/wechat/message", {
    method: "POST",
    body: JSON.stringify({
      message,
      session_id: options.sessionId,
      selected_model: options.chatSettings.selectedModel,
      relationship_mode: options.chatSettings.relationshipMode,
      performance_mode: performanceModeFromContext(options.chatSettings.contextMode),
      rag_enabled: options.ragEnabled,
      rag_top_k: options.ragSettings.chatTopK,
      rag_retrieval_mode: options.ragSettings.retrievalMode
    })
  });
}

export async function runNewsSearch(
  query: string,
  options: {
    sessionId?: string;
    readArticles: boolean;
    chatSettings: ChatSettings;
  }
): Promise<NewsSearchResponse> {
  return requestJson<NewsSearchResponse>("/news/search", {
    method: "POST",
    body: JSON.stringify({
      query,
      session_id: options.sessionId,
      read_articles: options.readArticles,
      selected_model: options.chatSettings.selectedModel,
      relationship_mode: options.chatSettings.relationshipMode,
      performance_mode: performanceModeFromContext(options.chatSettings.contextMode)
    })
  });
}

export async function lookupNews(query: string, maxItems = 8): Promise<NewsLookupResponse> {
  return requestJson<NewsLookupResponse>("/news/lookup", {
    method: "POST",
    body: JSON.stringify({
      query,
      max_items: maxItems
    })
  });
}

export async function loadSessions(): Promise<SessionRow[]> {
  const response = await requestJson<{ sessions: SessionRow[] }>("/sessions");
  return response.sessions;
}

export async function loadRagStatus(): Promise<RagStatusResponse> {
  return requestJson<RagStatusResponse>("/rag/status");
}

export async function uploadDocuments(files: File[]): Promise<RagIndexResponse> {
  const formData = new FormData();
  files.forEach((file) => formData.append("files", file));
  return uploadForm<RagIndexResponse>("/rag/upload", formData);
}

export async function queryRag(query: string, settings: RagSettings): Promise<RagQueryResponse> {
  return requestJson<RagQueryResponse>("/rag/query", {
    method: "POST",
    body: JSON.stringify({
      query,
      top_k: settings.topK,
      min_score: settings.minScore,
      retrieval_mode: settings.retrievalMode
    })
  });
}

export async function sendChat(
  userInput: string,
  history: ChatMessage[],
  options: ChatRequestOptions
): Promise<ChatResponse> {
  return requestJson<ChatResponse>("/chat", {
    method: "POST",
    body: JSON.stringify(buildChatPayload(userInput, history, options))
  });
}

export async function sendChatStream(
  userInput: string,
  history: ChatMessage[],
  options: ChatRequestOptions,
  handlers: ChatStreamHandlers = {}
): Promise<ChatResponse> {
  const response = await fetch(`${API_BASE_URL}/chat/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...authHeaders()
    },
    body: JSON.stringify(buildChatPayload(userInput, history, options))
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`${response.status} ${response.statusText}${body ? `: ${body}` : ""}`);
  }
  if (!response.body) {
    return sendChat(userInput, history, options);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let reply = "";
  let sessionId = options.sessionId ?? "";
  let route: Record<string, unknown> = {};
  let rag: ChatResponse["rag"] | null = null;

  const handleMessage = (message: SseMessage) => {
    if (message.event === "route") {
      route = message.data.route && typeof message.data.route === "object" ? (message.data.route as Record<string, unknown>) : message.data;
      handlers.onRoute?.(route);
      return;
    }
    if (message.event === "rag") {
      rag = (message.data.rag && typeof message.data.rag === "object" ? message.data.rag : message.data) as ChatResponse["rag"];
      handlers.onRag?.(rag);
      return;
    }
    if (message.event === "token") {
      const text = typeof message.data.text === "string" ? message.data.text : "";
      reply += text;
      handlers.onToken?.(text);
      return;
    }
    if (message.event === "usage") {
      const usage = message.data.usage && typeof message.data.usage === "object" ? (message.data.usage as Record<string, unknown>) : message.data;
      handlers.onUsage?.(usage);
      return;
    }
    if (message.event === "done") {
      if (typeof message.data.session_id === "string") {
        sessionId = message.data.session_id;
      }
      handlers.onDone?.(message.data);
      return;
    }
    if (message.event === "error") {
      handlers.onError?.(message.data);
      const detail = typeof message.data.message === "string" ? message.data.message : "聊天流式请求失败";
      throw new Error(detail);
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split(/\r?\n\r?\n/);
    buffer = parts.pop() ?? "";
    for (const message of parseSseMessages(parts.join("\n\n"))) {
      handleMessage(message);
    }
  }

  buffer += decoder.decode();
  for (const message of parseSseMessages(buffer)) {
    handleMessage(message);
  }

  return {
    reply,
    session_id: sessionId,
    route,
    rag: rag ?? {
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
}

export async function previewLocalKnowledge(query: string): Promise<ToolInvocationResponse> {
  return requestJson<ToolInvocationResponse>("/tools/retrieve_local_knowledge/preview", {
    method: "POST",
    body: JSON.stringify({
      args: {
        query,
        retrieval_mode: "hybrid",
        top_k: 3
      }
    })
  });
}

export async function callLocalKnowledge(query: string, runId?: string): Promise<ToolInvocationResponse> {
  return requestJson<ToolInvocationResponse>("/tools/retrieve_local_knowledge/call", {
    method: "POST",
    body: JSON.stringify({
      run_id: runId,
      args: {
        query,
        retrieval_mode: "hybrid",
        top_k: 3
      }
    })
  });
}

export async function loadWorkflowRun(runId: string): Promise<WorkflowRunDetail> {
  const response = await requestJson<{ run: WorkflowRunDetail }>(`/workflows/runs/${encodeURIComponent(runId)}`);
  return response.run;
}
