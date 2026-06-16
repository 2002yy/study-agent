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

export type ChatSettings = {
  selectedRole: string;
  selectedMode: string;
  selectedModel: string;
  relationshipMode: string;
  contextMode: string;
};

export type RagSettings = {
  retrievalMode: "lexical" | "vector" | "hybrid" | "backend_vector";
  topK: number;
  minScore: number;
  chatTopK: number;
};

export type RuntimeOption = {
  id: string;
  label: string;
  summary?: string;
};

export type RuntimeSettingsResponse = {
  settings: {
    selected_role: string;
    selected_mode: string;
    selected_model: string;
    relationship_mode: string;
    entry_mode: string;
    performance_mode: string;
    memory_mode: string;
    debug_mode: boolean;
    safe_mode: boolean;
    route_mode: string;
    context_mode: string;
    current_version: string;
    active_task: string;
    next_version: string;
    wechat_memory_capture_enabled: boolean;
    wechat_memory_capture_mode: string;
    rag_enabled: boolean;
    rag_retrieval_mode: RagSettings["retrievalMode"];
    rag_top_k: number;
    rag_min_score: number;
  };
  options: {
    roles: RuntimeOption[];
    modes: RuntimeOption[];
    models: RuntimeOption[];
    performance_modes: RuntimeOption[];
    relationship_modes: RuntimeOption[];
    entry_modes: RuntimeOption[];
    memory_modes: string[];
    retrieval_modes: RagSettings["retrievalMode"][];
  };
  runtime_profile: Record<string, unknown>;
  warnings: string[];
};

export type RoleResponse = {
  id: string;
  label: string;
  prompt: string;
  summary: string;
};

export type MemoryFileStatus = {
  name: string;
  path: string;
  exists: boolean;
  size_bytes: number;
  mtime_ns: number;
  preview: string;
};

export type MemoryStatusResponse = {
  writable: boolean;
  memory_mode: string;
  safe_mode: boolean;
  reason: string;
  context_mode: string;
  groups: Record<string, string[]>;
  files: MemoryFileStatus[];
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

export type SessionRow = {
  kind: string;
  name: string;
  path: string;
  size_bytes: number;
  mtime_ns: number;
};

export type ApiSnapshot = {
  health: HealthResponse | null;
  ragStatus: RagStatusResponse | null;
  tools: ToolSpec[];
  workflowRuns: WorkflowRunSummary[];
  sessions: SessionRow[];
  runtimeSettings: RuntimeSettingsResponse | null;
  memoryStatus: MemoryStatusResponse | null;
  error: string;
};
