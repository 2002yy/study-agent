export type HealthResponse = {
  status: string;
  service: string;
  rag_index_exists: boolean;
};

export type RagStatusResponse = {
  index_path: string;
  index_exists: boolean;
  documents: number;
  chunks: number;
  vector_backend: {
    name: string;
    available: boolean;
    detail?: string;
    [key: string]: unknown;
  };
};

export type ChatMessage = {
  role: "user" | "assistant" | "system";
  content: string;
};

export type ChatResponse = {
  reply: string;
  session_id: string;
  route: Record<string, unknown>;
  rag: {
    status: string;
    query: string;
    retrieval_mode: string;
    reason: string;
    context: string;
    sources: string;
    result_count: number;
    results: Array<Record<string, unknown>>;
    debug: Record<string, unknown>;
    attempts: Array<Record<string, unknown>>;
    rewritten_query: string;
  };
};

export type ToolSpec = {
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
  permissions: string[];
  requires_confirmation: boolean;
  enabled: boolean;
};

export type ToolInvocationResponse = {
  tool_name: string;
  status: "preview" | "succeeded" | "failed" | "blocked";
  output: Record<string, unknown>;
  reason: string;
  elapsed_ms: number;
  run_id: string;
};

export type WorkflowRunSummary = {
  run_id: string;
  workflow_name: string;
  status: string;
  started_at: string;
  completed_at: string;
  elapsed_ms: number;
  event_count: number;
};

export type ApiSnapshot = {
  health: HealthResponse | null;
  ragStatus: RagStatusResponse | null;
  tools: ToolSpec[];
  workflowRuns: WorkflowRunSummary[];
  error: string;
};
