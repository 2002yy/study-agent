export type HealthResponse = {
  status: string;
  service: string;
  rag_index_exists: boolean;
};

export type SearchProviderHealthItem = {
  name: string;
  role: "preferred" | "fallback" | "last_fallback";
  enabled: boolean;
  configured: boolean;
  reachable: boolean | null;
  search_capable: boolean | null;
  status: string;
  detail: string;
  endpoint: string;
};

export type SearchProviderHealthResponse = {
  status: "ready" | "degraded" | "unavailable";
  preferred_provider: string;
  probed: boolean;
  checked_at: string;
  providers: SearchProviderHealthItem[];
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
    provider?: string;
    purpose?: string;
    audit_version?: number;
    data_categories?: string[];
    index_path?: string;
  }>;
  index_version?: number;
};

export type RagChunk = {
  chunk_id?: string;
  document_id?: string;
  revision_id?: string;
  metadata?: Record<string, unknown>;
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
  evidence_ids?: string[];
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

export type ExternalDataPolicySnapshot = {
  web_policy: "off" | "ask" | "auto" | string;
  cloud_context_policy: "question_only" | "recent_chat" | "allow_local_evidence" | string;
  task_source_policy: string;
  web_allowed: boolean;
  local_retrieval_allowed: boolean;
  history_allowed: boolean;
  memory_allowed: boolean;
  local_evidence_to_model_allowed: boolean;
  reason: string;
  external_data_audit_version?: number;
  external_calls?: ExternalDataCallAudit[];
  web_search_performed?: boolean;
  history_sent_to_model?: boolean;
  history_message_count?: number;
  learning_state_sent_to_model?: boolean;
  memory_context_sent_to_model?: boolean;
  local_evidence_sent_to_model?: boolean;
  local_evidence_chunk_count?: number;
};

export type ExternalDataCallAudit = {
  call_id: string;
  purpose: string;
  provider: string;
  data_categories: string[];
  data_counts?: Record<string, number>;
  status: string;
  result?: string;
};

export type DrawerId =
  | "sessions"
  | "memory"
  | "settings"
  | "sources"
  | "lab";

export type ChatMessage = {
  role: "user" | "assistant" | "system";
  content: string;
  avatarRole?: string;
  transient?: boolean;
  turnId?: string;
  turnStatus?: string;
  // G12: cancellation lifecycle copy, written only by the cooperative cancel
  // flow. Never rendered for plain aborts/disconnects or restored history.
  cancelNotice?: string;
  parentTurnId?: string | null;
  evidence?: TurnEvidence;
  researchPresentation?: import("./features/answer-ui/researchPresentation").ResearchPresentation;
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
    web_policy?: "off" | "ask" | "auto";
    cloud_context_policy?: "question_only" | "recent_chat" | "allow_local_evidence";
    memory_policy?: "off" | "ask" | "auto";
    deep_research_sensitivity?: "conservative" | "balanced" | "eager";
    attachment_vision_enabled?: boolean;
    enter_to_send?: boolean;
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
    web_policies?: string[];
    cloud_context_policies?: string[];
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
      run_id?: string;
      provider_errors?: string[];
      evidence_status?: "read_backed" | "candidate_only" | "empty" | string;
      candidate_count?: number;
      read_count?: number;
      used_sources?: Array<{
        title?: string;
        url?: string;
        source?: string;
      }>;
    };
    web_context?: {
      used: boolean;
      run_id?: string;
      source: "research_run" | "manual";
    };
    external_data_policy?: ExternalDataPolicySnapshot;
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
    // G16: per-session memory grant persisted by the backend.
    memory_consent_granted?: boolean;
    memory_consent_granted_at?: string | null;
    memory_consent_revoked_at?: string | null;
    webPolicy?: string;
    cloudContextPolicy?: string;
    memoryPolicy?: string;
    [key: string]: unknown;
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
    route_snapshot?: Record<string, unknown>;
    rag_snapshot?: Record<string, unknown>;
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

export type ChatResearchProgress = {
  run_id: string;
  status: "pending" | "running" | "completed" | "partial" | "failed" | "cancelled";
  stage: "planned" | "searching" | "assessing" | "reading" | "synthesizing" | "gating" | "completed" | "failed" | "cancelled";
  provider_status: string;
  stop_reason: string;
  error: string;
  query_attempt_count: number;
  selected_source_count: number;
  candidate_count?: number | null;
  read_count?: number | null;
  cluster_count?: number | null;
  open_critical_gap_count?: number | null;
  active_phase?: string | null;
  gate_status?: string | null;
  version: number;
  // G18 deep-research journey fields (present only for deep runs).
  round?: number | null;
  notes_count?: number | null;
  last_step_kind?: string | null;
  last_step_text?: string | null;
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
  // G12 decision 15: the archive intent is persisted server-side and will
  // execute once the cancelled operation settles (or on restart).
  queued?: boolean;
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
