import type {
  ApiSnapshot,
  ChatMessage,
  ChatResponse,
  HealthResponse,
  RagIndexResponse,
  RagQueryResponse,
  RagStatusResponse,
  ToolInvocationResponse,
  ToolSpec,
  WorkflowRunDetail,
  WorkflowRunSummary
} from "./types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

async function requestJson<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      "Content-Type": "application/json",
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
    body: formData
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`${response.status} ${response.statusText}${body ? `: ${body}` : ""}`);
  }
  return (await response.json()) as T;
}

export async function loadApiSnapshot(): Promise<ApiSnapshot> {
  try {
    const [health, ragStatus, tools, workflows] = await Promise.all([
      requestJson<HealthResponse>("/health"),
      requestJson<RagStatusResponse>("/rag/status"),
      requestJson<{ tools: ToolSpec[] }>("/tools"),
      requestJson<{ runs: WorkflowRunSummary[] }>("/workflows/runs")
    ]);
    return {
      health,
      ragStatus,
      tools: tools.tools,
      workflowRuns: workflows.runs,
      error: ""
    };
  } catch (error) {
    return {
      health: null,
      ragStatus: null,
      tools: [],
      workflowRuns: [],
      error: error instanceof Error ? error.message : "API unavailable"
    };
  }
}

export async function loadRagStatus(): Promise<RagStatusResponse> {
  return requestJson<RagStatusResponse>("/rag/status");
}

export async function uploadDocuments(files: File[]): Promise<RagIndexResponse> {
  const formData = new FormData();
  files.forEach((file) => formData.append("files", file));
  return uploadForm<RagIndexResponse>("/rag/upload", formData);
}

export async function queryRag(query: string): Promise<RagQueryResponse> {
  return requestJson<RagQueryResponse>("/rag/query", {
    method: "POST",
    body: JSON.stringify({
      query,
      top_k: 5,
      retrieval_mode: "hybrid"
    })
  });
}

export async function sendChat(
  userInput: string,
  history: ChatMessage[],
  options: { ragEnabled: boolean; sessionId?: string }
): Promise<ChatResponse> {
  return requestJson<ChatResponse>("/chat", {
    method: "POST",
    body: JSON.stringify({
      user_input: userInput,
      selected_role: "auto",
      selected_mode: "auto",
      selected_model: "auto",
      relationship_mode: "standard",
      chat_history: history.map((message) => ({
        role: message.role,
        content: message.content
      })),
      session_id: options.sessionId,
      rag_enabled: options.ragEnabled,
      rag_top_k: 3,
      rag_retrieval_mode: "hybrid"
    })
  });
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
