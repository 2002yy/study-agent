import {
  Activity,
  AlertTriangle,
  BookOpen,
  Bot,
  BrainCircuit,
  CheckCircle2,
  Clock3,
  Database,
  FileText,
  ListChecks,
  Loader2,
  MemoryStick,
  MessageSquare,
  RefreshCw,
  Search,
  Send,
  Settings,
  ShieldCheck,
  Sparkles,
  Upload,
  User,
  Wrench
} from "lucide-react";
import { ChangeEvent, FormEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  callLocalKnowledge,
  loadApiSnapshot,
  loadRole,
  loadWorkflowRun,
  previewLocalKnowledge,
  queryRag,
  saveRuntimeSettings,
  sendChat,
  uploadDocuments
} from "./api";
import type {
  ApiSnapshot,
  ChatMessage,
  ChatResponse,
  ChatSettings,
  MemoryStatusResponse,
  RagDebugResult,
  RagQueryResponse,
  RagResult,
  RagSettings,
  RoleResponse,
  SessionRow,
  ToolInvocationResponse,
  WorkflowRunDetail,
  WorkflowRunSummary
} from "./types";

const INITIAL_SNAPSHOT: ApiSnapshot = {
  health: null,
  ragStatus: null,
  tools: [],
  workflowRuns: [],
  sessions: [],
  runtimeSettings: null,
  memoryStatus: null,
  error: ""
};

const seedMessages: ChatMessage[] = [
  {
    role: "assistant",
    content:
      "本地学习工作台已就绪。你可以提问、上传资料、查看引用来源，并在右侧检查工具调用与工作流状态。"
  }
];

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

const roleOptions = [
  ["auto", "自动"],
  ["march7", "三月七"],
  ["keqing", "刻晴"],
  ["nahida", "纳西妲"],
  ["firefly", "流萤"]
] as const;

const modeOptions = [
  ["auto", "自动"],
  ["普通", "普通"],
  ["苏格拉底", "苏格拉底"],
  ["费曼", "费曼"],
  ["项目", "项目"],
  ["论文", "论文"],
  ["概念地图", "概念地图"]
] as const;

const modelOptions = [
  ["auto", "自动"],
  ["flash", "Flash"],
  ["pro", "Pro"]
] as const;

const contextModeOptions = [
  ["", "自动"],
  ["fast", "快速"],
  ["light", "标准"],
  ["deep", "深度"]
] as const;

const relationshipOptions = [
  ["standard", "自然"],
  ["warm", "温和"],
  ["close", "贴近"]
] as const;

const retrievalOptions = [
  ["lexical", "关键词"],
  ["hybrid", "混合"],
  ["vector", "本地向量"],
  ["backend_vector", "向量后端"]
] as const;

const quickPrompts = [
  "继续上次学习，先给我一个下一步建议",
  "分析当前 Study Agent 架构，并列出最该推进的三件事",
  "根据本地资料解释 RAG 工作流时间线的作用"
];

const roadmapItems = [
  "微信群、新闻讨论和课后总结仍需要 PRD 中的新增 API 才能完整迁移。",
  "React 当前先补齐单人学习设置、路由检查、RAG 参数和会话状态。",
  "Streamlit 暂时保留为业务闭环回归参考。"
];

type SourceRow = {
  key: string;
  rank: number;
  title: string;
  sourcePath: string;
  lineRange: string;
  score: number;
  matchedTerms: string[];
  scoreBreakdown: Record<string, number>;
};

function StatusDot({ tone = "neutral" }: { tone?: "good" | "warn" | "neutral" | "bad" }) {
  return <span className={`status-dot ${tone}`} />;
}

function formatScore(value: number | undefined): string {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "-";
  }
  return value.toFixed(3);
}

function translateStatus(value: string | undefined): string {
  const labels: Record<string, string> = {
    waiting: "等待中",
    skipped: "已跳过",
    found: "已找到",
    not_found: "未找到",
    index_missing: "索引缺失",
    error: "错误",
    preview: "预览",
    succeeded: "成功",
    failed: "失败",
    blocked: "已阻止",
    started: "已开始",
    running: "运行中"
  };
  return labels[value ?? ""] ?? (value || "-");
}

function basename(path: string): string {
  const parts = path.split(/[\\/]/).filter(Boolean);
  return parts.length ? parts[parts.length - 1] : path;
}

function displayValue(value: unknown): string {
  if (value === null || typeof value === "undefined" || value === "") {
    return "-";
  }
  if (Array.isArray(value)) {
    return value.length ? value.join(", ") : "-";
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}

function formatBytes(value: number | undefined): string {
  if (!value) {
    return "0 B";
  }
  if (value < 1024) {
    return `${value} B`;
  }
  if (value < 1024 * 1024) {
    return `${(value / 1024).toFixed(1)} KB`;
  }
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function formatMtime(ns: number | undefined): string {
  if (!ns) {
    return "-";
  }
  return new Date(Math.floor(ns / 1_000_000)).toLocaleString();
}

function sourceRowsFromDebug(debugResults: RagDebugResult[] | undefined, fallbackResults: RagResult[]): SourceRow[] {
  if (debugResults?.length) {
    return debugResults.map((item, index) => ({
      key: `${item.source_path ?? "source"}-${item.rank ?? index}`,
      rank: item.rank ?? index + 1,
      title: item.title || basename(item.source_path ?? "未命名资料"),
      sourcePath: item.source_path ?? "未知来源",
      lineRange: item.line_range ?? "-",
      score: item.score ?? 0,
      matchedTerms: item.matched_terms ?? [],
      scoreBreakdown: item.score_breakdown ?? {}
    }));
  }
  return fallbackResults.map((item, index) => {
    const chunk = item.chunk ?? {};
    return {
      key: chunk.chunk_id ?? `${chunk.source_path ?? "source"}-${index}`,
      rank: index + 1,
      title: chunk.title || basename(chunk.source_path ?? "未命名资料"),
      sourcePath: chunk.source_path ?? "未知来源",
      lineRange:
        typeof chunk.start_line === "number" && typeof chunk.end_line === "number"
          ? `L${chunk.start_line}-L${chunk.end_line}`
          : "-",
      score: item.score ?? 0,
      matchedTerms: item.matched_terms ?? [],
      scoreBreakdown: {}
    };
  });
}

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
        <label className="toggle-row">
          <input checked={ragEnabled} onChange={(event) => setRagEnabled(event.target.checked)} type="checkbox" />
          <span>用于聊天回答</span>
        </label>
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

function ChatPanel({
  messages,
  input,
  setInput,
  isSending,
  onSubmit,
  onUploadClick,
  onSearchSources,
  isSearching,
  onQuickPrompt,
  lastChat,
  ragEnabled
}: {
  messages: ChatMessage[];
  input: string;
  setInput: (value: string) => void;
  isSending: boolean;
  onSubmit: (event: FormEvent) => void;
  onUploadClick: () => void;
  onSearchSources: () => void;
  isSearching: boolean;
  onQuickPrompt: (value: string) => void;
  lastChat: ChatResponse | null;
  ragEnabled: boolean;
}) {
  return (
    <main className="chat-panel" id="chat">
      <header className="topbar">
        <div>
          <h1>学习工作台</h1>
          <p>提问、检索本地资料、检查执行链路，再决定哪些内容写入记忆。</p>
          <div className="topbar-meta">
            <span>RAG {ragEnabled ? "已启用" : "未启用"}</span>
            <span>路由 {lastChat ? "已生成" : "等待提问"}</span>
            <span>Session {lastChat?.session_id ?? "未开始"}</span>
          </div>
        </div>
        <div className="topbar-actions">
          <button className="icon-button" onClick={onUploadClick} type="button" title="上传资料">
            <Upload size={17} />
          </button>
          <button className="icon-button" onClick={onSearchSources} type="button" title="检索来源">
            {isSearching ? <Loader2 className="spin" size={17} /> : <Search size={17} />}
          </button>
        </div>
      </header>

      <section className="conversation" aria-label="Conversation">
        <div className="home-brief">
          <div>
            <h2>继续学习</h2>
            <p>PRD 的方向是把 Streamlit 的学习闭环迁回 React，同时保留工具、来源和工作流审计。</p>
          </div>
          <div className="quick-grid">
            {quickPrompts.map((prompt) => (
              <button key={prompt} onClick={() => onQuickPrompt(prompt)} type="button">
                {prompt}
              </button>
            ))}
          </div>
        </div>
        {messages.map((message, index) => (
          <article className={`message ${message.role}`} key={`${message.role}-${index}`}>
            <div className="avatar">{message.role === "user" ? <User size={16} /> : <Bot size={16} />}</div>
            <div className="message-body">
              <span>{message.role === "user" ? "你" : "Study Agent"}</span>
              <p>{message.content}</p>
            </div>
          </article>
        ))}
      </section>

      <form className="composer" onSubmit={onSubmit}>
        <textarea
          aria-label="Message"
          onChange={(event) => setInput(event.target.value)}
          placeholder="输入你的问题，或让本地资料帮你解释一个概念..."
          value={input}
        />
        <button className="send-button" disabled={isSending || !input.trim()} type="submit">
          {isSending ? <Loader2 className="spin" size={17} /> : <Send size={17} />}
          {isSending ? "发送中" : "发送"}
        </button>
      </form>
    </main>
  );
}

function SourcesPanel({
  lastChat,
  ragSearch,
  isSearching
}: {
  lastChat: ChatResponse | null;
  ragSearch: RagQueryResponse | null;
  isSearching: boolean;
}) {
  const rows = useMemo(() => {
    const source = ragSearch ?? lastChat?.rag;
    return sourceRowsFromDebug(source?.debug.results, source?.results ?? []);
  }, [lastChat, ragSearch]);
  const activeSource = ragSearch ?? lastChat?.rag;
  const status = ragSearch ? `检索到 ${ragSearch.result_count} 条` : translateStatus(lastChat?.rag.status ?? "waiting");

  return (
    <section className="panel" id="sources">
      <div className="panel-header">
        <div>
          <h2>引用来源</h2>
          <span>{isSearching ? "正在检索" : status}</span>
        </div>
        <FileText size={18} />
      </div>
      {rows.length ? (
        <div className="source-table" role="table" aria-label="检索到的引用来源">
          <div className="source-row header" role="row">
            <span>排序</span>
            <span>来源</span>
            <span>分数</span>
          </div>
          {rows.map((row) => (
            <div className="source-row" role="row" key={row.key}>
              <strong>#{row.rank}</strong>
              <div>
                <b>{row.title}</b>
                <small>
                  {row.lineRange} · {row.matchedTerms.length ? row.matchedTerms.join(", ") : "暂无命中词"}
                </small>
                <em title={row.sourcePath}>{row.sourcePath}</em>
                {Object.keys(row.scoreBreakdown).length ? (
                  <details className="inline-details">
                    <summary>分数 breakdown</summary>
                    <pre>{JSON.stringify(row.scoreBreakdown, null, 2)}</pre>
                  </details>
                ) : null}
              </div>
              <span>{formatScore(row.score)}</span>
            </div>
          ))}
        </div>
      ) : (
        <div className="empty-state">还没有引用来源。开启“用于聊天回答”后提问，或点击顶部检索按钮。</div>
      )}
      {activeSource?.context || activeSource?.sources ? (
        <details className="debug-drawer">
          <summary>引用上下文与来源块</summary>
          {activeSource.sources ? (
            <>
              <strong>来源块</strong>
              <pre>{activeSource.sources}</pre>
            </>
          ) : null}
          {activeSource.context ? (
            <>
              <strong>注入上下文</strong>
              <pre>{activeSource.context}</pre>
            </>
          ) : null}
        </details>
      ) : null}
    </section>
  );
}

function TimelinePanel({
  runs,
  selectedRun,
  loadingRunId,
  onSelectRun
}: {
  runs: WorkflowRunSummary[];
  selectedRun: WorkflowRunDetail | null;
  loadingRunId: string;
  onSelectRun: (runId: string) => void;
}) {
  return (
    <section className="panel" id="timeline">
      <div className="panel-header">
        <div>
          <h2>工作流时间线</h2>
          <span>最近 {runs.length} 次运行</span>
        </div>
        <ListChecks size={18} />
      </div>
      <div className="timeline">
        {runs.length ? (
          runs.slice(0, 6).map((run) => (
            <button className="timeline-row" key={run.run_id} onClick={() => onSelectRun(run.run_id)} type="button">
              <StatusDot tone={run.status === "succeeded" ? "good" : run.status === "failed" ? "bad" : "warn"} />
              <div>
                <strong>{run.workflow_name}</strong>
                <span>{run.run_id}</span>
              </div>
              <em>{loadingRunId === run.run_id ? "..." : `${run.elapsed_ms} ms`}</em>
            </button>
          ))
        ) : (
          <div className="empty-state">还没有工作流审计事件。</div>
        )}
      </div>
      {selectedRun ? (
        <div className="run-detail">
          <div className="run-detail-title">
            <Clock3 size={15} />
            <strong>{selectedRun.run_id}</strong>
          </div>
          {selectedRun.events.map((event, index) => (
            <div className="event-row" key={`${event.event_type}-${index}`}>
              <StatusDot tone={event.status === "succeeded" ? "good" : event.status === "failed" ? "bad" : "warn"} />
              <div>
                <strong>{translateStatus(event.event_type)}</strong>
                <span>{event.message || event.step_id}</span>
                {event.error ? <em>{event.error}</em> : null}
              </div>
              <small>{event.elapsed_ms} ms</small>
            </div>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function ToolPanel({
  toolCount,
  toolPreview,
  toolCall,
  previewTool,
  callTool,
  isPreviewing,
  isCalling
}: {
  toolCount: number;
  toolPreview: ToolInvocationResponse | null;
  toolCall: ToolInvocationResponse | null;
  previewTool: () => void;
  callTool: () => void;
  isPreviewing: boolean;
  isCalling: boolean;
}) {
  const latest = toolCall ?? toolPreview;
  const outputStatus = typeof latest?.output.status === "string" ? latest.output.status : "";
  const outputLabel = outputStatus ? translateStatus(outputStatus) : latest?.reason || "就绪";
  return (
    <section className="panel" id="tools">
      <div className="panel-header">
        <div>
          <h2>工具调用</h2>
          <span>{toolCount} 个已允许工具</span>
        </div>
        <Wrench size={18} />
      </div>
      <div className="tool-actions">
        <button className="tool-button" disabled={isPreviewing} onClick={previewTool} type="button">
          {isPreviewing ? <Loader2 className="spin" size={16} /> : <Sparkles size={16} />}
          预览
        </button>
        <button className="tool-button secondary" disabled={!toolPreview || isCalling} onClick={callTool} type="button">
          {isCalling ? <Loader2 className="spin" size={16} /> : <CheckCircle2 size={16} />}
          调用
        </button>
      </div>
      {latest ? (
        <div className="tool-result">
          <div className="metric-row">
            <span>状态</span>
            <strong>{translateStatus(latest.status)}</strong>
          </div>
          <div className="metric-row">
            <span>结果</span>
            <strong>{outputLabel}</strong>
          </div>
          <div className="metric-row">
            <span>运行</span>
            <strong>{latest.run_id || "仅预览"}</strong>
          </div>
        </div>
      ) : (
        <div className="empty-state">先预览参数，再调用只读的本地知识检索工具；正式调用会写入工作流审计。</div>
      )}
    </section>
  );
}

function RoutePanel({ lastChat }: { lastChat: ChatResponse | null }) {
  const routeRows: Array<[string, unknown]> = [
    ["实际角色", lastChat?.route.role],
    ["实际模式", lastChat?.route.mode],
    ["实际模型", lastChat?.route.model_profile],
    ["人工覆盖", lastChat?.route.manual_override],
    ["置信度", lastChat?.route.confidence],
    ["命中关键词", lastChat?.route.matched_keywords],
    ["LLM 路由", lastChat?.route.llm_router_used],
    ["路由原因", lastChat?.route.reason]
  ];
  return (
    <section className="panel" id="route">
      <div className="panel-header">
        <div>
          <h2>回答检查器</h2>
          <span>{lastChat ? `Session ${lastChat.session_id}` : "等待第一轮回答"}</span>
        </div>
        <Activity size={18} />
      </div>
      {lastChat ? (
        <div className="route-grid">
          {routeRows.map(([label, value]) => (
            <div className="metric-row" key={label}>
              <span>{label}</span>
              <strong title={displayValue(value)}>{displayValue(value)}</strong>
            </div>
          ))}
          <div className="metric-row">
            <span>RAG 状态</span>
            <strong>{translateStatus(lastChat.rag.status)}</strong>
          </div>
          <div className="metric-row">
            <span>引用数量</span>
            <strong>{lastChat.rag.result_count}</strong>
          </div>
        </div>
      ) : (
        <div className="empty-state">发送一条消息后，这里会展示后端返回的角色、模式、模型、路由原因和 RAG 状态。</div>
      )}
    </section>
  );
}

function SessionsPanel({ sessions }: { sessions: SessionRow[] }) {
  return (
    <section className="panel" id="sessions">
      <div className="panel-header">
        <div>
          <h2>会话历史</h2>
          <span>{sessions.length} 个会话文件</span>
        </div>
        <Clock3 size={18} />
      </div>
      {sessions.length ? (
        <div className="session-list">
          {sessions.slice(0, 5).map((session) => (
            <div className="session-row" key={`${session.kind}-${session.name}`}>
              <strong>{session.name}</strong>
              <span>{session.kind} · {formatBytes(session.size_bytes)} · {formatMtime(session.mtime_ns)}</span>
            </div>
          ))}
        </div>
      ) : (
        <div className="empty-state">还没有可展示的会话历史；新回答会先写入当前 session，后续可接入详情和继续会话 API。</div>
      )}
    </section>
  );
}

function RoadmapPanel() {
  return (
    <section className="panel compact" id="prd-roadmap">
      <div className="panel-header">
        <div>
          <h2>双版本对齐</h2>
          <span>按 PRD 保留能力边界</span>
        </div>
        <ShieldCheck size={18} />
      </div>
      <ul className="roadmap-list">
        {roadmapItems.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </section>
  );
}

function MemoryPanel({ memoryStatus }: { memoryStatus: MemoryStatusResponse | null }) {
  const focus = memoryStatus?.files.find((file) => file.name === "current_focus.md");
  const progress = memoryStatus?.files.find((file) => file.name === "progress.md");
  const summary = memoryStatus?.files.find((file) => file.name === "summary.md");
  return (
    <section className="panel compact" id="memory">
      <div className="panel-header">
        <div>
          <h2>学习记忆</h2>
          <span>{memoryStatus ? `${memoryStatus.context_mode} · ${memoryStatus.writable ? "可写" : "只读"}` : "等待 API"}</span>
        </div>
        <ShieldCheck size={18} />
      </div>
      {memoryStatus ? (
        <>
          <div className="memory-note">
            <StatusDot tone={memoryStatus.writable ? "good" : memoryStatus.safe_mode ? "bad" : "warn"} />
            <span>
              memory_mode={memoryStatus.memory_mode} · safe_mode={String(memoryStatus.safe_mode)} · reason={memoryStatus.reason}
            </span>
          </div>
          <div className="memory-grid">
            {[focus, progress, summary].map((file) =>
              file ? (
                <details className="memory-file" key={file.name}>
                  <summary>{file.name}</summary>
                  <p>{file.preview || "暂无内容"}</p>
                </details>
              ) : null
            )}
          </div>
        </>
      ) : (
        <div className="memory-note">
          <AlertTriangle size={16} />
          记忆状态接口暂不可用。
        </div>
      )}
    </section>
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
  isCalling
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
}) {
  return (
    <aside className="inspector">
      <RoutePanel lastChat={lastChat} />
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
      <MemoryPanel memoryStatus={snapshot.memoryStatus} />
    </aside>
  );
}

export default function App() {
  const [snapshot, setSnapshot] = useState<ApiSnapshot>(INITIAL_SNAPSHOT);
  const [messages, setMessages] = useState<ChatMessage[]>(seedMessages);
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
  const [loadingRunId, setLoadingRunId] = useState("");
  const [uploadState, setUploadState] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const runtimeHydratedRef = useRef(false);

  const activeQuery = input.trim() || lastChat?.rag.query || "本地资料 工作流 引用来源";

  const refresh = async () => {
    setSnapshot(await loadApiSnapshot());
  };

  useEffect(() => {
    const saved = window.localStorage.getItem("study-agent-react-session");
    if (saved) {
      try {
        const parsed = JSON.parse(saved) as {
          messages?: ChatMessage[];
          sessionId?: string;
          chatSettings?: ChatSettings;
          ragSettings?: RagSettings;
          ragEnabled?: boolean;
        };
        if (parsed.messages?.length) {
          setMessages(parsed.messages);
        }
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
        window.localStorage.removeItem("study-agent-react-session");
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
    setChatSettings({
      selectedRole: settings.selected_role,
      selectedMode: settings.selected_mode,
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
      "study-agent-react-session",
      JSON.stringify({ messages, sessionId, chatSettings, ragSettings, ragEnabled })
    );
  }, [messages, sessionId, chatSettings, ragSettings, ragEnabled]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const question = input.trim();
    if (!question || isSending) {
      return;
    }
    const nextMessages: ChatMessage[] = [...messages, { role: "user", content: question }];
    setMessages(nextMessages);
    setInput("");
    setIsSending(true);
    setRagSearch(null);
    try {
      const response = await sendChat(
        question,
        nextMessages.filter((message) => message.role !== "system"),
        { ragEnabled, sessionId, chatSettings, ragSettings }
      );
      setSessionId(response.session_id);
      setLastChat(response);
      setMessages([...nextMessages, { role: "assistant", content: response.reply }]);
      await refresh();
    } catch (error) {
      const message = error instanceof Error ? error.message : "聊天请求失败";
      setMessages([
        ...nextMessages,
        {
          role: "assistant",
          content: `请求失败：${message}`
        }
      ]);
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
      setMessages((current) => [
        ...current,
        {
          role: "assistant",
          content: `来源检索失败：${error instanceof Error ? error.message : "未知错误"}`
        }
      ]);
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
        messages={messages}
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
