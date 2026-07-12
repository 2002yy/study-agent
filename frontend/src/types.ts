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
  stages?: Array<{
    name: string;
    status: string;
    documents?: number;
    chunks?: number;
    detail?: string;
    backend?: Record<string, unknown>;
    index_path?: string;
  }>;
  index_version?: number;
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

export type PedagogySummary = {
  mode: string;
  phase: string;
  move: string;
  disclosure_level: number;
};

export type LearningState = {
  protocol: string;
  protocol_version?: number;
  objective: string;
  phase: string;
  learner_claim?: string;
  confirmed_points?: string[];
  unresolved_gap: string;
  attempted_examples?: string[];
  hint_level: number;
  library_facts_given?: string[];
  turn_count: number;
  payload?: Record<string, unknown>;
};

export type WebToolCall = {
  name: string;
  arguments: Record<string, unknown>;
  result: Record<string, unknown>;
};

export type TurnEvidence = {
  pedagogy?: PedagogySummary;
  rag?: ChatResponse["rag"];
  route?: Record<string, unknown>;
};

export type DrawerId = "group" | "news" | "tools" | "sessions" | "memory" | "settings";

export type ChatMessage = {
  role: "user" | "assistant" | "system";
  content: string;
  avatarRole?: string;
  transient?: boolean;
  turnId?: string;
  turnStatus?: string;
  parentTurnId?: string | null;
  evidence?: TurnEvidence;
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
    rag_search_top_k: number;
    rag_chat_top_k: number;
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
  description: string;
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
  latest_section?: string;
  latest_updated_at?: string;
};

export type MemoryUpdate = {
  target: string;
  content: string;
  append?: boolean;
  learner_pending?: boolean;
};

export type MemoryPreviewItem = {
  target: string;
  path: string;
  action: string;
  allowed: boolean;
  preview: string;
};

export type MemoryPreviewResponse = {
  writable: boolean;
  memory_mode: string;
  safe_mode: boolean;
  updates: MemoryPreviewItem[];
};

export type MemoryCommitResponse = {
  writable: boolean;
  results: Array<{
    target: string;
    action: string;
    path: string;
  }>;
  errors?: Array<{
    target: string;
    action: string;
    error: string;
  }>;
};

export type MemoryRunResponse = {
  id: string;
  status: "previewed" | "running" | "succeeded" | "partial" | "failed" | "blocked";
  updates: MemoryUpdate[];
  updates_hash: string;
  preview: MemoryPreviewResponse;
  result: {
    results?: MemoryCommitResponse["results"];
    errors?: NonNullable<MemoryCommitResponse["errors"]>;
  };
  reason: string;
  active_operation_id?: string | null;
  active_operation_started_at?: string | null;
  previewed_at?: string | null;
  completed_at?: string | null;
  version: number;
  created_at: string;
  updated_at: string;
};

export type WechatStateResponse = {
  group_thread_id: string;
  state: Record<string, unknown>;
  content: string;
  unread: string;
  has_unread: boolean;
  started: boolean;
  message_count: number;
  unread_count: number;
  summary: string;
};

export type WechatMessageResponse = {
  reply: string;
  content: string;
  state: Record<string, unknown>;
  session_id: string;
  group_thread_id: string;
  rag: Record<string, unknown>;
  message_count?: number;
  unread_count?: number;
  has_unread?: boolean;
};

export type WechatSearchResult = {
  speaker?: string;
  text?: string;
  line?: number;
  score?: number;
  [key: string]: unknown;
};

export type WechatSearchResponse = {
  keyword: string;
  results: WechatSearchResult[];
};

export type NewsLookupResponse = {
  run_id: string;
  query_text: string;
  news_items: Array<Record<string, unknown>>;
  source_block: string;
  warnings: string[];
};

export type ChatResponse = {
  reply: string;
  session_id: string;
  turn_id?: string | null;
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
    web_tools?: {
      enabled: boolean;
      used: boolean;
      calls: Array<Record<string, unknown>>;
      error?: string;
    };
  };
  pedagogy?: PedagogySummary;
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
  session_id?: string;
  kind: string;
  name: string;
  path: string;
  size_bytes: number;
  mtime_ns: number;
};

export type SessionDetailResponse = {
  session_id: string;
  kind: string;
  path: string;
  messages: ChatMessage[];
  settings: Partial<ChatSettings> & {
    ragEnabled?: boolean;
    ragSettings?: Partial<RagSettings>;
    keepCurrentRole?: boolean;
  };
  route: Record<string, unknown>;
  rag: ChatResponse["rag"] | Record<string, unknown>;
  learning_state: Record<string, unknown>;
  pedagogy: Record<string, unknown>;
  latest_attempted_pedagogy: Record<string, unknown>;
  conversation_instruction: string;
  turns?: Array<{
    turn_id: string;
    status: string;
    parent_turn_id?: string | null;
    operation_id?: string | null;
    user_message: string;
    assistant_message: string;
    role: string;
    mode: string;
    model: string;
    pedagogy_snapshot?: Record<string, unknown>;
  }>;
  raw: string;
};

export type RagRunResponse = {
  id: string;
  kind: "query" | "upload" | "rebuild";
    status: "running" | "completed" | "partial_success" | "failed";
  request: Record<string, unknown>;
  result: Record<string, unknown>;
  error: string;
  index_version: number;
  version: number;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
};

  export type KnowledgeDocument = {
    document_id: string;
    revision_id: string;
  title: string;
  source_path: string;
  file_type: string;
  content_hash: string;
  chunks: number;
  metadata: Record<string, unknown>;
};

export type KnowledgeDocumentListResponse = {
  index_path: string;
  index_exists: boolean;
  index_version: number;
  documents: KnowledgeDocument[];
  chunks: number;
};

export type WebLookupRunResponse = {
  id: string;
  query: string;
  status: "running" | "completed" | "failed";
  items: Array<Record<string, unknown>>;
  source_block: string;
  warnings: string[];
  error: string;
  version: number;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
};

export type ToolRunResponse = {
  id: string;
  tool_name: string;
  args: Record<string, unknown>;
  args_hash: string;
  status: "previewed" | "running" | "succeeded" | "failed" | "blocked";
  preview: Record<string, unknown>;
  result: Record<string, unknown>;
  reason: string;
  elapsed_ms: number;
  active_operation_id: string | null;
  active_operation_started_at: string | null;
  previewed_at: string | null;
  completed_at: string | null;
  version: number;
  created_at: string;
  updated_at: string;
};

export type NewsRunResponse = {
  id: string;
  query: string;
  stage: "created" | "searched" | "enriched" | "enrich_skipped" | "digested" | "discussed";
  status: "running" | "failed" | "completed";
  safe_mode: boolean;
  items: Array<Record<string, unknown>>;
  digest: string;
  source_block: string;
  article_coverage: Record<string, unknown>;
  discussion: string;
  warnings: string[];
  error: string;
  group_thread_id?: string | null;
  active_operation_id?: string | null;
  active_operation_started_at?: string | null;
  stage_started_at?: string | null;
  completed_at?: string | null;
  version: number;
  created_at: string;
  updated_at: string;
};

export type SessionNewResponse = {
  session_id: string;
  settings: Partial<RuntimeSettingsResponse["settings"]>;
};

export type SessionArchiveResponse = {
  session_id: string;
  kind: string;
  path: string;
  archived: boolean;
};

export type ApiSnapshot = {
  health: HealthResponse | null;
  ragStatus: RagStatusResponse | null;
  tools: ToolSpec[];
  workflowRuns: WorkflowRunSummary[];
  sessions: SessionRow[];
  runtimeSettings: RuntimeSettingsResponse | null;
  memoryStatus: MemoryStatusResponse | null;
  wechat: WechatStateResponse | null;
  error: string;
  errors: Record<string, string>;
};

/* Centralized workspace state for stable persistence and cross-UI coordination.
   Should be kept in sync between localStorage, App state, and session lifecycle. */
export type WorkspaceState = {
  singleChatSessionId?: string;
  wechatThreadId?: string;
  newsRunId?: string;
  webLookupRunId?: string;
  singleChatMessages: ChatMessage[];
  chatSettings: ChatSettings;
  ragSettings: RagSettings;
  ragEnabled: boolean;
  keepCurrentRole: boolean;
  conversationInstruction: string;
  lastRoute?: Record<string, unknown>;
  lastRag?: Record<string, unknown>;
  lastSessionId?: string;
};
