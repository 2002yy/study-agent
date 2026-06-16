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
  callLocalKnowledge,
  createWechatOpening,
  loadApiSnapshot,
  loadRole,
  loadWorkflowRun,
  lookupNews,
  markWechatRead,
  previewLocalKnowledge,
  queryRag,
  resetWechat,
  runNewsSearch,
  saveRuntimeSettings,
  sendChatStream,
  sendWechatMessage,
  uploadDocuments
} from "./api";
import { RoleAvatar } from "./components/RoleAvatar";
import { StatusDot } from "./components/StatusDot";
import { MemoryPanel } from "./features/learning-memory/MemoryPanel";
import { RoadmapPanel } from "./features/migration/RoadmapPanel";
import { SourcesPanel } from "./features/rag/SourcesPanel";
import { RoutePanel } from "./features/route/RoutePanel";
import { SessionsPanel } from "./features/sessions/SessionsPanel";
import { ChatPanel } from "./features/single-chat/ChatPanel";
import { SESSION_STORAGE_KEY, sanitizeSingleChatMessages, seedMessages, toChatHistoryPayload } from "./features/single-chat/chatHistory";
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
  RagQueryResponse,
  RagSettings,
  RoleResponse,
  ToolInvocationResponse,
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
  error: ""
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
  auto: "后端根据问题自动判断学习方式。",
  普通: "直接回答问题，适合快速确认事实或步骤。",
  苏格拉底: "通过连续追问帮你自己推理出答案，适合概念卡住时使用。",
  费曼: "要求你用简单语言复述，再帮你找漏洞，适合检查是否真正理解。",
  项目: "围绕目标、任务、风险和下一步推进。"
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
  setRagEnabled,
  chatSettings,
  setChatSettings,
  ragSettings,
  setRagSettings,
  onSaveSettings,
  isSavingSettings,
  onLoadRole,
  roleDetail,
  refresh,
  onUploadClick,
  uploadState,
  lastChat
}: {
  snapshot: ApiSnapshot;
  ragEnabled: boolean;
  setRagEnabled: (value: boolean) => void;
  chatSettings: ChatSettings;
  setChatSettings: (value: ChatSettings) => void;
  ragSettings: RagSettings;
  setRagSettings: (value: RagSettings) => void;
  onSaveSettings: () => void;
  isSavingSettings: boolean;
  onLoadRole: () => void;
  roleDetail: RoleResponse | null;
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

      <button className="primary-action" onClick={onUploadClick} type="button">
        <Upload size={17} />
        上传并建立索引
      </button>
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
          <select value={chatSettings.selectedRole} onChange={(event) => updateChatSetting("selectedRole", event.target.value)}>
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
        {chatSettings.selectedRole !== "auto" ? (
          <button className="ghost-action compact" onClick={onLoadRole} type="button">
            <BookOpen size={15} />
            查看角色人设
          </button>
        ) : null}
        {roleDetail ? (
          <div className="role-preview">
            <strong>{roleDetail.label}</strong>
            <p>{roleDetail.summary}</p>
            <details>
              <summary>完整提示词</summary>
              <pre>{roleDetail.prompt}</pre>
            </details>
          </div>
        ) : null}
        <label className="field-row">
          <span>学习模式</span>
          <select value={chatSettings.selectedMode} onChange={(event) => updateChatSetting("selectedMode", event.target.value)}>
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
          <select value={chatSettings.selectedModel} onChange={(event) => updateChatSetting("selectedModel", event.target.value)}>
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
          <select value={chatSettings.contextMode} onChange={(event) => updateChatSetting("contextMode", event.target.value)}>
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
          <select value={chatSettings.relationshipMode} onChange={(event) => updateChatSetting("relationshipMode", event.target.value)}>
            {relationshipOptions.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <small className="field-hint">{relationshipDescriptions[chatSettings.relationshipMode]}</small>
        <label className="toggle-row">
          <input checked={ragEnabled} onChange={(event) => setRagEnabled(event.target.checked)} type="checkbox" />
          <span>用于聊天回答</span>
        </label>
        <small className="field-hint">开启后，回答会先查本地资料再生成；关闭则更像普通聊天，不引用资料库。</small>
        <label className="field-row">
          <span>检索模式</span>
          <select
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
              onChange={(event) => updateRagSetting("topK", Number(event.target.value))}
              type="number"
              value={ragSettings.topK}
            />
          </label>
          <label className="field-row compact">
            <span>聊天引用</span>
            <input
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
        <button className="primary-action secondary" disabled={isSavingSettings} onClick={onSaveSettings} type="button">
          {isSavingSettings ? <Loader2 className="spin" size={16} /> : <CheckCircle2 size={16} />}
          保存设置到后端
        </button>
      </section>

      <section className="side-section">
        <div className="section-title">
          <Activity size={15} />
          当前回答检查
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
  onRunNews,
  onLookupNews,
  isWechatBusy,
  isNewsBusy,
  onMemoryChanged
}: {
  snapshot: ApiSnapshot;
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
  onRunNews: (event: FormEvent) => void;
  onLookupNews: () => void;
  isWechatBusy: boolean;
  isNewsBusy: boolean;
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
        onOpening={onWechatOpening}
        onReset={onWechatReset}
        onMarkRead={onWechatMarkRead}
        onSendWechat={onSendWechat}
        onRunNews={onRunNews}
        onLookupNews={onLookupNews}
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
      />
      <SessionsPanel sessions={snapshot.sessions} />
      <RoadmapPanel />
      <MemoryPanel memoryStatus={snapshot.memoryStatus} onMemoryChanged={onMemoryChanged} />
    </aside>
  );
}

export default function App() {
  const [snapshot, setSnapshot] = useState<ApiSnapshot>(INITIAL_SNAPSHOT);
  const [singleChatMessages, setSingleChatMessages] = useState<ChatMessage[]>(seedMessages);
  const [input, setInput] = useState("根据本地资料解释 RAG 工作流时间线的作用");
  const [ragEnabled, setRagEnabled] = useState(true);
  const [chatSettings, setChatSettings] = useState<ChatSettings>(CHAT_SETTINGS_DEFAULTS);
  const [ragSettings, setRagSettings] = useState<RagSettings>(RAG_SETTINGS_DEFAULTS);
  const [isSending, setIsSending] = useState(false);
  const [isSavingSettings, setIsSavingSettings] = useState(false);
  const [isPreviewing, setIsPreviewing] = useState(false);
  const [isCalling, setIsCalling] = useState(false);
  const [isSearching, setIsSearching] = useState(false);
  const [sessionId, setSessionId] = useState<string | undefined>();
  const [lastChat, setLastChat] = useState<ChatResponse | null>(null);
  const [ragSearch, setRagSearch] = useState<RagQueryResponse | null>(null);
  const [toolPreview, setToolPreview] = useState<ToolInvocationResponse | null>(null);
  const [toolCall, setToolCall] = useState<ToolInvocationResponse | null>(null);
  const [selectedRun, setSelectedRun] = useState<WorkflowRunDetail | null>(null);
  const [roleDetail, setRoleDetail] = useState<RoleResponse | null>(null);
  const [newsResult, setNewsResult] = useState<NewsSearchResponse | null>(null);
  const [webLookup, setWebLookup] = useState<NewsLookupResponse | null>(null);
  const [useWebLookup, setUseWebLookup] = useState(true);
  const [loadingRunId, setLoadingRunId] = useState("");
  const [uploadState, setUploadState] = useState("");
  const [wechatInput, setWechatInput] = useState("");
  const [newsQuery, setNewsQuery] = useState("最新新闻 when:1d");
  const [readArticles, setReadArticles] = useState(true);
  const [isWechatBusy, setIsWechatBusy] = useState(false);
  const [isNewsBusy, setIsNewsBusy] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const runtimeHydratedRef = useRef(false);

  const activeQuery = input.trim() || lastChat?.rag?.query || "本地资料 工作流 引用来源";

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
          chatSettings?: ChatSettings;
          ragSettings?: RagSettings;
          ragEnabled?: boolean;
        };
        setSingleChatMessages(sanitizeSingleChatMessages(parsed.singleChatMessages ?? parsed.messages));
        if (parsed.sessionId) {
          setSessionId(parsed.sessionId);
        }
        if (parsed.chatSettings) {
          setChatSettings({ ...CHAT_SETTINGS_DEFAULTS, ...parsed.chatSettings });
        }
        if (parsed.ragSettings) {
          setRagSettings({ ...RAG_SETTINGS_DEFAULTS, ...parsed.ragSettings });
        }
        if (typeof parsed.ragEnabled === "boolean") {
          setRagEnabled(parsed.ragEnabled);
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
      topK: settings.rag_top_k,
      chatTopK: settings.rag_top_k,
      minScore: settings.rag_min_score
    });
  }, [snapshot.runtimeSettings]);

  useEffect(() => {
    window.localStorage.setItem(
      SESSION_STORAGE_KEY,
      JSON.stringify({ singleChatMessages, sessionId, chatSettings, ragSettings, ragEnabled })
    );
  }, [singleChatMessages, sessionId, chatSettings, ragSettings, ragEnabled]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const question = input.trim();
    if (!question || isSending) {
      return;
    }
    const nextMessages: ChatMessage[] = [...singleChatMessages, { role: "user", content: question, avatarRole: "user" }];
    const assistantIndex = nextMessages.length;
    setSingleChatMessages([...nextMessages, { role: "assistant", content: "", avatarRole: "auto" }]);
    setInput("");
    setIsSending(true);
    setRagSearch(null);
    let streamedReply = "";
    const shouldConsumeWebLookup = useWebLookup && Boolean(webLookup?.source_block);
    try {
      const response = await sendChatStream(
        question,
        toChatHistoryPayload(singleChatMessages),
        {
          ragEnabled,
          sessionId,
          chatSettings,
          ragSettings,
          webContext: shouldConsumeWebLookup ? webLookup?.source_block : ""
        },
        {
          onRoute: (route) => {
            setLastChat((current) => ({
              reply: current?.reply ?? streamedReply,
              session_id: current?.session_id ?? sessionId ?? "streaming",
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
            setLastChat((current) => ({
              reply: current?.reply ?? streamedReply,
              session_id: current?.session_id ?? sessionId ?? "streaming",
              route: current?.route ?? {},
              rag
            }));
          },
          onToken: (token) => {
            streamedReply += token;
            setSingleChatMessages((current) =>
              current.map((message, index) =>
                index === assistantIndex ? { ...message, content: `${message.content}${token}` } : message
              )
            );
            setLastChat((current) => (current ? { ...current, reply: streamedReply } : current));
          },
          onDone: (done) => {
            if (typeof done.session_id === "string") {
              setSessionId(done.session_id);
            }
          }
        }
      );
      setSessionId(response.session_id);
      setLastChat(response);
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
      const message = error instanceof Error ? error.message : "聊天请求失败";
      setSingleChatMessages((current) =>
        current.map((item, index) =>
          index === assistantIndex ? { ...item, avatarRole: "auto", content: `请求失败：${message}` } : item
        )
      );
    } finally {
      setIsSending(false);
    }
  };

  const searchSources = async () => {
    if (!activeQuery || isSearching) {
      return;
    }
    setIsSearching(true);
    try {
      setRagSearch(await queryRag(activeQuery, ragSettings));
    } catch (error) {
      setRagSearch(null);
      setSnapshot((current) => ({
        ...current,
        error: error instanceof Error ? error.message : "来源检索失败"
      }));
    } finally {
      setIsSearching(false);
    }
  };

  const previewTool = async () => {
    setIsPreviewing(true);
    setToolCall(null);
    try {
      setToolPreview(await previewLocalKnowledge(activeQuery));
    } catch (error) {
      setToolPreview({
        tool_name: "retrieve_local_knowledge",
        status: "failed",
        output: {},
        reason: error instanceof Error ? error.message : "预览失败",
        elapsed_ms: 0,
        run_id: ""
      });
    } finally {
      setIsPreviewing(false);
    }
  };

  const saveSettings = async () => {
    setIsSavingSettings(true);
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
        rag_top_k: ragSettings.chatTopK,
        rag_min_score: ragSettings.minScore
      });
      setSnapshot((current) => ({ ...current, runtimeSettings: response, error: "" }));
      await refresh();
    } catch (error) {
      setSnapshot((current) => ({
        ...current,
        error: error instanceof Error ? error.message : "设置保存失败"
      }));
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
        summary: error instanceof Error ? error.message : "角色读取失败"
      });
    }
  };

  const callTool = async () => {
    if (!toolPreview || isCalling) {
      return;
    }
    setIsCalling(true);
    try {
      const result = await callLocalKnowledge(activeQuery);
      setToolCall(result);
      await refresh();
      if (result.run_id) {
        await selectRun(result.run_id);
      }
    } catch (error) {
      setToolCall({
        tool_name: "retrieve_local_knowledge",
        status: "failed",
        output: {},
        reason: error instanceof Error ? error.message : "调用失败",
        elapsed_ms: 0,
        run_id: ""
      });
    } finally {
      setIsCalling(false);
    }
  };

  const handleWechatOpening = async () => {
    if (isWechatBusy) {
      return;
    }
    setIsWechatBusy(true);
    try {
      const wechat = await createWechatOpening(chatSettings);
      setSnapshot((current) => ({ ...current, wechat, error: "" }));
    } catch (error) {
      setSnapshot((current) => ({
        ...current,
        error: error instanceof Error ? error.message : "群聊开场生成失败"
      }));
    } finally {
      setIsWechatBusy(false);
    }
  };

  const handleWechatReset = async () => {
    if (isWechatBusy) {
      return;
    }
    setIsWechatBusy(true);
    try {
      const wechat = await resetWechat();
      setNewsResult(null);
      setSnapshot((current) => ({ ...current, wechat, error: "" }));
    } catch (error) {
      setSnapshot((current) => ({
        ...current,
        error: error instanceof Error ? error.message : "新群聊创建失败"
      }));
    } finally {
      setIsWechatBusy(false);
    }
  };

  const handleWechatMarkRead = async () => {
    try {
      const wechat = await markWechatRead(sessionId);
      setSnapshot((current) => ({ ...current, wechat, error: "" }));
    } catch (error) {
      setSnapshot((current) => ({
        ...current,
        error: error instanceof Error ? error.message : "标记已读失败"
      }));
    }
  };

  const handleSendWechat = async (event: FormEvent) => {
    event.preventDefault();
    const message = wechatInput.trim();
    if (!message || isWechatBusy) {
      return;
    }
    setIsWechatBusy(true);
    try {
      const response = await sendWechatMessage(message, {
        sessionId,
        ragEnabled,
        chatSettings,
        ragSettings
      });
      setSessionId(response.session_id);
      setWechatInput("");
      await refresh();
    } catch (error) {
      setSnapshot((current) => ({
        ...current,
        error: error instanceof Error ? error.message : "群聊发送失败"
      }));
    } finally {
      setIsWechatBusy(false);
    }
  };

  const handleRunNews = async (event: FormEvent) => {
    event.preventDefault();
    const query = newsQuery.trim();
    if (!query || isNewsBusy) {
      return;
    }
    setIsNewsBusy(true);
    try {
      const result = await runNewsSearch(query, {
        sessionId,
        readArticles,
        chatSettings
      });
      setNewsResult(result);
      setSessionId(result.session_id);
      await refresh();
    } catch (error) {
      setSnapshot((current) => ({
        ...current,
        error: error instanceof Error ? error.message : "联网检索失败"
      }));
    } finally {
      setIsNewsBusy(false);
    }
  };

  const handleLookupNews = async () => {
    const query = newsQuery.trim();
    if (!query || isNewsBusy) {
      return;
    }
    setIsNewsBusy(true);
    try {
      const result = await lookupNews(query);
      setWebLookup(result);
      setUseWebLookup(true);
      setSnapshot((current) => ({ ...current, error: "" }));
    } catch (error) {
      setSnapshot((current) => ({
        ...current,
        error: error instanceof Error ? error.message : "联网搜索失败"
      }));
    } finally {
      setIsNewsBusy(false);
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

  const handleUpload = async (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    if (!files.length) {
      return;
    }
    setUploadState(`正在索引 ${files.length} 个文件...`);
    try {
      const result = await uploadDocuments(files);
      setUploadState(`已索引 ${result.documents} 个文档、${result.chunks} 个片段`);
      await refresh();
    } catch (error) {
      setUploadState(`上传失败：${error instanceof Error ? error.message : "未知错误"}`);
    } finally {
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
        setRagEnabled={setRagEnabled}
        chatSettings={chatSettings}
        setChatSettings={setChatSettings}
        ragSettings={ragSettings}
        setRagSettings={setRagSettings}
        onSaveSettings={saveSettings}
        isSavingSettings={isSavingSettings}
        onLoadRole={showRole}
        roleDetail={roleDetail}
        refresh={refresh}
        onUploadClick={() => fileInputRef.current?.click()}
        uploadState={uploadState}
        lastChat={lastChat}
      />
      <ChatPanel
        messages={singleChatMessages}
        input={input}
        setInput={setInput}
        isSending={isSending}
        onSubmit={submit}
        onUploadClick={() => fileInputRef.current?.click()}
        onSearchSources={searchSources}
        isSearching={isSearching}
        onQuickPrompt={setInput}
        lastChat={lastChat}
        ragEnabled={ragEnabled}
      />
      <Inspector
        snapshot={snapshot}
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
        onRunNews={handleRunNews}
        onLookupNews={handleLookupNews}
        isWechatBusy={isWechatBusy}
        isNewsBusy={isNewsBusy}
        onMemoryChanged={refresh}
      />
      {snapshot.error ? (
        <div className="api-warning">
          <AlertTriangle size={16} />
          API 未连接：{snapshot.error}
        </div>
      ) : null}
    </div>
  );
}
