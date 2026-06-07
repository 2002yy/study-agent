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
  loadWorkflowRun,
  previewLocalKnowledge,
  queryRag,
  sendChat,
  uploadDocuments
} from "./api";
import type {
  ApiSnapshot,
  ChatMessage,
  ChatResponse,
  RagDebugResult,
  RagQueryResponse,
  RagResult,
  ToolInvocationResponse,
  WorkflowRunDetail,
  WorkflowRunSummary
} from "./types";

const INITIAL_SNAPSHOT: ApiSnapshot = {
  health: null,
  ragStatus: null,
  tools: [],
  workflowRuns: [],
  error: ""
};

const seedMessages: ChatMessage[] = [
  {
    role: "assistant",
    content:
      "本地学习工作台已就绪。你可以提问、上传资料、查看引用来源，并在右侧检查工具调用与工作流状态。"
  }
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
  refresh,
  onUploadClick,
  uploadState
}: {
  snapshot: ApiSnapshot;
  ragEnabled: boolean;
  setRagEnabled: (value: boolean) => void;
  refresh: () => void;
  onUploadClick: () => void;
  uploadState: string;
}) {
  const apiTone = snapshot.health?.status === "ok" ? "good" : snapshot.error ? "bad" : "neutral";
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
          运行模式
        </div>
        <label className="toggle-row">
          <input checked={ragEnabled} onChange={(event) => setRagEnabled(event.target.checked)} type="checkbox" />
          <span>用于聊天回答</span>
        </label>
        <div className="status-line">
          <StatusDot tone={apiTone} />
          <span>{snapshot.health?.service ?? "API 未连接"}</span>
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
  isSearching
}: {
  messages: ChatMessage[];
  input: string;
  setInput: (value: string) => void;
  isSending: boolean;
  onSubmit: (event: FormEvent) => void;
  onUploadClick: () => void;
  onSearchSources: () => void;
  isSearching: boolean;
}) {
  return (
    <main className="chat-panel" id="chat">
      <header className="topbar">
        <div>
          <h1>学习工作台</h1>
          <p>提问、检索本地资料、检查执行链路，再决定哪些内容写入记忆。</p>
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
              </div>
              <span>{formatScore(row.score)}</span>
            </div>
          ))}
        </div>
      ) : (
        <div className="empty-state">还没有引用来源。开启“用于聊天回答”后提问，或点击顶部检索按钮。</div>
      )}
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
      <section className="panel compact" id="memory">
        <div className="panel-header">
          <div>
            <h2>记忆候选</h2>
            <span>先预览再写入</span>
          </div>
          <ShieldCheck size={18} />
        </div>
        <div className="memory-note">
          <CheckCircle2 size={16} />
          记忆写入仍受预览确认与运行模式保护。
        </div>
      </section>
    </aside>
  );
}

export default function App() {
  const [snapshot, setSnapshot] = useState<ApiSnapshot>(INITIAL_SNAPSHOT);
  const [messages, setMessages] = useState<ChatMessage[]>(seedMessages);
  const [input, setInput] = useState("根据本地资料解释 RAG 工作流时间线的作用");
  const [ragEnabled, setRagEnabled] = useState(true);
  const [isSending, setIsSending] = useState(false);
  const [isPreviewing, setIsPreviewing] = useState(false);
  const [isCalling, setIsCalling] = useState(false);
  const [isSearching, setIsSearching] = useState(false);
  const [sessionId, setSessionId] = useState<string | undefined>();
  const [lastChat, setLastChat] = useState<ChatResponse | null>(null);
  const [ragSearch, setRagSearch] = useState<RagQueryResponse | null>(null);
  const [toolPreview, setToolPreview] = useState<ToolInvocationResponse | null>(null);
  const [toolCall, setToolCall] = useState<ToolInvocationResponse | null>(null);
  const [selectedRun, setSelectedRun] = useState<WorkflowRunDetail | null>(null);
  const [loadingRunId, setLoadingRunId] = useState("");
  const [uploadState, setUploadState] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  const activeQuery = input.trim() || lastChat?.rag.query || "本地资料 工作流 引用来源";

  const refresh = async () => {
    setSnapshot(await loadApiSnapshot());
  };

  useEffect(() => {
    void refresh();
  }, []);

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
        { ragEnabled, sessionId }
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
      setRagSearch(await queryRag(activeQuery));
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
        refresh={refresh}
        onUploadClick={() => fileInputRef.current?.click()}
        uploadState={uploadState}
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
