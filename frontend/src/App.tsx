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
  loadApiSnapshot,
  loadRole,
  loadWorkflowRun,
  saveRuntimeSettings
} from "./api";
import type { LocalKnowledgeInvocation } from "./api";
import { operationRegistry } from "./app/operationRegistry";
import { useWorkspace } from "./app/WorkspaceProvider";
import { RoleAvatar } from "./components/RoleAvatar";
import { StatusDot } from "./components/StatusDot";
import { MemoryPanel } from "./features/learning-memory/MemoryPanel";
import { useMemoryController } from "./features/learning-memory/memoryController";
import { RoadmapPanel } from "./features/migration/RoadmapPanel";
import { SourcesPanel } from "./features/rag/SourcesPanel";
import { useRagController } from "./features/rag/ragController";
import { useUploadController } from "./features/rag/uploadController";
import { RoutePanel } from "./features/route/RoutePanel";
import { SessionsPanel } from "./features/sessions/SessionsPanel";
import { createEmptyRag, useChatController } from "./features/chat/chatController";
import { ChatPanel } from "./features/single-chat/ChatPanel";
import { SESSION_STORAGE_KEY, seedMessages } from "./features/single-chat/chatHistory";
import { ToolPanel } from "./features/tools/ToolPanel";
import { useToolController, type ToolController } from "./features/tools/toolController";
import { roleLabel, roleOptions } from "./features/roles/roleCatalog";
import { WechatPanel } from "./features/wechat-workspace/WechatPanel";
import { useGroupChatController } from "./features/group-chat/groupChatController";
import { useNewsController, type NewsController } from "./features/news-workspace/newsController";
import { useWebLookupController } from "./features/web-lookup/webLookupController";
import { TimelinePanel } from "./features/workflows/TimelinePanel";
import { displayValue } from "./utils/format";
import type {
  ApiSnapshot,
  ChatMessage,
  ChatResponse,
  ChatSettings,
  NewsLookupResponse,
  RagQueryResponse,
  RagSettings,
  RoleResponse,
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
  auto: "根据学习行为选择协议；询问“为什么/原理”仍会直接讲解，只有明确要求自行推导才进入苏格拉底。",
  普通: "直接、完整地回答当前问题；必要时才澄清，不强制进入教学流程。",
  苏格拉底: "苏格拉底式再发现：你承担关键推理，AI每轮用一个问题、反例或有限线索设计发现路径；外部事实会直接说明。",
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
  ragUploadMode: "upload" | "rebuild";
  setRagUploadMode: (mode: "upload" | "rebuild") => void;
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
            checked={ragUploadMode === "upload"}
            name="rag-upload-mode"
            onChange={() => setRagUploadMode("upload")}
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
          <span>教学阶段</span>
          <strong>{displayValue((lastChat?.route.pedagogy as Record<string, unknown> | undefined)?.phase)}</strong>
        </div>
        <div className="metric-row">
          <span>本轮动作</span>
          <strong>{displayValue((lastChat?.route.pedagogy as Record<string, unknown> | undefined)?.move)}</strong>
        </div>
        <div className="metric-row">
          <span>知识披露</span>
          <strong>{displayValue(lastChat?.route.evidence_disclosure)}</strong>
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
  lastChat,
  ragSearch,
  isSearching,
  selectedRun,
  loadingRunId,
  selectRun,
  toolController,
  onRestoreSession,
  onArchiveSession,
  newsController,
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
  isWechatBusy,
  wechatError,
  isNewsBusy,
  isSending,
  memoryController,
  uploadController
}: {
  snapshot: ApiSnapshot;
  singleChatSessionId?: string;
  wechatThreadId?: string;
  lastChat: ChatResponse | null;
  ragSearch: RagQueryResponse | null;
  isSearching: boolean;
  selectedRun: WorkflowRunDetail | null;
  loadingRunId: string;
  selectRun: (runId: string) => void;
  toolController: ToolController;
  onRestoreSession: (sessionId: string) => void;
  onArchiveSession: (sessionId: string) => void;
  newsController: NewsController;
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
  isWechatBusy: boolean;
  wechatError: string;
  isNewsBusy: boolean;
  isSending: boolean;
  memoryController: ReturnType<typeof useMemoryController>;
  uploadController: ReturnType<typeof useUploadController>;
}) {
  return (
    <aside className="inspector">
      <RoutePanel lastChat={lastChat} />
      <WechatPanel
        wechat={snapshot.wechat}
        newsController={newsController}
        webLookup={webLookup}
        useWebLookup={useWebLookup}
        setUseWebLookup={setUseWebLookup}
        wechatInput={wechatInput}
        setWechatInput={setWechatInput}
        newsQuery={newsQuery}
        setNewsQuery={setNewsQuery}
        readArticles={readArticles}
        setReadArticles={setReadArticles}
        sessionId={wechatThreadId}
        onOpening={onWechatOpening}
        onReset={onWechatReset}
        onMarkRead={onWechatMarkRead}
        onSendWechat={onSendWechat}
        onStopWechat={onStopWechat}
        onLookupNews={onLookupNews}
        isWechatBusy={isWechatBusy}
        error={wechatError}
        isNewsBusy={isNewsBusy}
      />
      <SourcesPanel
        lastChat={lastChat}
        ragSearch={ragSearch}
        isSearching={isSearching}
        knowledgeBase={uploadController.documents}
        onDeleteDocument={(documentId) => void uploadController.removeDocument(documentId)}
      />
      <TimelinePanel
        runs={snapshot.workflowRuns}
        selectedRun={selectedRun}
        loadingRunId={loadingRunId}
        onSelectRun={selectRun}
      />
      <ToolPanel
        toolCount={snapshot.tools.length}
        run={toolController.run}
        error={toolController.error}
        previewTool={toolController.preview}
        callTool={toolController.call}
        isPreviewing={toolController.isPreviewing}
        isCalling={toolController.isCalling}
        canCall={toolController.canCall}
        callBlockedReason={toolController.callBlockedReason}
        invocationLabel={toolController.invocationLabel}
      />
      <SessionsPanel sessions={snapshot.sessions} activeSessionId={singleChatSessionId} isSending={isSending} onRestore={onRestoreSession} onArchive={onArchiveSession} />
      <RoadmapPanel />
      <MemoryPanel memoryStatus={snapshot.memoryStatus} controller={memoryController} />
    </aside>
  );
}

export default function App() {
  const [snapshot, setSnapshot] = useState<ApiSnapshot>(INITIAL_SNAPSHOT);
  const { state: workspaceRuntime, dispatch: dispatchWorkspace } = useWorkspace();
  const [input, setInput] = useState("");
  const [ragEnabled, setRagEnabled] = useState(true);
  const [chatSettings, setChatSettings] = useState<ChatSettings>(CHAT_SETTINGS_DEFAULTS);
  const [ragSettings, setRagSettings] = useState<RagSettings>(RAG_SETTINGS_DEFAULTS);
  const [keepCurrentRole, setKeepCurrentRole] = useState(false);
  const [conversationInstruction, setConversationInstruction] = useState("");
  const [isSavingSettings, setIsSavingSettings] = useState(false);
  const wechatThreadId = workspaceRuntime.activeGroupThreadId ?? snapshot.wechat?.group_thread_id;
  const newsRunId = workspaceRuntime.activeNewsRunId;
  const toolRunId = workspaceRuntime.activeToolRunId;
  const memoryRunId = workspaceRuntime.activeMemoryRunId;
  const ragQueryRunId = workspaceRuntime.activeRagQueryRunId;
  const ragWriteRunId = workspaceRuntime.activeRagWriteRunId;
  const webLookupRunId = workspaceRuntime.activeWebLookupRunId;
  const setWechatThreadId = (threadId?: string) => dispatchWorkspace({ type: "SET_ACTIVE_GROUP_THREAD", threadId });
  const setNewsRunId = (runId?: string) => dispatchWorkspace({ type: "SET_ACTIVE_NEWS_RUN", runId });
  const setToolRunId = (runId?: string) => dispatchWorkspace({ type: "SET_ACTIVE_TOOL_RUN", runId });
  const setMemoryRunId = (runId?: string) => dispatchWorkspace({ type: "SET_ACTIVE_MEMORY_RUN", runId });
  const setRagQueryRunId = (runId?: string) => dispatchWorkspace({ type: "SET_ACTIVE_RAG_QUERY_RUN", runId });
  const setRagWriteRunId = (runId?: string) => dispatchWorkspace({ type: "SET_ACTIVE_RAG_WRITE_RUN", runId });
  const setWebLookupRunId = (runId?: string) => dispatchWorkspace({ type: "SET_ACTIVE_WEB_LOOKUP_RUN", runId });
  const [selectedRun, setSelectedRun] = useState<WorkflowRunDetail | null>(null);
  const [roleDetail, setRoleDetail] = useState<RoleResponse | null>(null);
  const [loadingRunId, setLoadingRunId] = useState("");
  const [newsQuery, setNewsQuery] = useState("最新新闻 when:1d");
  const [readArticles, setReadArticles] = useState(true);
  const [operationError, setOperationError] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const sessionStoragePayloadRef = useRef("");
  const runtimeHydratedRef = useRef(false);
  const sessionSettingsRestoredRef = useRef(false);

  const refresh = async () => {
    setSnapshot(await loadApiSnapshot());
  };

  const groupController = useGroupChatController({
    wechat: snapshot.wechat,
    setWechat: (wechat) => setSnapshot((current) => ({ ...current, wechat })),
    chatSettings,
    ragSettings,
    ragEnabled,
    clearAssociatedNews: () => {
      setNewsRunId(undefined);
    },
  });

  const newsController = useNewsController({
    query: newsQuery,
    readArticles,
    chatSettings,
    groupThreadId: wechatThreadId,
    activeRunId: newsRunId,
    setActiveRunId: setNewsRunId,
    onDiscussed: (threadId) => {
      setWechatThreadId(threadId);
      void refresh();
    },
  });
  const webLookupController = useWebLookupController({
    query: newsQuery,
    setOperationError,
    activeRunId: webLookupRunId,
    setActiveRunId: setWebLookupRunId,
  });
  const memoryController = useMemoryController({
    activeRunId: memoryRunId,
    setActiveRunId: setMemoryRunId,
    onMemoryChanged: refresh,
  });
  const ragController = useRagController({
    settings: ragSettings,
    activeRunId: ragQueryRunId,
    setActiveRunId: setRagQueryRunId,
    setOperationError,
  });
  const uploadController = useUploadController({
    activeRunId: ragWriteRunId,
    setActiveRunId: setRagWriteRunId,
    setOperationError,
    onChanged: refresh,
  });
  const webLookup = webLookupController.result;
  const useWebLookup = webLookupController.useInChat;
  const setUseWebLookup = webLookupController.setUseInChat;

  useEffect(() => {
    const serverThreadId = snapshot.wechat?.group_thread_id;
    if (serverThreadId && workspaceRuntime.activeGroupThreadId !== serverThreadId) {
      setWechatThreadId(serverThreadId);
    }
  }, [snapshot.wechat?.group_thread_id, workspaceRuntime.activeGroupThreadId]);

  const chatController = useChatController({
    chatSettings,
    chatSettingsDefaults: CHAT_SETTINGS_DEFAULTS,
    setChatSettings,
    ragSettings,
    ragSettingsDefaults: RAG_SETTINGS_DEFAULTS,
    setRagSettings,
    ragEnabled,
    setRagEnabled,
    keepCurrentRole,
    setKeepCurrentRole,
    conversationInstruction,
    setConversationInstruction,
    webLookupSource: webLookup?.source_block ?? "",
    useWebLookup,
    setUseWebLookup,
    setInput,
    setOperationError,
    clearChatArtifacts: () => {
      ragController.clear();
      operationRegistry.invalidate("tool");
      setToolRunId(undefined);
      setSelectedRun(null);
    },
    onWorkspaceCancelled: () => {
      groupController.cancelWorkspace();
      newsController.cancelWorkspace();
      operationRegistry.invalidate("tool");
      webLookupController.cancel();
    },
    refresh,
  });
  const singleChatMessages = chatController.messages;
  const setSingleChatMessages = chatController.setMessages;
  const lastChat = chatController.lastChat;
  const setLastChat = chatController.setLastChat;
  const streamRecovery = chatController.streamRecovery;
  const singleChatSessionId = chatController.threadId;
  const setSingleChatSessionId = chatController.setThreadId;
  const isSending = chatController.isSending;
  const cancelWorkspaceRuns = chatController.cancelWorkspaceRuns;

  const activeQuery = input.trim() || lastChat?.rag?.query || "";
  const partialErrors = Object.entries(snapshot.errors ?? {}).filter(([key]) => key !== "health");
  const currentToolInvocation: LocalKnowledgeInvocation = {
    query: activeQuery,
    retrievalMode: ragSettings.retrievalMode,
    topK: ragSettings.chatTopK,
    minScore: ragSettings.minScore
  };
  const toolController = useToolController({
    invocation: currentToolInvocation,
    activeRunId: toolRunId,
    setActiveRunId: setToolRunId,
    onCalled: async () => {
      await refresh();
    },
  });

  useEffect(() => {
    const saved = window.localStorage.getItem(SESSION_STORAGE_KEY);
    if (saved) {
      try {
        const parsed = JSON.parse(saved) as Record<string, unknown>;
        const restoredThreadId = String(parsed.singleChatSessionId ?? parsed.sessionId ?? "");
        const restoredWechatThreadId = String(parsed.wechatThreadId ?? "");
        const restoredNewsRunId = String(parsed.newsRunId ?? "");
        const restoredToolRunId = String(parsed.toolRunId ?? "");
        const restoredMemoryRunId = String(parsed.memoryRunId ?? "");
        const restoredRagQueryRunId = String(parsed.ragQueryRunId ?? "");
        const restoredRagWriteRunId = String(parsed.ragWriteRunId ?? "");
        const restoredWebLookupRunId = String(parsed.webLookupRunId ?? "");
        if (restoredWechatThreadId) {
          setWechatThreadId(restoredWechatThreadId);
        }
        if (restoredNewsRunId) {
          setNewsRunId(restoredNewsRunId);
        }
        if (restoredToolRunId) {
          setToolRunId(restoredToolRunId);
        }
        if (restoredMemoryRunId) {
          setMemoryRunId(restoredMemoryRunId);
        }
        if (restoredRagQueryRunId) {
          setRagQueryRunId(restoredRagQueryRunId);
        }
        if (restoredRagWriteRunId) {
          setRagWriteRunId(restoredRagWriteRunId);
        }
        if (restoredWebLookupRunId) {
          setWebLookupRunId(restoredWebLookupRunId);
        }
        if (parsed.chatSettings && typeof parsed.chatSettings === "object") {
          sessionSettingsRestoredRef.current = true;
          setChatSettings({ ...CHAT_SETTINGS_DEFAULTS, ...(parsed.chatSettings as ChatSettings) });
        }
        if (parsed.ragSettings && typeof parsed.ragSettings === "object") {
          sessionSettingsRestoredRef.current = true;
          setRagSettings({ ...RAG_SETTINGS_DEFAULTS, ...(parsed.ragSettings as RagSettings) });
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
        if (restoredThreadId) {
          const cached = Array.isArray(parsed.cachedMessages)
            ? (parsed.cachedMessages as ChatMessage[])
            : undefined;
          void chatController.hydrateSession(restoredThreadId, cached);
        } else {
          setSingleChatMessages(seedMessages);
        }
        if (parsed.lastRoute && typeof parsed.lastRoute === "object") {
          const restoredRoute = parsed.lastRoute as ChatResponse["route"];
          const restoredRag = (parsed.lastRag && typeof parsed.lastRag === "object" ? parsed.lastRag : createEmptyRag()) as ChatResponse["rag"];
          setLastChat({
            reply: "",
            session_id: String(parsed.lastSessionId ?? restoredThreadId ?? "restored"),
            route: restoredRoute,
            rag: restoredRag,
          });
        }
      } catch {
        window.localStorage.removeItem(SESSION_STORAGE_KEY);
        setSingleChatMessages(seedMessages);
      }
    } else {
      setSingleChatMessages(seedMessages);
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
    const payload = JSON.stringify({
      singleChatSessionId,
      wechatThreadId,
      newsRunId,
      toolRunId,
      memoryRunId,
      ragQueryRunId,
      ragWriteRunId,
      webLookupRunId,
      chatSettings,
      ragSettings,
      ragEnabled,
      keepCurrentRole,
      conversationInstruction,
      lastRoute: lastChat?.route ?? undefined,
      lastRag: lastChat?.rag ?? undefined,
      lastSessionId: lastChat?.session_id ?? undefined,
      cachedMessages: singleChatMessages,
    });
    sessionStoragePayloadRef.current = payload;
    const timeout = window.setTimeout(() => {
      window.localStorage.setItem(SESSION_STORAGE_KEY, payload);
    }, isSending ? 800 : 200);
    return () => window.clearTimeout(timeout);
  }, [singleChatMessages, singleChatSessionId, wechatThreadId, newsRunId, toolRunId, memoryRunId, ragQueryRunId, ragWriteRunId, webLookupRunId, chatSettings, ragSettings, ragEnabled, keepCurrentRole, conversationInstruction, lastChat, isSending]);

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


  const submit = async (event: FormEvent) => {
    event.preventDefault();
    await chatController.send(input.trim());
  };

  const stopChatGeneration = chatController.stop;

  const retryInterruptedChat = chatController.retry;
  const continueInterruptedChat = chatController.continueInterrupted;
  const copyInterruptedReply = chatController.copyInterrupted;

  const searchSources = () => ragController.search(activeQuery);

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

  const selectRun = async (runId: string) => {
    setLoadingRunId(runId);
    try {
      setSelectedRun(await loadWorkflowRun(runId));
    } finally {
      setLoadingRunId("");
    }
  };

  const restoreSession = chatController.restoreSession;
  const archiveCurrentSession = chatController.archiveCurrentSession;
  const startNewSession = chatController.startNewSession;

  const handleUpload = async (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    if (!files.length) {
      return;
    }
    if (
      uploadController.mode === "rebuild" &&
      !window.confirm(`将用本次 ${files.length} 个文件重建整个知识库索引，旧索引会被替换。继续吗？`)
    ) {
      event.target.value = "";
      return;
    }
    await uploadController.upload(files);
    event.target.value = "";
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
        ragUploadMode={uploadController.mode}
        setRagUploadMode={uploadController.setMode}
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
        uploadState={uploadController.status}
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
        isSearching={ragController.isSearching}
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
        lastChat={lastChat}
        ragSearch={ragController.result}
        isSearching={ragController.isSearching}
        selectedRun={selectedRun}
        loadingRunId={loadingRunId}
        selectRun={selectRun}
        toolController={toolController}
        onRestoreSession={restoreSession}
        onArchiveSession={archiveCurrentSession}
        newsController={newsController}
        webLookup={webLookup}
        useWebLookup={useWebLookup}
        setUseWebLookup={setUseWebLookup}
        wechatInput={groupController.input}
        setWechatInput={groupController.setInput}
        newsQuery={newsQuery}
        setNewsQuery={setNewsQuery}
        readArticles={readArticles}
        setReadArticles={setReadArticles}
        onWechatOpening={groupController.opening}
        onWechatReset={groupController.reset}
        onWechatMarkRead={groupController.markRead}
        onSendWechat={groupController.send}
        onStopWechat={groupController.stop}
        onLookupNews={webLookupController.lookup}
        isWechatBusy={groupController.isBusy}
        wechatError={groupController.error}
        isNewsBusy={webLookupController.isBusy}
        isSending={isSending}
        memoryController={memoryController}
        uploadController={uploadController}
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
