import {
  Activity,
  AlertTriangle,
  BookOpen,
  BrainCircuit,
  CheckCircle2,
  Database,
  FileText,
  Loader2,
  MemoryStick,
  MessageSquare,
  RefreshCw,
  Settings,
  Upload,
  Wrench
} from "lucide-react";
import { ChangeEvent, FormEvent, useEffect, useRef, useState } from "react";
import {
  archiveSession,
  callLocalKnowledge,
  commitTurn,
  createNewSession,
  createWechatOpening,
  flushSession,
  loadApiSnapshot,
  loadRole,
  loadSessionDetail,
  loadWorkflowRun,
  lookupNews,
  markWechatRead,
  previewLocalKnowledge,
  queryRag,
  resetWechat,
  saveRuntimeSettings,
  sendChatStream,
  sendWechatMessageStream,
  uploadDocuments
} from "./api";
import type { LocalKnowledgeInvocation } from "./api";
import { RoleAvatar } from "./components/RoleAvatar";
import { StatusDot } from "./components/StatusDot";
import { MemoryPanel } from "./features/learning-memory/MemoryPanel";
import { RoadmapPanel } from "./features/migration/RoadmapPanel";
import { SourcesPanel } from "./features/rag/SourcesPanel";
import { RoutePanel } from "./features/route/RoutePanel";
import { SessionsPanel } from "./features/sessions/SessionsPanel";
import { ChatPanel } from "./features/single-chat/ChatPanel";
import { SESSION_STORAGE_KEY, sanitizeSingleChatMessages, seedMessages, toChatHistoryPayload, buildWorkspaceState, serializeWorkspaceState, deserializeWorkspaceState, buildContinuationHistory } from "./features/single-chat/chatHistory";
import { ToolPanel } from "./features/tools/ToolPanel";
import { roleLabel, roleOptions } from "./features/roles/roleCatalog";
import { WechatPanel } from "./features/wechat-workspace/WechatPanel";
import { TimelinePanel } from "./features/workflows/TimelinePanel";
import { displayValue } from "./utils/format";
import type {
  ApiSnapshot,
  ChatMessage,
  ChatResponse,
  ChatSettings,
  NewsLookupResponse,
  NewsSearchResponse,
  RagIndexResponse,
  RagQueryResponse,
  RagSettings,
  RoleResponse,
  SessionDetailResponse,
  ToolInvocationResponse,
  WorkspaceState,
  WorkflowRunDetail
} from "./types";

const INITIAL_SNAPSHOT: ApiSnapshot = {
  health: null,
  ragStatus: null,
  tools: [],
  workflowRuns: [],
  sessions: [],
  runtimeSettings: null,
  memoryStatus: null,
  wechat: null,
  error: "",
  errors: {}
};

const CHAT_SETTINGS_DEFAULTS: ChatSettings = {
  selectedRole: "auto",
  selectedMode: "auto",
  selectedModel: "auto",
  relationshipMode: "standard",
  contextMode: ""
};

const RAG_SETTINGS_DEFAULTS: RagSettings = {
  retrievalMode: "hybrid",
  topK: 5,
  minScore: 0.01,
  chatTopK: 3
};

function createEmptyRag(): ChatResponse["rag"] {
  return {
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
  };
}

function describeRagUploadResult(result: RagIndexResponse): string {
  const vectorStage = result.stages?.find((stage) => stage.name === "vector");
  const base = `已索引 ${result.documents} 个文档、${result.chunks} 个片段`;
  if (!vectorStage) {
    return base;
  }
  if (vectorStage.status === "completed") {
    return `${base}；向量后端已同步`;
  }
  return `${base}；向量后端同步失败：${vectorStage.detail ?? "未知错误"}`;
}

const roleDescriptions: Record<string, string> = {
  auto: "后端根据问题自动选择合适角色。",
  march7: "更轻快、鼓励式的学习伙伴。",
  keqing: "偏执行、判断和推进项目。",
  nahida: "偏概念解释、连接知识脉络。",
  firefly: "偏陪伴、感受整理和收束。"
};

const modeOptions = [
  ["auto", "自动"],
  ["普通", "直接讲解"],
  ["苏格拉底", "苏格拉底"],
  ["费曼", "费曼"],
  ["项目", "项目推进"]
] as const;

const modeDescriptions: Record<string, string> = {
  auto: "根据你当前的学习行为和任务阶段，在直接回答、逐层探究、费曼复述和项目推进之间选择。",
  普通: "直接、完整地回答当前问题；必要时才澄清，不强制进入教学流程。",
  苏格拉底: "你通过持续思考和提问决定学习路径，AI直接回答当前一层，并帮助你逐步深入。",
  费曼: "你用自己的话解释，AI定位理解缺口，补充关键点后引导你重新说明。",
  项目: "围绕当前项目阶段解决实际问题，给出最小修改、实施顺序、验证方式和主要风险。"
};

const modelOptions = [
  ["auto", "自动"],
  ["flash", "Flash"],
  ["pro", "Pro"]
] as const;

const modelDescriptions: Record<string, string> = {
  auto: "按当前性能设置和任务自动选模型。",
  flash: "响应更快，适合日常问答和轻量检索。",
  pro: "质量更高，适合复杂分析、写作和长上下文。"
};

const contextModeOptions = [
  ["", "自动"],
  ["fast", "快速"],
  ["light", "标准"],
  ["deep", "深度"]
] as const;

const contextModeDescriptions: Record<string, string> = {
  "": "沿用后端当前运行档位。",
  fast: "优先速度，减少上下文和输出预算。",
  light: "平衡速度和质量，适合大多数学习对话。",
  deep: "读取更多上下文，适合复杂问题和复盘。"
};

const relationshipOptions = [
  ["standard", "自然"],
  ["warm", "温和"],
  ["close", "贴近"]
] as const;

const relationshipDescriptions: Record<string, string> = {
  standard: "自然克制，保持学习导向。",
  warm: "更鼓励、更柔和，但仍然聚焦任务。",
  close: "更有陪伴感，适合复盘和情绪整理。"
};

const retrievalOptions = [
  ["lexical", "关键词"],
  ["hybrid", "混合"],
  ["vector", "本地向量"],
  ["backend_vector", "向量后端"]
] as const;

const retrievalDescriptions: Record<string, string> = {
  lexical: "按关键词命中，稳定、可解释。",
  hybrid: "关键词和向量结合，通常最稳妥。",
  vector: "使用本地向量语义检索。",
  backend_vector: "调用外部向量后端，取决于后端配置。"
};

function Sidebar({
  snapshot,
  ragEnabled,
  ragUploadMode,
  setRagUploadMode,
  setRagEnabled,
  chatSettings,
  setChatSettings,
  ragSettings,
  setRagSettings,
  onSaveSettings,
  isSavingSettings,
  onLoadRole,
  roleDetail,
  keepCurrentRole,
  setKeepCurrentRole,
  conversationInstruction,
  setConversationInstruction,
  onNewSession,
  isSending,
  refresh,
  onUploadClick,
  uploadState,
  lastChat
}: {
  snapshot: ApiSnapshot;
  ragEnabled: boolean;
  ragUploadMode: "append" | "rebuild";
  setRagUploadMode: (mode: "append" | "rebuild") => void;
  setRagEnabled: (value: boolean) => void;
  chatSettings: ChatSettings;
  setChatSettings: (value: ChatSettings) => void;
  ragSettings: RagSettings;
  setRagSettings: (value: RagSettings) => void;
  onSaveSettings: () => void;
  isSavingSettings: boolean;
  onLoadRole: () => void;
  roleDetail: RoleResponse | null;
  keepCurrentRole: boolean;
  setKeepCurrentRole: (value: boolean) => void;
  conversationInstruction: string;
  setConversationInstruction: (value: string) => void;
  onNewSession: () => void;
  isSending: boolean;
  refresh: () => void;
  onUploadClick: () => void;
  uploadState: string;
  lastChat: ChatResponse | null;
}) {
  const apiTone = snapshot.health?.status === "ok" ? "good" : snapshot.error ? "bad" : "neutral";
  const updateChatSetting = (key: keyof ChatSettings, value: string) => {
    setChatSettings({ ...chatSettings, [key]: value });
  };
  const updateRagSetting = <K extends keyof RagSettings>(key: K, value: RagSettings[K]) => {
    setRagSettings({ ...ragSettings, [key]: value });
  };
  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-mark">
          <BrainCircuit size={22} />
        </div>
        <div>
          <strong>Study Agent</strong>
          <span>本地学习工作台</span>
        </div>
      </div>

      <button className="primary-action" disabled={isSending} onClick={onUploadClick} type="button">
        <Upload size={17} />
        上传资料
      </button>
      <div className="upload-mode">
        <label>
          <input
            checked={ragUploadMode === "append"}
            name="rag-upload-mode"
            onChange={() => setRagUploadMode("append")}
            type="radio"
          />
          添加到现有知识库
        </label>
        <label>
          <input
            checked={ragUploadMode === "rebuild"}
            name="rag-upload-mode"
            onChange={() => setRagUploadMode("rebuild")}
            type="radio"
          />
          重建整个知识库
        </label>
      </div>
      <small className="field-hint">默认追加并按内容去重；重建会用本次文件替换当前索引。</small>
      {uploadState ? <div className="upload-state">{uploadState}</div> : null}

      <nav className="nav-list" aria-label="Workspace navigation">
        <a className="active" href="#chat">
          <MessageSquare size={16} />
          单人对话
        </a>
        <a href="#sources">
          <BookOpen size={16} />
          引用来源
        </a>
        <a href="#timeline">
          <Activity size={16} />
          工作流
        </a>
        <a href="#tools">
          <Wrench size={16} />
          工具
        </a>
        <a href="#memory">
          <MemoryStick size={16} />
          记忆
        </a>
      </nav>

      <section className="side-section">
        <div className="section-title">
          <Database size={15} />
          本地知识库
        </div>
        <div className="metric-row">
          <span>文档数</span>
          <strong>{snapshot.ragStatus?.documents ?? "?"}</strong>
        </div>
        <div className="metric-row">
          <span>片段数</span>
          <strong>{snapshot.ragStatus?.chunks ?? "?"}</strong>
        </div>
        <div className="metric-row">
          <span>向量后端</span>
          <strong>{snapshot.ragStatus?.vector_backend.name ?? "未知"}</strong>
        </div>
      </section>

      <section className="side-section">
        <div className="section-title">
          <Settings size={15} />
          单人学习设置
        </div>
        <label className="field-row">
          <span>角色</span>
          <select disabled={isSending} value={chatSettings.selectedRole} onChange={(event) => updateChatSetting("selectedRole", event.target.value)}>
            {roleOptions.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <small className="field-hint">{roleDescriptions[chatSettings.selectedRole]}</small>
        <div className="role-current">
          <RoleAvatar fallback="assistant" roleId={chatSettings.selectedRole} />
          <div>
            <strong>{roleLabel(chatSettings.selectedRole)}</strong>
            <span>{chatSettings.selectedRole === "auto" ? "自动路由时按回答结果显示头像" : "当前手动指定角色"}</span>
          </div>
        </div>
        <button
          aria-pressed={keepCurrentRole}
          className={`ghost-action compact ${keepCurrentRole ? "active" : ""}`}
          disabled={chatSettings.selectedRole !== "auto" || isSending}
          onClick={() => setKeepCurrentRole(!keepCurrentRole)}
          type="button"
        >
          强制保持当前角色
        </button>
        <small className="field-hint">
          仅在角色为自动时生效。系统默认已在中等/低置信度下自动保持上一角色；开启此项后会强制保持，即使高置信度匹配到其他角色也不切换。
        </small>
        <label className="field-row">
          <span>本会话微调</span>
          <textarea
            className="session-instruction"
            disabled={isSending}
            onChange={(event) => setConversationInstruction(event.target.value)}
            placeholder="例如：不要转交给其他角色，直接回答我的问题。"
            rows={3}
            value={conversationInstruction}
          />
        </label>
        <small className="field-hint">只影响当前会话，不会修改角色原始人设或全局默认。</small>
        <button className="ghost-action compact" disabled={isSending} onClick={onNewSession} type="button">
          新建单人会话
        </button>
        {chatSettings.selectedRole !== "auto" ? (
          <button className="ghost-action compact" onClick={onLoadRole} type="button">
            <BookOpen size={15} />
            查看角色人设
          </button>
        ) : null}
        {roleDetail && roleDetail.id === chatSettings.selectedRole ? (
          <div className="role-preview">
            <strong>{roleDetail.label}</strong>
            <p>{roleDetail.description || roleDetail.summary}</p>
            <details>
              <summary>完整提示词</summary>
              <pre>{roleDetail.prompt}</pre>
            </details>
          </div>
        ) : null}
        <label className="field-row">
          <span>学习模式</span>
          <select disabled={isSending} value={chatSettings.selectedMode} onChange={(event) => updateChatSetting("selectedMode", event.target.value)}>
            {modeOptions.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <small className="field-hint">{modeDescriptions[chatSettings.selectedMode]}</small>
        <label className="field-row">
          <span>模型档位</span>
          <select disabled={isSending} value={chatSettings.selectedModel} onChange={(event) => updateChatSetting("selectedModel", event.target.value)}>
            {modelOptions.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <small className="field-hint">{modelDescriptions[chatSettings.selectedModel]}</small>
        <label className="field-row">
          <span>性能/上下文</span>
          <select disabled={isSending} value={chatSettings.contextMode} onChange={(event) => updateChatSetting("contextMode", event.target.value)}>
            {contextModeOptions.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <small className="field-hint">{contextModeDescriptions[chatSettings.contextMode]}</small>
        <label className="field-row">
          <span>互动氛围</span>
          <select disabled={isSending} value={chatSettings.relationshipMode} onChange={(event) => updateChatSetting("relationshipMode", event.target.value)}>
            {relationshipOptions.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <small className="field-hint">{relationshipDescriptions[chatSettings.relationshipMode]}</small>
        <label className="toggle-row">
          <input checked={ragEnabled} disabled={isSending} onChange={(event) => setRagEnabled(event.target.checked)} type="checkbox" />
          <span>用于聊天回答</span>
        </label>
        <small className="field-hint">开启后，回答会先查本地资料再生成；关闭则更像普通聊天，不引用资料库。</small>
        <label className="field-row">
          <span>检索模式</span>
          <select
            disabled={isSending}
            value={ragSettings.retrievalMode}
            onChange={(event) => updateRagSetting("retrievalMode", event.target.value as RagSettings["retrievalMode"])}
          >
            {retrievalOptions.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <small className="field-hint">{retrievalDescriptions[ragSettings.retrievalMode]}</small>
        <div className="number-grid">
          <label className="field-row compact">
            <span>检索 top_k</span>
            <input
              min={1}
              max={20}
              disabled={isSending}
              onChange={(event) => updateRagSetting("topK", Number(event.target.value))}
              type="number"
              value={ragSettings.topK}
            />
          </label>
          <label className="field-row compact">
            <span>聊天引用</span>
            <input
              disabled={isSending}
              min={1}
              max={20}
              onChange={(event) => updateRagSetting("chatTopK", Number(event.target.value))}
              type="number"
              value={ragSettings.chatTopK}
            />
          </label>
        </div>
        <small className="field-hint">检索 top_k 是单独查来源时最多拿几条；聊天引用是回答时最多塞进上下文的资料条数。</small>
        <label className="field-row">
          <span>最低分</span>
          <input
            min={0}
            disabled={isSending}
            onChange={(event) => updateRagSetting("minScore", Number(event.target.value))}
            step={0.01}
            type="number"
            value={ragSettings.minScore}
          />
        </label>
        <small className="field-hint">最低分越高越严格，来源更少但更稳；不确定时保持默认即可。</small>
        <div className="status-line">
          <StatusDot tone={apiTone} />
          <span>{snapshot.health?.service ?? "API 未连接"}</span>
        </div>
        <button className="primary-action secondary" disabled={isSending || isSavingSettings} onClick={onSaveSettings} type="button">
          {isSavingSettings ? <Loader2 className="spin" size={16} /> : <CheckCircle2 size={16} />}
          设为全局默认
        </button>
        <small className="field-hint">上方设置会立即影响当前会话；这里仅保存为新会话的默认值。</small>
      </section>

      <section className="side-section">
        <div className="section-title">
          <Activity size={15} />
          最近一次回答实际配置
        </div>
        <div className="metric-row">
          <span>实际角色</span>
          <strong>{displayValue(lastChat?.route.role)}</strong>
        </div>
        <div className="metric-row">
          <span>实际模式</span>
          <strong>{displayValue(lastChat?.route.mode)}</strong>
        </div>
        <div className="metric-row">
          <span>实际模型</span>
          <strong>{displayValue(lastChat?.route.model_profile)}</strong>
        </div>
        <div className="metric-row">
          <span>Session</span>
          <strong>{lastChat?.session_id ?? "未开始"}</strong>
        </div>
      </section>

      <button className="ghost-action" onClick={refresh} type="button">
        <RefreshCw size={16} />
        刷新状态
      </button>
    </aside>
  );
}

function Inspector({
  snapshot,
  singleChatSessionId,
  wechatThreadId,
  chatSettings,
  lastChat,
  ragSearch,
  isSearching,
  selectedRun,
  loadingRunId,
  selectRun,
  toolPreview,
  toolCall,
  previewTool,
  callTool,
  isPreviewing,
  isCalling,
  toolCanCall,
  toolCallBlockedReason,
  toolInvocationLabel,
  onRestoreSession,
  onArchiveSession,
  newsResult,
  webLookup,
  useWebLookup,
  setUseWebLookup,
  wechatInput,
  setWechatInput,
  newsQuery,
  setNewsQuery,
  readArticles,
  setReadArticles,
  onWechatOpening,
  onWechatReset,
  onWechatMarkRead,
  onSendWechat,
  onStopWechat,
  onLookupNews,
  onNewsRunStarted,
  onNewsDiscussed,
  isWechatBusy,
  isNewsBusy,
  isSending,
  onMemoryChanged
}: {
  snapshot: ApiSnapshot;
  singleChatSessionId?: string;
  wechatThreadId?: string;
  chatSettings: ChatSettings;
  lastChat: ChatResponse | null;
  ragSearch: RagQueryResponse | null;
  isSearching: boolean;
  selectedRun: WorkflowRunDetail | null;
  loadingRunId: string;
  selectRun: (runId: string) => void;
  toolPreview: ToolInvocationResponse | null;
  toolCall: ToolInvocationResponse | null;
  previewTool: () => void;
  callTool: () => void;
  isPreviewing: boolean;
  isCalling: boolean;
  toolCanCall: boolean;
  toolCallBlockedReason: string;
  toolInvocationLabel: string;
  onRestoreSession: (sessionId: string) => void;
  onArchiveSession: (sessionId: string) => void;
  newsResult: NewsSearchResponse | null;
  webLookup: NewsLookupResponse | null;
  useWebLookup: boolean;
  setUseWebLookup: (value: boolean) => void;
  wechatInput: string;
  setWechatInput: (value: string) => void;
  newsQuery: string;
  setNewsQuery: (value: string) => void;
  readArticles: boolean;
  setReadArticles: (value: boolean) => void;
  onWechatOpening: () => void;
  onWechatReset: () => void;
  onWechatMarkRead: () => void;
  onSendWechat: (event: FormEvent) => void;
  onStopWechat: () => void;
  onLookupNews: () => void;
  onNewsRunStarted: (runId: string) => void;
  onNewsDiscussed: (sessionId: string) => void;
  isWechatBusy: boolean;
  isNewsBusy: boolean;
  isSending: boolean;
  onMemoryChanged: () => Promise<void> | void;
}) {
  return (
    <aside className="inspector">
      <RoutePanel lastChat={lastChat} />
      <WechatPanel
        wechat={snapshot.wechat}
        newsResult={newsResult}
        webLookup={webLookup}
        useWebLookup={useWebLookup}
        setUseWebLookup={setUseWebLookup}
        wechatInput={wechatInput}
        setWechatInput={setWechatInput}
        newsQuery={newsQuery}
        setNewsQuery={setNewsQuery}
        readArticles={readArticles}
        setReadArticles={setReadArticles}
        chatSettings={chatSettings}
        sessionId={wechatThreadId}
        onOpening={onWechatOpening}
        onReset={onWechatReset}
        onMarkRead={onWechatMarkRead}
        onSendWechat={onSendWechat}
        onStopWechat={onStopWechat}
        onLookupNews={onLookupNews}
        onNewsRunStarted={onNewsRunStarted}
        onNewsDiscussed={onNewsDiscussed}
        isWechatBusy={isWechatBusy}
        isNewsBusy={isNewsBusy}
      />
      <SourcesPanel lastChat={lastChat} ragSearch={ragSearch} isSearching={isSearching} />
      <TimelinePanel
        runs={snapshot.workflowRuns}
        selectedRun={selectedRun}
        loadingRunId={loadingRunId}
        onSelectRun={selectRun}
      />
      <ToolPanel
        toolCount={snapshot.tools.length}
        toolPreview={toolPreview}
        toolCall={toolCall}
        previewTool={previewTool}
        callTool={callTool}
        isPreviewing={isPreviewing}
        isCalling={isCalling}
        canCall={toolCanCall}
        callBlockedReason={toolCallBlockedReason}
        invocationLabel={toolInvocationLabel}
      />
      <SessionsPanel sessions={snapshot.sessions} activeSessionId={singleChatSessionId} isSending={isSending} onRestore={onRestoreSession} onArchive={onArchiveSession} />
      <RoadmapPanel />
      <MemoryPanel memoryStatus={snapshot.memoryStatus} onMemoryChanged={onMemoryChanged} />
    </aside>
  );
}

export default function App() {
  const [snapshot, setSnapshot] = useState<ApiSnapshot>(INITIAL_SNAPSHOT);
  const [singleChatMessages, setSingleChatMessages] = useState<ChatMessage[]>(seedMessages);
  const [input, setInput] = useState("");
  const [ragEnabled, setRagEnabled] = useState(true);
  const [chatSettings, setChatSettings] = useState<ChatSettings>(CHAT_SETTINGS_DEFAULTS);
  const [ragSettings, setRagSettings] = useState<RagSettings>(RAG_SETTINGS_DEFAULTS);
  const [keepCurrentRole, setKeepCurrentRole] = useState(false);
  const [conversationInstruction, setConversationInstruction] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [isSavingSettings, setIsSavingSettings] = useState(false);
  const [isPreviewing, setIsPreviewing] = useState(false);
  const [isCalling, setIsCalling] = useState(false);
  const [isSearching, setIsSearching] = useState(false);
  const [singleChatSessionId, setSingleChatSessionId] = useState<string | undefined>();
  const [wechatThreadId, setWechatThreadId] = useState<string | undefined>();
  const [newsRunId, setNewsRunId] = useState<string | undefined>();
  const [lastChat, setLastChat] = useState<ChatResponse | null>(null);
  const [ragSearch, setRagSearch] = useState<RagQueryResponse | null>(null);
  const [toolPreview, setToolPreview] = useState<ToolInvocationResponse | null>(null);
  const [toolCall, setToolCall] = useState<ToolInvocationResponse | null>(null);
  const [previewedInvocation, setPreviewedInvocation] = useState<LocalKnowledgeInvocation | null>(null);
  const [selectedRun, setSelectedRun] = useState<WorkflowRunDetail | null>(null);
  const [roleDetail, setRoleDetail] = useState<RoleResponse | null>(null);
  const [newsResult, setNewsResult] = useState<NewsSearchResponse | null>(null);
  const [webLookup, setWebLookup] = useState<NewsLookupResponse | null>(null);
  const [useWebLookup, setUseWebLookup] = useState(true);
  const [loadingRunId, setLoadingRunId] = useState("");
  const [uploadState, setUploadState] = useState("");
  const [ragUploadMode, setRagUploadMode] = useState<"append" | "rebuild">("append");
  const [wechatInput, setWechatInput] = useState("");
  const [newsQuery, setNewsQuery] = useState("最新新闻 when:1d");
  const [readArticles, setReadArticles] = useState(true);
  const [isWechatBusy, setIsWechatBusy] = useState(false);
  const [isNewsBusy, setIsNewsBusy] = useState(false);
  const [streamRecovery, setStreamRecovery] = useState<{ question: string; reply: string; reason: string } | null>(null);
  const [operationError, setOperationError] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const chatAbortRef = useRef<AbortController | null>(null);
  const wechatAbortRef = useRef<AbortController | null>(null);
  const newsLookupAbortRef = useRef<AbortController | null>(null);
  const chatGenerationRef = useRef(0);
  const wechatGenerationRef = useRef(0);
  const newsGenerationRef = useRef(0);
  const toolGenerationRef = useRef(0);
  const sessionStoragePayloadRef = useRef("");
  const runtimeHydratedRef = useRef(false);
  const sessionSettingsRestoredRef = useRef(false);

  const cancelWorkspaceRuns = () => {
    chatGenerationRef.current++;
    wechatGenerationRef.current++;
    newsGenerationRef.current++;
    toolGenerationRef.current++;
    chatAbortRef.current?.abort();
    wechatAbortRef.current?.abort();
    newsLookupAbortRef.current?.abort();
    setIsSending(false);
    setIsWechatBusy(false);
    setIsNewsBusy(false);
    setIsPreviewing(false);
    setIsCalling(false);
  };

  const activeQuery = input.trim() || lastChat?.rag?.query || "";
  const partialErrors = Object.entries(snapshot.errors ?? {}).filter(([key]) => key !== "health");
  const currentToolInvocation: LocalKnowledgeInvocation = {
    query: activeQuery,
    retrievalMode: ragSettings.retrievalMode,
    topK: ragSettings.chatTopK,
    minScore: ragSettings.minScore
  };
  const toolCanCall = Boolean(
    toolPreview &&
      previewedInvocation &&
      previewedInvocation.query === currentToolInvocation.query &&
      previewedInvocation.retrievalMode === currentToolInvocation.retrievalMode &&
      previewedInvocation.topK === currentToolInvocation.topK &&
      previewedInvocation.minScore === currentToolInvocation.minScore
  );
  const toolCallBlockedReason = !toolPreview
    ? ""
    : toolCanCall
      ? ""
      : "输入或 RAG 参数已变化，请重新预览后再调用。";
  const toolInvocationLabel = previewedInvocation
    ? `${previewedInvocation.query} · ${previewedInvocation.retrievalMode} · top_k=${previewedInvocation.topK} · min_score=${previewedInvocation.minScore}`
    : "";

  const refresh = async () => {
    setSnapshot(await loadApiSnapshot());
  };

  useEffect(() => {
    const saved = window.localStorage.getItem(SESSION_STORAGE_KEY);
    if (saved) {
      try {
        const parsed = JSON.parse(saved) as {
          messages?: ChatMessage[];
          singleChatMessages?: ChatMessage[];
          sessionId?: string;
          singleChatSessionId?: string;
          wechatThreadId?: string;
          newsRunId?: string;
          chatSettings?: ChatSettings;
          ragSettings?: RagSettings;
          ragEnabled?: boolean;
          keepCurrentRole?: boolean;
          conversationInstruction?: string;
          lastRoute?: Record<string, unknown>;
          lastRag?: Record<string, unknown>;
          lastSessionId?: string;
        };
        const restoredWorkspace = buildWorkspaceState(parsed);
        const restoredMessages = parsed.singleChatMessages ?? parsed.messages ?? restoredWorkspace.singleChatMessages;
        setSingleChatMessages(sanitizeSingleChatMessages(restoredMessages));
        if (restoredWorkspace.singleChatSessionId) {
          setSingleChatSessionId(restoredWorkspace.singleChatSessionId);
        }
        if (restoredWorkspace.wechatThreadId) {
          setWechatThreadId(restoredWorkspace.wechatThreadId);
        }
        if (restoredWorkspace.newsRunId) {
          setNewsRunId(restoredWorkspace.newsRunId);
        }
        if (parsed.lastRoute && Object.keys(parsed.lastRoute).length) {
          const restoredRoute = parsed.lastRoute as ChatResponse["route"];
          const restoredRag = (parsed.lastRag && Object.keys(parsed.lastRag).length ? parsed.lastRag : createEmptyRag()) as ChatResponse["rag"];
          const lastAssistant = sanitizeSingleChatMessages(restoredMessages)
            .filter((m) => m.role === "assistant" && !m.transient)
            .pop();
          setLastChat({
            reply: lastAssistant?.content ?? "",
            session_id: parsed.lastSessionId ?? restoredWorkspace.singleChatSessionId ?? "restored",
            route: restoredRoute,
            rag: restoredRag,
          });
        }
        if (parsed.chatSettings) {
          sessionSettingsRestoredRef.current = true;
          setChatSettings({ ...CHAT_SETTINGS_DEFAULTS, ...parsed.chatSettings });
        }
        if (parsed.ragSettings) {
          sessionSettingsRestoredRef.current = true;
          setRagSettings({ ...RAG_SETTINGS_DEFAULTS, ...parsed.ragSettings });
        }
        if (typeof parsed.ragEnabled === "boolean") {
          sessionSettingsRestoredRef.current = true;
          setRagEnabled(parsed.ragEnabled);
        }
        if (typeof parsed.keepCurrentRole === "boolean") {
          setKeepCurrentRole(parsed.keepCurrentRole);
        }
        if (typeof parsed.conversationInstruction === "string") {
          setConversationInstruction(parsed.conversationInstruction);
        }
      } catch {
        window.localStorage.removeItem(SESSION_STORAGE_KEY);
      }
    }
    void refresh();
  }, []);

  useEffect(() => {
    const settings = snapshot.runtimeSettings?.settings;
    if (!settings || runtimeHydratedRef.current) {
      return;
    }
    runtimeHydratedRef.current = true;
    if (sessionSettingsRestoredRef.current) {
      return;
    }
    const visibleMode = modeOptions.some(([value]) => value === settings.selected_mode)
      ? settings.selected_mode
      : "auto";
    setChatSettings({
      selectedRole: settings.selected_role,
      selectedMode: visibleMode,
      selectedModel: settings.selected_model,
      relationshipMode: settings.relationship_mode,
      contextMode: settings.context_mode === "fast" || settings.context_mode === "light" || settings.context_mode === "deep"
        ? settings.context_mode
        : ""
    });
    setRagEnabled(settings.rag_enabled);
    setRagSettings({
      retrievalMode: settings.rag_retrieval_mode,
      topK: settings.rag_search_top_k ?? settings.rag_top_k,
      chatTopK: settings.rag_chat_top_k ?? settings.rag_top_k,
      minScore: settings.rag_min_score
    });
  }, [snapshot.runtimeSettings]);

  useEffect(() => {
    const payload = serializeWorkspaceState({
      singleChatMessages,
      singleChatSessionId,
      wechatThreadId,
      newsRunId,
      chatSettings,
      ragSettings,
      ragEnabled,
      keepCurrentRole,
      conversationInstruction,
      lastRoute: lastChat?.route ?? undefined,
      lastRag: lastChat?.rag ?? undefined,
      lastSessionId: lastChat?.session_id ?? undefined,
    });
    sessionStoragePayloadRef.current = payload;
    const timeout = window.setTimeout(() => {
      window.localStorage.setItem(SESSION_STORAGE_KEY, payload);
    }, isSending ? 800 : 200);
    return () => window.clearTimeout(timeout);
  }, [singleChatMessages, singleChatSessionId, wechatThreadId, newsRunId, chatSettings, ragSettings, ragEnabled, keepCurrentRole, conversationInstruction, lastChat, isSending]);

  useEffect(() => {
    const flushSessionStorage = () => {
      if (document.visibilityState === "hidden" && sessionStoragePayloadRef.current) {
        window.localStorage.setItem(SESSION_STORAGE_KEY, sessionStoragePayloadRef.current);
      }
    };
    document.addEventListener("visibilitychange", flushSessionStorage);
    return () => document.removeEventListener("visibilitychange", flushSessionStorage);
  }, []);

  useEffect(() => {
    let cancelled = false;
    const roleId = chatSettings.selectedRole;
    if (roleId === "auto") {
      setRoleDetail(null);
      return () => {
        cancelled = true;
      };
    }
    setRoleDetail(null);
    void loadRole(roleId)
      .then((detail) => {
        if (!cancelled) {
          setRoleDetail(detail);
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setRoleDetail({
            id: roleId,
            label: roleId,
            prompt: "",
            summary: error instanceof Error ? error.message : "角色读取失败",
            description: error instanceof Error ? error.message : "角色读取失败"
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [chatSettings.selectedRole]);


  const sendSingleChat = async (question: string, historyBase = singleChatMessages, extraOpts: { continuationOfTurnId?: string; partialReply?: string; turnId?: string } = {}) => {
    if (!question || isSending) {
      return;
    }
    const generationId = ++chatGenerationRef.current;
    const isContinuation = Boolean(extraOpts.continuationOfTurnId);
    const nextMessages: ChatMessage[] = isContinuation
      ? [...historyBase]
      : [...historyBase, { role: "user", content: question, avatarRole: "user" }];
    const userIndex = isContinuation ? -1 : nextMessages.length - 1;
    const assistantIndex = nextMessages.length;
    setSingleChatMessages([...nextMessages, { role: "assistant", content: "", avatarRole: "auto" }]);
    setInput("");
    setStreamRecovery(null);
    setOperationError("");
    setIsSending(true);
    setRagSearch(null);
    const abortController = new AbortController();
    chatAbortRef.current = abortController;
    let streamedReply = "";
    let streamedRoute: Record<string, unknown> = {};
    let streamedRag: ChatResponse["rag"] | null = null;
    const shouldConsumeWebLookup = useWebLookup && Boolean(webLookup?.source_block);
    try {
      const response = await sendChatStream(
        question,
        toChatHistoryPayload(historyBase),
        {
          ragEnabled,
          sessionId: singleChatSessionId,
          chatSettings,
          ragSettings,
          keepCurrentRole,
          previousMode: typeof lastChat?.route?.mode === "string" ? String(lastChat.route.mode) : undefined,
          conversationInstruction,
          webContext: shouldConsumeWebLookup ? webLookup?.source_block : "",
          continuationOfTurnId: extraOpts.continuationOfTurnId,
          partialReply: extraOpts.partialReply ?? "",
          turnId: extraOpts.turnId
        },
        {
          onSession: (sid) => {
            if (chatGenerationRef.current !== generationId) return;
            setSingleChatSessionId(sid);
          },
          onRoute: (route) => {
            if (chatGenerationRef.current !== generationId) return;
            streamedRoute = route;
            setLastChat((current) => ({
              reply: current?.reply ?? streamedReply,
              session_id: current?.session_id ?? singleChatSessionId ?? "streaming",
              route,
              rag: current?.rag ?? createEmptyRag()
            }));
            setSingleChatMessages((current) =>
              current.map((message, index) =>
                index === assistantIndex ? { ...message, avatarRole: String(route.role ?? "auto") } : message
              )
            );
          },
          onRag: (rag) => {
            if (chatGenerationRef.current !== generationId) return;
            streamedRag = rag;
            setLastChat((current) => ({
              reply: current?.reply ?? streamedReply,
              session_id: current?.session_id ?? singleChatSessionId ?? "streaming",
              route: current?.route ?? {},
              rag
            }));
          },
          onToken: (token) => {
            if (chatGenerationRef.current !== generationId) return;
            streamedReply += token;
            setSingleChatMessages((current) =>
              current.map((message, index) =>
                index === assistantIndex ? { ...message, content: `${message.content}${token}` } : message
              )
            );
            setLastChat((current) => (current ? { ...current, reply: streamedReply } : current));
          },
          onDone: (done) => {
            if (wechatGenerationRef.current !== generationId) return;
            if (typeof done.session_id === "string") {
              setSingleChatSessionId(done.session_id);
            }
          }
        },
        { signal: abortController.signal }
      );
      if (wechatGenerationRef.current !== generationId) return;
      setSingleChatSessionId(response.session_id);
      setLastChat(response);
      setOperationError("");
      if (shouldConsumeWebLookup) {
        setUseWebLookup(false);
      }
      setSingleChatMessages((current) =>
        current.map((message, index) =>
          index === assistantIndex
            ? { ...message, content: response.reply, avatarRole: String(response.route.role ?? "auto") }
            : message
        )
      );
      await refresh();
    } catch (error) {
      if (chatGenerationRef.current !== generationId) return;
      const isAbort = error instanceof DOMException && error.name === "AbortError";
      const message = isAbort ? "已停止生成" : error instanceof Error ? error.message : "聊天请求失败";
      const preserved = streamedReply
        ? `${streamedReply}\n\n---\n生成中断：${message}`
        : `生成中断：${message}`;
      setStreamRecovery({ question, reply: streamedReply, reason: message });
      if (!isAbort) {
        setOperationError(`聊天请求失败：${message}`);
      }
      // Attempt to persist partial reply to session log on interrupt/error
      if (streamedReply && singleChatSessionId) {
        try {
          await commitTurn(singleChatSessionId, {
            userInput: question,
            agentReply: streamedReply,
            role: String(streamedRoute.role ?? lastChat?.route?.role ?? "auto"),
            mode: typeof streamedRoute.mode === "string" ? String(streamedRoute.mode) : typeof lastChat?.route?.mode === "string" ? String(lastChat.route.mode) : "auto",
            model: typeof streamedRoute.model_profile === "string" ? String(streamedRoute.model_profile) : typeof lastChat?.route?.model_profile === "string" ? String(lastChat.route.model_profile) : "auto",
            memoryEnabled: ragEnabled,
            routeInfo: Object.keys(streamedRoute).length ? streamedRoute : (lastChat?.route ?? {}),
            ragInfo: streamedRag ?? lastChat?.rag ?? {},
            conversationInstruction,
          });
        } catch {
          // Best-effort; don't surface commit failure to user
        }
      }
      setSingleChatMessages((current) =>
        current.map((item, index) =>
          index === userIndex
            ? { ...item, transient: true }
            : index === assistantIndex
              ? { ...item, avatarRole: item.avatarRole ?? "auto", content: preserved, transient: true }
              : item
        )
      );
    } finally {
      if (chatAbortRef.current === abortController) {
        chatAbortRef.current = null;
      }
      setIsSending(false);
    }
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    await sendSingleChat(input.trim());
  };

  const stopChatGeneration = () => {
    chatAbortRef.current?.abort();
  };

  const stopWechatGeneration = () => {
    wechatAbortRef.current?.abort();
  };

  const retryInterruptedChat = async () => {
    if (!streamRecovery || isSending) {
      return;
    }
    const retryQuestion = streamRecovery.question;
    const trimmedHistory = singleChatMessages.filter((message, index, messages) => {
      const nextMessage = messages[index + 1];
      const previousMessage = messages[index - 1];
      const isInterruptedUser =
        message.role === "user" &&
        message.transient &&
        message.content === retryQuestion &&
        nextMessage?.role === "assistant" &&
        nextMessage.transient;
      const isInterruptedAssistant =
        message.role === "assistant" &&
        message.transient &&
        previousMessage?.role === "user" &&
        previousMessage.content === retryQuestion;
      return !isInterruptedUser && !isInterruptedAssistant;
    });
    await sendSingleChat(retryQuestion, trimmedHistory);
  };

  const continueInterruptedChat = async () => {
    if (!streamRecovery?.reply || isSending) {
      return;
    }
    const continuationHistory = buildContinuationHistory(singleChatMessages, streamRecovery);
    const turnId = `turn-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
    setStreamRecovery(null);
    await sendSingleChat(streamRecovery.question, continuationHistory, {
      continuationOfTurnId: streamRecovery.question,
      partialReply: streamRecovery.reply,
      turnId,
    });
  };

  const copyInterruptedReply = async () => {
    if (!streamRecovery?.reply) {
      return;
    }
    await navigator.clipboard.writeText(streamRecovery.reply);
  };

  const searchSources = async () => {
    if (!activeQuery || isSearching) {
      return;
    }
    setIsSearching(true);
    setOperationError("");
    try {
      setRagSearch(await queryRag(activeQuery, ragSettings));
    } catch (error) {
      setRagSearch(null);
      setOperationError(`本地资料检索失败：${error instanceof Error ? error.message : "来源检索失败"}`);
    } finally {
      setIsSearching(false);
    }
  };

  const previewTool = async () => {
    const generationId = ++toolGenerationRef.current;
    setIsPreviewing(true);
    setToolCall(null);
    const invocation = { ...currentToolInvocation };
    try {
      const response = await previewLocalKnowledge(invocation);
      if (wechatGenerationRef.current !== generationId) return;
      setToolPreview(response);
      setPreviewedInvocation({ ...invocation, previewId: response.run_id });
    } catch (error) {
      if (wechatGenerationRef.current !== generationId) return;
      setPreviewedInvocation(null);
      setToolPreview({
        tool_name: "retrieve_local_knowledge",
        status: "failed",
        output: {},
        reason: error instanceof Error ? error.message : "预览失败",
        elapsed_ms: 0,
        run_id: ""
      });
    } finally {
      if (toolGenerationRef.current === generationId) {
        setIsPreviewing(false);
      }
    }
  };

  const saveSettings = async () => {
    setIsSavingSettings(true);
    setOperationError("");
    try {
      const response = await saveRuntimeSettings({
        selected_role: chatSettings.selectedRole,
        selected_mode: chatSettings.selectedMode,
        selected_model: chatSettings.selectedModel,
        relationship_mode: chatSettings.relationshipMode,
        performance_mode:
          chatSettings.contextMode === "fast"
            ? "fast"
            : chatSettings.contextMode === "deep"
              ? "deep"
              : chatSettings.contextMode === "light"
                ? "standard"
                : undefined,
        rag_enabled: ragEnabled,
        rag_retrieval_mode: ragSettings.retrievalMode,
        rag_search_top_k: ragSettings.topK,
        rag_chat_top_k: ragSettings.chatTopK,
        rag_min_score: ragSettings.minScore
      });
      setSnapshot((current) => ({ ...current, runtimeSettings: response }));
      setOperationError("");
      await refresh();
    } catch (error) {
      setOperationError(`设置保存失败：${error instanceof Error ? error.message : "设置保存失败"}`);
    } finally {
      setIsSavingSettings(false);
    }
  };

  const showRole = async () => {
    if (chatSettings.selectedRole === "auto") {
      setRoleDetail(null);
      return;
    }
    try {
      setRoleDetail(await loadRole(chatSettings.selectedRole));
    } catch (error) {
      setRoleDetail({
        id: chatSettings.selectedRole,
        label: chatSettings.selectedRole,
        prompt: "",
        summary: error instanceof Error ? error.message : "角色读取失败",
        description: error instanceof Error ? error.message : "角色读取失败"
      });
    }
  };

  const callTool = async () => {
    if (!previewedInvocation || !toolCanCall || isCalling) {
      return;
    }
    const generationId = ++toolGenerationRef.current;
    setIsCalling(true);
    try {
      const result = await callLocalKnowledge(previewedInvocation);
      if (wechatGenerationRef.current !== generationId) return;
      setToolCall(result);
      await refresh();
      if (result.run_id) {
        await selectRun(result.run_id);
      }
    } catch (error) {
      if (wechatGenerationRef.current !== generationId) return;
      setToolCall({
        tool_name: "retrieve_local_knowledge",
        status: "failed",
        output: {},
        reason: error instanceof Error ? error.message : "调用失败",
        elapsed_ms: 0,
        run_id: ""
      });
    } finally {
      if (toolGenerationRef.current === generationId) {
        setIsCalling(false);
      }
    }
  };

  const handleWechatOpening = async () => {
    if (isWechatBusy) {
      return;
    }
    const messageCount = snapshot.wechat?.message_count ?? 0;
    if (messageCount > 0) {
      setOperationError("群聊已有历史内容。生成开场会覆盖当前群聊，请先使用「新群聊」归档旧内容后再生成开场。");
      return;
    }
    setIsWechatBusy(true);
    setOperationError("");
    try {
      const wechat = await createWechatOpening(chatSettings);
      setSnapshot((current) => ({ ...current, wechat }));
    } catch (error) {
      setOperationError(`微信群开场生成失败：${error instanceof Error ? error.message : "群聊开场生成失败"}`);
    } finally {
      setIsWechatBusy(false);
    }
  };

  const handleWechatReset = async () => {
    if (isWechatBusy) {
      return;
    }
    const messageCount = snapshot.wechat?.message_count ?? 0;
    const ok = window.confirm(
      messageCount > 0
        ? `当前群聊有 ${messageCount} 条消息，将先归档再创建新群聊。继续吗？`
        : "创建一个新的空群聊？"
    );
    if (!ok) {
      return;
    }
    setIsWechatBusy(true);
    setOperationError("");
    try {
      const wechat = await resetWechat();
      setWechatThreadId(undefined);
      setNewsRunId(undefined);
      setNewsResult(null);
      setSnapshot((current) => ({ ...current, wechat }));
    } catch (error) {
      setOperationError(`新群聊创建失败：${error instanceof Error ? error.message : "新群聊创建失败"}`);
    } finally {
      setIsWechatBusy(false);
    }
  };

  const handleWechatMarkRead = async () => {
    try {
      const wechat = await markWechatRead(wechatThreadId);
      setSnapshot((current) => ({ ...current, wechat }));
      setOperationError("");
    } catch (error) {
      setOperationError(`标记已读失败：${error instanceof Error ? error.message : "标记已读失败"}`);
    }
  };

  const handleSendWechat = async (event: FormEvent) => {
    event.preventDefault();
    const message = wechatInput.trim();
    if (!message || isWechatBusy) {
      return;
    }
    const baseWechat = snapshot.wechat;
    const generationId = ++wechatGenerationRef.current;
    setIsWechatBusy(true);
    setOperationError("");
    const abortController = new AbortController();
    wechatAbortRef.current = abortController;
    try {
      const baseContent = baseWechat?.content ?? "";
      let streamedReply = "";
      const pendingContent = `${baseContent}${baseContent.trim() ? "\n\n" : ""}【用户】\n${message}\n\n【群聊】\n她们正在输入…`;
      if (baseWechat) {
        setSnapshot((current) => ({
          ...current,
          wechat: {
            ...baseWechat,
            content: pendingContent,
            message_count: baseWechat.message_count + 1
          }
        }));
      }
      const response = await sendWechatMessageStream(message, {
        sessionId: wechatThreadId,
        ragEnabled,
        chatSettings,
        ragSettings
      }, {
        onToken: (token) => {
          if (wechatGenerationRef.current !== generationId) return;
          streamedReply += token;
          if (!baseWechat) {
            return;
          }
          setSnapshot((current) => ({
            ...current,
            wechat: current.wechat
              ? {
                  ...current.wechat,
                  content: `${baseContent}${baseContent.trim() ? "\n\n" : ""}【用户】\n${message}\n\n${streamedReply || "【群聊】\n她们正在输入…"}`
                }
              : current.wechat
          }));
        }
      }, { signal: abortController.signal });
      if (wechatGenerationRef.current !== generationId) return;
      setWechatThreadId(response.session_id);
      setWechatInput("");
      setSnapshot((current) => ({
        ...current,
        wechat: current.wechat
          ? {
              ...current.wechat,
              content: response.content,
              state: response.state,
              message_count: response.message_count ?? Math.max(current.wechat.message_count, (response.content.match(/【/g) ?? []).length)
            }
          : current.wechat
      }));
      await refresh();
    } catch (error) {
      if (wechatGenerationRef.current !== generationId) return;
      const isAbort = error instanceof DOMException && error.name === "AbortError";
      const message = isAbort ? "已停止生成" : error instanceof Error ? error.message : "群聊发送失败";
      // Rollback optimistic UI to base state
      setSnapshot((current) => ({
        ...current,
        wechat: baseWechat
          ? {
              ...baseWechat,
              content: `${baseWechat.content}\n\n【用户】\n${message}\n\n---\n发送失败：${message} [可重试]`
            }
          : baseWechat
      }));
      setOperationError(`微信群回复生成失败：${message}`);
    } finally {
      if (wechatAbortRef.current === abortController) {
        wechatAbortRef.current = null;
      }
      if (wechatGenerationRef.current === generationId) {
        setIsWechatBusy(false);
      }
    }
  };

  const handleLookupNews = async () => {
    const query = newsQuery.trim();
    if (!query || isNewsBusy) {
      return;
    }
    const generationId = ++newsGenerationRef.current;
    const abortController = new AbortController();
    newsLookupAbortRef.current?.abort();
    newsLookupAbortRef.current = abortController;
    setIsNewsBusy(true);
    setOperationError("");
    try {
      const result = await lookupNews(query, 8, { signal: abortController.signal });
      if (newsGenerationRef.current !== generationId) return;
      setWebLookup(result);
      setUseWebLookup(true);
      setOperationError("");
    } catch (error) {
      if (newsGenerationRef.current !== generationId || (error instanceof DOMException && error.name === "AbortError")) return;
      setOperationError(`联网搜索失败：${error instanceof Error ? error.message : "联网搜索失败"}`);
    } finally {
      if (newsLookupAbortRef.current === abortController) {
        newsLookupAbortRef.current = null;
      }
      if (newsGenerationRef.current === generationId) {
        setIsNewsBusy(false);
      }
    }
  };

  const selectRun = async (runId: string) => {
    setLoadingRunId(runId);
    try {
      setSelectedRun(await loadWorkflowRun(runId));
    } finally {
      setLoadingRunId("");
    }
  };

  const applySessionDetail = (detail: SessionDetailResponse) => {
    const restoredMessages = detail.messages.filter((message) => message.role === "user" || message.role === "assistant");
    const restoredSettings = detail.settings ?? {};
    const restoredRagSettings = restoredSettings.ragSettings ?? {};
    const hasFullSettings = (
      typeof restoredSettings.selectedRole === "string"
      || typeof restoredSettings.selectedMode === "string"
      || typeof restoredSettings.relationshipMode === "string"
    );
    const nextChatSettings: ChatSettings = hasFullSettings
      ? {
          selectedRole: typeof restoredSettings.selectedRole === "string" ? restoredSettings.selectedRole : CHAT_SETTINGS_DEFAULTS.selectedRole,
          selectedMode: typeof restoredSettings.selectedMode === "string" ? restoredSettings.selectedMode : CHAT_SETTINGS_DEFAULTS.selectedMode,
          selectedModel: typeof restoredSettings.selectedModel === "string" ? restoredSettings.selectedModel : CHAT_SETTINGS_DEFAULTS.selectedModel,
          relationshipMode: typeof restoredSettings.relationshipMode === "string" ? restoredSettings.relationshipMode : CHAT_SETTINGS_DEFAULTS.relationshipMode,
          contextMode: typeof restoredSettings.contextMode === "string" ? restoredSettings.contextMode : CHAT_SETTINGS_DEFAULTS.contextMode,
        }
      : chatSettings;
    const nextRagSettings: RagSettings = typeof restoredSettings.ragEnabled === "boolean"
      ? { ...RAG_SETTINGS_DEFAULTS, ...restoredRagSettings }
      : ragSettings;
    const lastAssistant = [...restoredMessages].reverse().find((message) => message.role === "assistant");
    const restoredRoute = detail.route ?? {};
    const restoredRag = detail.rag && Object.keys(detail.rag).length ? (detail.rag as ChatResponse["rag"]) : createEmptyRag();

    setSingleChatMessages(restoredMessages.length ? restoredMessages : seedMessages);
    setSingleChatSessionId(detail.session_id);
    setChatSettings(nextChatSettings);
    setRagSettings(nextRagSettings);
    if (typeof restoredSettings.ragEnabled === "boolean") {
      setRagEnabled(restoredSettings.ragEnabled);
    }
    if (typeof restoredSettings.keepCurrentRole === "boolean") {
      setKeepCurrentRole(restoredSettings.keepCurrentRole);
    }
    setConversationInstruction(detail.conversation_instruction ?? "");
    setLastChat(
      Object.keys(restoredRoute).length || lastAssistant
        ? {
            reply: lastAssistant?.content ?? "",
            session_id: detail.session_id,
            route: restoredRoute,
            rag: restoredRag
          }
        : null
    );
    setRagSearch(null);
    setNewsResult(null);
    setWebLookup(null);
    setUseWebLookup(false);
    setStreamRecovery(null);
    setInput("");
    setToolPreview(null);
    setToolCall(null);
    setPreviewedInvocation(null);
    setSelectedRun(null);
  };

  const restoreSession = async (restoredSessionId: string) => {
    setOperationError("");
    cancelWorkspaceRuns();
    try {
      const detail = await loadSessionDetail(restoredSessionId);
      applySessionDetail(detail);
      setOperationError("");
    } catch (error) {
      setOperationError(`会话恢复失败：${error instanceof Error ? error.message : "会话恢复失败"}`);
    }
  };

  const archiveCurrentSession = async (targetSessionId: string) => {
    setOperationError("");
    cancelWorkspaceRuns();
    const isArchivingActive = targetSessionId === singleChatSessionId;
    try {
      await archiveSession(targetSessionId);
      if (isArchivingActive) {
        const created = await createNewSession();
        setSingleChatSessionId(created.session_id);
        setSingleChatMessages(seedMessages);
        setInput("");
        setLastChat(null);
        setRagSearch(null);
        setToolPreview(null);
        setToolCall(null);
        setPreviewedInvocation(null);
        setStreamRecovery(null);
        setConversationInstruction("");
      }
      await refresh();
    } catch (error) {
      setOperationError(`会话归档失败：${error instanceof Error ? error.message : "会话归档失败"}`);
    }
  };

  const startNewSession = async () => {
    setOperationError("");
    cancelWorkspaceRuns();
    try {
      if (singleChatSessionId) {
        try {
          const detail = await loadSessionDetail(singleChatSessionId);
          const hasMessages = detail.messages.some(
            (message) => message.role === "user" || message.role === "assistant"
          );
          if (hasMessages) {
            await archiveSession(singleChatSessionId);
          }
        } catch {
          // Session not on disk yet (still in memory) — flush via API
          try {
            await flushSession(singleChatSessionId);
          } catch {
            // Best-effort; proceed even if flush fails
          }
        }
      }
      const created = await createNewSession();
      setSingleChatSessionId(created.session_id);
      setSingleChatMessages(seedMessages);
      setInput("");
      setLastChat(null);
      setRagSearch(null);
      setToolPreview(null);
      setToolCall(null);
      setPreviewedInvocation(null);
      setStreamRecovery(null);
      setNewsResult(null);
      setWebLookup(null);
      setUseWebLookup(false);
      setConversationInstruction("");
      setToolPreview(null);
      setToolCall(null);
      setPreviewedInvocation(null);
      setSelectedRun(null);
      const settings = created.settings ?? {};
      setChatSettings({
        ...CHAT_SETTINGS_DEFAULTS,
        selectedRole: typeof settings.selected_role === "string" ? settings.selected_role : CHAT_SETTINGS_DEFAULTS.selectedRole,
        selectedMode: typeof settings.selected_mode === "string" ? settings.selected_mode : CHAT_SETTINGS_DEFAULTS.selectedMode,
        selectedModel: typeof settings.selected_model === "string" ? settings.selected_model : CHAT_SETTINGS_DEFAULTS.selectedModel,
        relationshipMode: typeof settings.relationship_mode === "string" ? settings.relationship_mode : CHAT_SETTINGS_DEFAULTS.relationshipMode,
        contextMode: typeof settings.context_mode === "string" ? settings.context_mode : CHAT_SETTINGS_DEFAULTS.contextMode
      });
      setRagEnabled(typeof settings.rag_enabled === "boolean" ? settings.rag_enabled : true);
      setRagSettings({
        ...RAG_SETTINGS_DEFAULTS,
        retrievalMode: settings.rag_retrieval_mode ?? RAG_SETTINGS_DEFAULTS.retrievalMode,
        topK: settings.rag_search_top_k ?? settings.rag_top_k ?? RAG_SETTINGS_DEFAULTS.topK,
        chatTopK: settings.rag_chat_top_k ?? settings.rag_top_k ?? RAG_SETTINGS_DEFAULTS.chatTopK,
        minScore: settings.rag_min_score ?? RAG_SETTINGS_DEFAULTS.minScore
      });
      setKeepCurrentRole(false);
      setOperationError("");
      await refresh();
    } catch (error) {
      setOperationError(`新建会话失败：${error instanceof Error ? error.message : "新建会话失败"}`);
    }
  };

  const handleUpload = async (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    if (!files.length) {
      return;
    }
    if (
      ragUploadMode === "rebuild" &&
      !window.confirm(`将用本次 ${files.length} 个文件重建整个知识库索引，旧索引会被替换。继续吗？`)
    ) {
      event.target.value = "";
      return;
    }
    setUploadState(`${ragUploadMode === "append" ? "正在追加索引" : "正在重建索引"} ${files.length} 个文件...`);
    setOperationError("");
    try {
      const result = await uploadDocuments(files, ragUploadMode);
      setUploadState(describeRagUploadResult(result));
    } catch (error) {
      const message = error instanceof Error ? error.message : "未知错误";
      setUploadState(`上传失败：${message}`);
      setOperationError(`资料上传失败：${message}`);
    } finally {
      await refresh();
      event.target.value = "";
    }
  };

  return (
    <div className="app-shell">
      <input
        aria-label="上传资料"
        className="visually-hidden"
        multiple
        onChange={handleUpload}
        ref={fileInputRef}
        type="file"
      />
      <Sidebar
        snapshot={snapshot}
        ragEnabled={ragEnabled}
        ragUploadMode={ragUploadMode}
        setRagUploadMode={setRagUploadMode}
        setRagEnabled={setRagEnabled}
        chatSettings={chatSettings}
        setChatSettings={setChatSettings}
        ragSettings={ragSettings}
        setRagSettings={setRagSettings}
        onSaveSettings={saveSettings}
        isSavingSettings={isSavingSettings}
        onLoadRole={showRole}
        roleDetail={roleDetail}
        keepCurrentRole={keepCurrentRole}
        setKeepCurrentRole={setKeepCurrentRole}
        conversationInstruction={conversationInstruction}
        setConversationInstruction={setConversationInstruction}
        onNewSession={startNewSession}
        isSending={isSending}
        refresh={refresh}
        onUploadClick={() => fileInputRef.current?.click()}
        uploadState={uploadState}
        lastChat={lastChat}
      />
      <ChatPanel
        sessionId={singleChatSessionId}
        messages={singleChatMessages}
        input={input}
        setInput={setInput}
        isSending={isSending}
        onSubmit={submit}
        onStop={stopChatGeneration}
        streamRecovery={streamRecovery}
        onContinueInterruptedReply={continueInterruptedChat}
        onRetry={retryInterruptedChat}
        onCopyInterruptedReply={copyInterruptedReply}
        onUploadClick={() => fileInputRef.current?.click()}
        onSearchSources={searchSources}
        isSearching={isSearching}
        hasSearchQuery={Boolean(activeQuery)}
        onQuickPrompt={setInput}
        lastChat={lastChat}
        ragEnabled={ragEnabled}
        memoryStatus={snapshot.memoryStatus}
      />
      <Inspector
        snapshot={snapshot}
        singleChatSessionId={singleChatSessionId}
        wechatThreadId={wechatThreadId}
        chatSettings={chatSettings}
        lastChat={lastChat}
        ragSearch={ragSearch}
        isSearching={isSearching}
        selectedRun={selectedRun}
        loadingRunId={loadingRunId}
        selectRun={selectRun}
        toolPreview={toolPreview}
        toolCall={toolCall}
        previewTool={previewTool}
        callTool={callTool}
        isPreviewing={isPreviewing}
        isCalling={isCalling}
        toolCanCall={toolCanCall}
        toolCallBlockedReason={toolCallBlockedReason}
        toolInvocationLabel={toolInvocationLabel}
        onRestoreSession={restoreSession}
        onArchiveSession={archiveCurrentSession}
        newsResult={newsResult}
        webLookup={webLookup}
        useWebLookup={useWebLookup}
        setUseWebLookup={setUseWebLookup}
        wechatInput={wechatInput}
        setWechatInput={setWechatInput}
        newsQuery={newsQuery}
        setNewsQuery={setNewsQuery}
        readArticles={readArticles}
        setReadArticles={setReadArticles}
        onWechatOpening={handleWechatOpening}
        onWechatReset={handleWechatReset}
        onWechatMarkRead={handleWechatMarkRead}
        onSendWechat={handleSendWechat}
        onStopWechat={stopWechatGeneration}
        onLookupNews={handleLookupNews}
        onNewsRunStarted={setNewsRunId}
        onNewsDiscussed={(nextSessionId) => {
          setWechatThreadId(nextSessionId);
          void refresh();
        }}
        isWechatBusy={isWechatBusy}
        isNewsBusy={isNewsBusy}
        isSending={isSending}
        onMemoryChanged={refresh}
      />
      {snapshot.error ? (
        <div className="api-warning">
          <AlertTriangle size={16} />
          API 未连接：{snapshot.error}
        </div>
      ) : null}
      {!snapshot.error && operationError ? (
        <div className="api-warning operation-warning">
          <AlertTriangle size={16} />
          {operationError}
          <button
            className="ghost-action compact"
            onClick={() => setOperationError("")}
            style={{ marginLeft: 8 }}
            type="button"
          >
            关闭
          </button>
        </div>
      ) : null}
      {!snapshot.error && !operationError && partialErrors.length ? (
        <div className="api-warning">
          <AlertTriangle size={16} />
          部分功能暂不可用：
          <details style={{ display: "inline", marginLeft: 4 }}>
            <summary>{partialErrors.map(([key]) => key).join(", ")}</summary>
            <div style={{ marginTop: 4 }}>
              {partialErrors.map(([key, message]) => (
                <div key={key}>
                  <strong>{key}</strong>: {message}
                </div>
              ))}
            </div>
          </details>
        </div>
      ) : null}
    </div>
  );
}
