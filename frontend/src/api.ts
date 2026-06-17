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
  SessionDetailResponse,
  SessionArchiveResponse,
  SessionNewResponse,
  SessionRow,
  ToolInvocationResponse,
  ToolSpec,
  WechatMessageResponse,
  WechatSearchResponse,
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
  keepCurrentRole?: boolean;
  webContext?: string;
  conversationInstruction?: string;
  previousMode?: string;
  scene?: "single" | "group";
  continuationOfTurnId?: string;
  partialReply?: string;
};

type ChatStreamHandlers = {
  onRoute?: (route: Record<string, unknown>) => void;
  onRag?: (rag: ChatResponse["rag"]) => void;
  onToken?: (token: string) => void;
  onUsage?: (usage: Record<string, unknown>) => void;
  onDone?: (done: Record<string, unknown>) => void;
  onError?: (error: Record<string, unknown>) => void;
};

type WechatStreamHandlers = {
  onRag?: (rag: Record<string, unknown>) => void;
  onToken?: (token: string) => void;
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
    previous_mode: options.previousMode ?? null,
    chat_history: history.map((message) => ({
      role: message.role,
      content: message.content,
      avatarRole: message.avatarRole
    })),
    keep_current_role: options.keepCurrentRole ?? false,
    session_id: options.sessionId,
    rag_enabled: options.ragEnabled,
    rag_top_k: options.ragSettings.chatTopK,
    rag_retrieval_mode: options.ragSettings.retrievalMode,
    rag_min_score: options.ragSettings.minScore,
    web_context: options.webContext ?? "",
    continuation_of_turn_id: options.continuationOfTurnId ?? null,
    partial_reply: options.partialReply ?? ""
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

let _lastSnapshot: ApiSnapshot | null = null;
let _refreshGeneration = 0;

export async function loadApiSnapshot(): Promise<ApiSnapshot> {
  const generation = ++_refreshGeneration;
  const results = await Promise.allSettled([
    requestJson<HealthResponse>("/health"),
    requestJson<RagStatusResponse>("/rag/status"),
    requestJson<{ tools: ToolSpec[] }>("/tools"),
    requestJson<{ runs: WorkflowRunSummary[] }>("/workflows/runs"),
    requestJson<{ sessions: SessionRow[] }>("/sessions"),
    requestJson<RuntimeSettingsResponse>("/runtime/settings"),
    requestJson<MemoryStatusResponse>("/memory"),
    requestJson<WechatStateResponse>("/wechat")
  ]);
  const errors: Record<string, string> = {};
  const read = <T>(index: number, key: string): T | null => {
    const result = results[index];
    if (result.status === "fulfilled") {
      return result.value as T;
    }
    errors[key] = result.reason instanceof Error ? result.reason.message : String(result.reason);
    return null;
  };

  const health = read<HealthResponse>(0, "health");
  const ragStatus = read<RagStatusResponse>(1, "rag");
  const tools = read<{ tools: ToolSpec[] }>(2, "tools");
  const workflows = read<{ runs: WorkflowRunSummary[] }>(3, "workflows");
  const sessions = read<{ sessions: SessionRow[] }>(4, "sessions");
  const runtimeSettings = read<RuntimeSettingsResponse>(5, "settings");
  const memoryStatus = read<MemoryStatusResponse>(6, "memory");
  const wechat = read<WechatStateResponse>(7, "wechat");

  if (generation !== _refreshGeneration) {
    // A newer refresh started while this one was in-flight — discard
    return _lastSnapshot ?? {
      health: null, ragStatus: null, tools: [], workflowRuns: [],
      sessions: [], runtimeSettings: null, memoryStatus: null, wechat: null,
      error: "snapshot refresh superseded", errors: {}
    };
  }

  const next: ApiSnapshot = {
    health,
    ragStatus,
    tools: tools?.tools ?? [],
    workflowRuns: workflows?.runs ?? [],
    sessions: sessions?.sessions ?? [],
    runtimeSettings,
    memoryStatus,
    wechat,
    error: errors.health ?? "",
    errors
  };

  // Preserve last-good data for failed modules
  if (_lastSnapshot) {
    const nameMap: Array<[keyof ApiSnapshot, string]> = [
      ["ragStatus", "rag"], ["tools", "tools"],
      ["workflowRuns", "workflows"], ["sessions", "sessions"],
      ["runtimeSettings", "settings"], ["memoryStatus", "memory"],
      ["wechat", "wechat"],
    ];
    for (const [key, errorKey] of nameMap) {
      if (errors[errorKey] && _lastSnapshot[key] != null) {
        (next as Record<string, unknown>)[key] = _lastSnapshot[key];
      }
    }
  }

  _lastSnapshot = next;
  return next;
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
    body: JSON.stringify(buildWechatPayload(message, options))
  });
}

function buildWechatPayload(
  message: string,
  options: {
    sessionId?: string;
    ragEnabled: boolean;
    chatSettings: ChatSettings;
    ragSettings: RagSettings;
  }
): Record<string, unknown> {
  return {
    message,
    session_id: options.sessionId,
    selected_model: options.chatSettings.selectedModel,
    relationship_mode: options.chatSettings.relationshipMode,
    performance_mode: performanceModeFromContext(options.chatSettings.contextMode),
    rag_enabled: options.ragEnabled,
    rag_top_k: options.ragSettings.chatTopK,
    rag_retrieval_mode: options.ragSettings.retrievalMode,
    rag_min_score: options.ragSettings.minScore
  };
}

export async function sendWechatMessageStream(
  message: string,
  options: {
    sessionId?: string;
    ragEnabled: boolean;
    chatSettings: ChatSettings;
    ragSettings: RagSettings;
  },
  handlers: WechatStreamHandlers = {},
  requestOptions: { signal?: AbortSignal } = {}
): Promise<WechatMessageResponse> {
  const response = await fetch(`${API_BASE_URL}/wechat/message/stream`, {
    method: "POST",
    signal: requestOptions.signal,
    headers: {
      "Content-Type": "application/json",
      ...authHeaders()
    },
    body: JSON.stringify(buildWechatPayload(message, options))
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`${response.status} ${response.statusText}${body ? `: ${body}` : ""}`);
  }
  if (!response.body) {
    return sendWechatMessage(message, options);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let reply = "";
  let sessionId = options.sessionId ?? "";
  let content = "";
  let state: Record<string, unknown> = {};
  let rag: Record<string, unknown> = {};

  const handleMessage = (sseMessage: SseMessage) => {
    if (sseMessage.event === "rag") {
      rag = sseMessage.data.rag && typeof sseMessage.data.rag === "object" ? (sseMessage.data.rag as Record<string, unknown>) : sseMessage.data;
      handlers.onRag?.(rag);
      return;
    }
    if (sseMessage.event === "token") {
      const text = typeof sseMessage.data.text === "string" ? sseMessage.data.text : "";
      reply += text;
      handlers.onToken?.(text);
      return;
    }
    if (sseMessage.event === "done") {
      if (typeof sseMessage.data.session_id === "string") {
        sessionId = sseMessage.data.session_id;
      }
      if (typeof sseMessage.data.reply === "string") {
        reply = sseMessage.data.reply;
      }
      if (typeof sseMessage.data.content === "string") {
        content = sseMessage.data.content;
      }
      if (sseMessage.data.state && typeof sseMessage.data.state === "object") {
        state = sseMessage.data.state as Record<string, unknown>;
      }
      if (sseMessage.data.rag && typeof sseMessage.data.rag === "object") {
        rag = sseMessage.data.rag as Record<string, unknown>;
      }
      handlers.onDone?.(sseMessage.data);
      return;
    }
    if (sseMessage.event === "error") {
      handlers.onError?.(sseMessage.data);
      const detail = typeof sseMessage.data.message === "string" ? sseMessage.data.message : "微信群流式请求失败";
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
    for (const sseMessage of parseSseMessages(parts.join("\n\n"))) {
      handleMessage(sseMessage);
    }
  }

  buffer += decoder.decode();
  for (const sseMessage of parseSseMessages(buffer)) {
    handleMessage(sseMessage);
  }

  return {
    reply,
    content,
    state,
    session_id: sessionId,
    rag
  };
}

export async function searchWechat(keyword: string, maxResults = 10): Promise<WechatSearchResponse> {
  return requestJson<WechatSearchResponse>("/wechat/search", {
    method: "POST",
    body: JSON.stringify({
      keyword,
      max_results: maxResults
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
  return requestJson<NewsSearchResponse>("/news/round", {
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

export async function searchNewsStage(query: string, maxItems = 10): Promise<{ query_text: string; news_items: Array<Record<string, unknown>> }> {
  return requestJson<{ query_text: string; news_items: Array<Record<string, unknown>> }>("/news/search", {
    method: "POST",
    body: JSON.stringify({ query, max_items: maxItems })
  });
}

export async function enrichNewsStage(payload: {
  queryText: string;
  newsItems: Array<Record<string, unknown>>;
  maxArticles?: number;
}): Promise<{ query_text: string; news_items: Array<Record<string, unknown>> }> {
  return requestJson<{ query_text: string; news_items: Array<Record<string, unknown>> }>("/news/enrich", {
    method: "POST",
    body: JSON.stringify({
      query_text: payload.queryText,
      news_items: payload.newsItems,
      max_articles: payload.maxArticles ?? 6
    })
  });
}

export async function digestNewsStage(payload: {
  queryText: string;
  newsItems: Array<Record<string, unknown>>;
  chatSettings: ChatSettings;
}): Promise<{
  query_text: string;
  digest: string;
  source_block: string;
  article_coverage: Record<string, unknown>;
  warnings: string[];
}> {
  return requestJson<{
    query_text: string;
    digest: string;
    source_block: string;
    article_coverage: Record<string, unknown>;
    warnings: string[];
  }>("/news/digest", {
    method: "POST",
    body: JSON.stringify({
      query_text: payload.queryText,
      news_items: payload.newsItems,
      selected_model: payload.chatSettings.selectedModel,
      performance_mode: performanceModeFromContext(payload.chatSettings.contextMode)
    })
  });
}

export async function discussNewsStage(payload: {
  digest: string;
  sourceBlock: string;
  sessionId?: string;
  chatSettings: ChatSettings;
}): Promise<{ discussion: string; group_content: string; session_id: string }> {
  return requestJson<{ discussion: string; group_content: string; session_id: string }>("/news/discuss", {
    method: "POST",
    body: JSON.stringify({
      digest: payload.digest,
      source_block: payload.sourceBlock,
      session_id: payload.sessionId,
      selected_model: payload.chatSettings.selectedModel,
      relationship_mode: payload.chatSettings.relationshipMode,
      performance_mode: performanceModeFromContext(payload.chatSettings.contextMode)
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

export async function loadSessionDetail(sessionId: string): Promise<SessionDetailResponse> {
  return requestJson<SessionDetailResponse>(`/sessions/${encodeURIComponent(sessionId)}`);
}

export async function createNewSession(): Promise<SessionNewResponse> {
  return requestJson<SessionNewResponse>("/sessions/new", { method: "POST" });
}

export async function archiveSession(sessionId: string): Promise<SessionArchiveResponse> {
  return requestJson<SessionArchiveResponse>(`/sessions/${encodeURIComponent(sessionId)}/archive`, { method: "POST" });
}

export async function flushSession(sessionId: string): Promise<{ session_id: string; flushed: boolean }> {
  return requestJson<{ session_id: string; flushed: boolean }>(`/sessions/${encodeURIComponent(sessionId)}/flush`, { method: "POST" });
}

export async function loadRagStatus(): Promise<RagStatusResponse> {
  return requestJson<RagStatusResponse>("/rag/status");
}

export async function uploadDocuments(files: File[], mode: "append" | "rebuild" = "append"): Promise<RagIndexResponse> {
  const formData = new FormData();
  files.forEach((file) => formData.append("files", file));
  return uploadForm<RagIndexResponse>(`/rag/upload?mode=${encodeURIComponent(mode)}`, formData);
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
  handlers: ChatStreamHandlers = {},
  requestOptions: { signal?: AbortSignal } = {}
): Promise<ChatResponse> {
  const response = await fetch(`${API_BASE_URL}/chat/stream`, {
    method: "POST",
    signal: requestOptions.signal,
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

export type LocalKnowledgeInvocation = {
  query: string;
  retrievalMode: RagSettings["retrievalMode"];
  topK: number;
  minScore: number;
  previewId?: string;
};

export async function previewLocalKnowledge(invocation: LocalKnowledgeInvocation): Promise<ToolInvocationResponse> {
  return requestJson<ToolInvocationResponse>("/tools/retrieve_local_knowledge/preview", {
    method: "POST",
    body: JSON.stringify({
      args: {
        query: invocation.query,
        retrieval_mode: invocation.retrievalMode,
        top_k: invocation.topK,
        min_score: invocation.minScore
      }
    })
  });
}

export async function callLocalKnowledge(invocation: LocalKnowledgeInvocation): Promise<ToolInvocationResponse> {
  return requestJson<ToolInvocationResponse>("/tools/retrieve_local_knowledge/call", {
    method: "POST",
    body: JSON.stringify({
      run_id: invocation.previewId,
      args: {
        query: invocation.query,
        retrieval_mode: invocation.retrievalMode,
        top_k: invocation.topK,
        min_score: invocation.minScore
      }
    })
  });
}

export async function loadWorkflowRun(runId: string): Promise<WorkflowRunDetail> {
  const response = await requestJson<{ run: WorkflowRunDetail }>(`/workflows/runs/${encodeURIComponent(runId)}`);
  return response.run;
}

export async function commitTurn(sessionId: string, payload: {
  userInput: string;
  agentReply: string;
  role?: string;
  mode?: string;
  model?: string;
  memoryEnabled?: boolean;
  routeInfo?: Record<string, unknown>;
  ragInfo?: Record<string, unknown>;
  conversationInstruction?: string;
}): Promise<{ session_id: string; committed: boolean; message: string }> {
  return requestJson<{ session_id: string; committed: boolean; message: string }>(`/sessions/${sessionId}/commit-turn`, {
    method: "POST",
    body: JSON.stringify({
      session_id: sessionId,
      user_input: payload.userInput,
      agent_reply: payload.agentReply,
      role: payload.role ?? "auto",
      mode: payload.mode ?? "auto",
      model: payload.model ?? "auto",
      memory_enabled: payload.memoryEnabled ?? false,
      route_info: payload.routeInfo ?? {},
      rag_info: payload.ragInfo ?? {},
      conversation_instruction: payload.conversationInstruction ?? ""
    })
  });
}
