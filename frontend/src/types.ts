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

export type RagIndexResponse = {
  documents: number;
  chunks: number;
  index_path: string;
};

export type RagChunk = {
  chunk_id?: string;
  source_path?: string;
  title?: string;
  start_line?: number;
  end_line?: number;
  text?: string;
};

export type RagResult = {
  chunk?: RagChunk;
  score?: number;
  matched_terms?: string[];
};

export type RagDebugResult = {
  rank?: number;
  score?: number;
  source_path?: string;
  title?: string;
  line_range?: string;
  matched_terms?: string[];
  score_breakdown?: Record<string, number>;
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
    results: RagResult[];
    debug: {
      results?: RagDebugResult[];
      [key: string]: unknown;
    };
    attempts: Array<Record<string, unknown>>;
    rewritten_query: string;
  };
};

export type RagQueryResponse = {
  query: string;
  retrieval_mode: string;
  result_count: number;
  context: string;
  sources: string;
  results: RagResult[];
  debug: {
    results?: RagDebugResult[];
    [key: string]: unknown;
  };
  evaluation?: Record<string, unknown> | null;
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

export type WorkflowEvent = {
  run_id: string;
  step_id: string;
  event_type: string;
  status: string;
  workflow_name: string;
  message: string;
  data: Record<string, unknown>;
  elapsed_ms: number;
  created_at: string;
  error: string;
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

export type WorkflowRunDetail = Omit<WorkflowRunSummary, "event_count"> & {
  events: WorkflowEvent[];
};

export type ApiSnapshot = {
  health: HealthResponse | null;
  ragStatus: RagStatusResponse | null;
  tools: ToolSpec[];
  workflowRuns: WorkflowRunSummary[];
  error: string;
};
