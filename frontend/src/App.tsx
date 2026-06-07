import {
  Activity,
  AlertTriangle,
  BookOpen,
  Bot,
  BrainCircuit,
  CheckCircle2,
  Database,
  FileText,
  ListChecks,
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
import { FormEvent, useEffect, useMemo, useState } from "react";
import { loadApiSnapshot, previewLocalKnowledge, sendChat } from "./api";
import type { ApiSnapshot, ChatMessage, ChatResponse, ToolInvocationResponse } from "./types";

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
      "Study Agent console is ready. Ask a study question, inspect local sources, and watch tool/workflow state from the right panel."
  }
];

function StatusDot({ tone = "neutral" }: { tone?: "good" | "warn" | "neutral" | "bad" }) {
  return <span className={`status-dot ${tone}`} />;
}

function Sidebar({
  snapshot,
  ragEnabled,
  setRagEnabled,
  refresh
}: {
  snapshot: ApiSnapshot;
  ragEnabled: boolean;
  setRagEnabled: (value: boolean) => void;
  refresh: () => void;
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
          <span>Local console</span>
        </div>
      </div>

      <button className="primary-action" type="button">
        <MessageSquare size={17} />
        New study thread
      </button>

      <nav className="nav-list" aria-label="Workspace navigation">
        <a className="active" href="#chat">
          <MessageSquare size={16} />
          Chat
        </a>
        <a href="#sources">
          <BookOpen size={16} />
          Sources
        </a>
        <a href="#timeline">
          <Activity size={16} />
          Timeline
        </a>
        <a href="#tools">
          <Wrench size={16} />
          Tools
        </a>
        <a href="#memory">
          <MemoryStick size={16} />
          Memory
        </a>
      </nav>

      <section className="side-section">
        <div className="section-title">
          <Database size={15} />
          RAG index
        </div>
        <div className="metric-row">
          <span>Documents</span>
          <strong>{snapshot.ragStatus?.documents ?? "?"}</strong>
        </div>
        <div className="metric-row">
          <span>Chunks</span>
          <strong>{snapshot.ragStatus?.chunks ?? "?"}</strong>
        </div>
        <div className="metric-row">
          <span>Backend</span>
          <strong>{snapshot.ragStatus?.vector_backend.name ?? "unknown"}</strong>
        </div>
      </section>

      <section className="side-section">
        <div className="section-title">
          <Settings size={15} />
          Run mode
        </div>
        <label className="toggle-row">
          <input checked={ragEnabled} onChange={(event) => setRagEnabled(event.target.checked)} type="checkbox" />
          <span>Use local knowledge</span>
        </label>
        <div className="status-line">
          <StatusDot tone={apiTone} />
          <span>{snapshot.health?.service ?? "API offline"}</span>
        </div>
      </section>

      <button className="ghost-action" onClick={refresh} type="button">
        <RefreshCw size={16} />
        Refresh API state
      </button>
    </aside>
  );
}

function ChatPanel({
  messages,
  input,
  setInput,
  isSending,
  onSubmit
}: {
  messages: ChatMessage[];
  input: string;
  setInput: (value: string) => void;
  isSending: boolean;
  onSubmit: (event: FormEvent) => void;
}) {
  return (
    <main className="chat-panel" id="chat">
      <header className="topbar">
        <div>
          <h1>Study workspace</h1>
          <p>Ask, retrieve local evidence, inspect workflow state, then decide what becomes memory.</p>
        </div>
        <div className="topbar-actions">
          <button className="icon-button" type="button" title="Upload documents">
            <Upload size={17} />
          </button>
          <button className="icon-button" type="button" title="Search sources">
            <Search size={17} />
          </button>
        </div>
      </header>

      <section className="conversation" aria-label="Conversation">
        {messages.map((message, index) => (
          <article className={`message ${message.role}`} key={`${message.role}-${index}`}>
            <div className="avatar">{message.role === "user" ? <User size={16} /> : <Bot size={16} />}</div>
            <div className="message-body">
              <span>{message.role === "user" ? "You" : "Study Agent"}</span>
              <p>{message.content}</p>
            </div>
          </article>
        ))}
      </section>

      <form className="composer" onSubmit={onSubmit}>
        <textarea
          aria-label="Message"
          onChange={(event) => setInput(event.target.value)}
          placeholder="Ask about your local notes, a RAG design choice, or the next study step..."
          value={input}
        />
        <button className="send-button" disabled={isSending || !input.trim()} type="submit">
          <Send size={17} />
          {isSending ? "Sending" : "Send"}
        </button>
      </form>
    </main>
  );
}

function Inspector({
  snapshot,
  lastChat,
  toolPreview,
  previewTool,
  isPreviewing
}: {
  snapshot: ApiSnapshot;
  lastChat: ChatResponse | null;
  toolPreview: ToolInvocationResponse | null;
  previewTool: () => void;
  isPreviewing: boolean;
}) {
  const sources = useMemo(() => {
    const text = lastChat?.rag.sources.trim();
    return text ? text.split("\n") : [];
  }, [lastChat]);

  return (
    <aside className="inspector">
      <section className="panel" id="sources">
        <div className="panel-header">
          <div>
            <h2>Sources</h2>
            <span>{lastChat?.rag.status ?? "waiting"}</span>
          </div>
          <FileText size={18} />
        </div>
        {sources.length ? (
          <ul className="source-list">
            {sources.map((source) => (
              <li key={source}>{source}</li>
            ))}
          </ul>
        ) : (
          <div className="empty-state">No cited source block yet. Enable local knowledge and send a grounded question.</div>
        )}
      </section>

      <section className="panel" id="timeline">
        <div className="panel-header">
          <div>
            <h2>Workflow timeline</h2>
            <span>{snapshot.workflowRuns.length} recent runs</span>
          </div>
          <ListChecks size={18} />
        </div>
        <div className="timeline">
          {snapshot.workflowRuns.length ? (
            snapshot.workflowRuns.slice(0, 4).map((run) => (
              <div className="timeline-row" key={run.run_id}>
                <StatusDot tone={run.status === "succeeded" ? "good" : run.status === "failed" ? "bad" : "warn"} />
                <div>
                  <strong>{run.workflow_name}</strong>
                  <span>{run.run_id}</span>
                </div>
                <em>{run.elapsed_ms} ms</em>
              </div>
            ))
          ) : (
            <div className="empty-state">No workflow audit events yet.</div>
          )}
        </div>
      </section>

      <section className="panel" id="tools">
        <div className="panel-header">
          <div>
            <h2>Tool preview</h2>
            <span>{snapshot.tools.length} allowlisted</span>
          </div>
          <Wrench size={18} />
        </div>
        <button className="tool-button" onClick={previewTool} type="button">
          <Sparkles size={16} />
          {isPreviewing ? "Previewing" : "Preview retrieve_local_knowledge"}
        </button>
        {toolPreview ? (
          <div className="tool-result">
            <div className="metric-row">
              <span>Status</span>
              <strong>{toolPreview.status}</strong>
            </div>
            <div className="metric-row">
              <span>Reason</span>
              <strong>{toolPreview.reason || "ready"}</strong>
            </div>
          </div>
        ) : (
          <div className="empty-state">Tool calls stay visible before agentic behavior expands.</div>
        )}
      </section>

      <section className="panel compact" id="memory">
        <div className="panel-header">
          <div>
            <h2>Memory candidate</h2>
            <span>preview-first</span>
          </div>
          <ShieldCheck size={18} />
        </div>
        <div className="memory-note">
          <CheckCircle2 size={16} />
          Memory writes remain gated by preview and runtime mode.
        </div>
      </section>
    </aside>
  );
}

export default function App() {
  const [snapshot, setSnapshot] = useState<ApiSnapshot>(INITIAL_SNAPSHOT);
  const [messages, setMessages] = useState<ChatMessage[]>(seedMessages);
  const [input, setInput] = useState("根据本地资料解释 RAG workflow timeline 的作用");
  const [ragEnabled, setRagEnabled] = useState(true);
  const [isSending, setIsSending] = useState(false);
  const [isPreviewing, setIsPreviewing] = useState(false);
  const [sessionId, setSessionId] = useState<string | undefined>();
  const [lastChat, setLastChat] = useState<ChatResponse | null>(null);
  const [toolPreview, setToolPreview] = useState<ToolInvocationResponse | null>(null);

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
      const message = error instanceof Error ? error.message : "Chat request failed";
      setMessages([
        ...nextMessages,
        {
          role: "assistant",
          content: `Request failed: ${message}`
        }
      ]);
    } finally {
      setIsSending(false);
    }
  };

  const previewTool = async () => {
    setIsPreviewing(true);
    try {
      setToolPreview(await previewLocalKnowledge(input || "local knowledge workflow evidence"));
    } catch (error) {
      setToolPreview({
        tool_name: "retrieve_local_knowledge",
        status: "failed",
        output: {},
        reason: error instanceof Error ? error.message : "preview failed",
        elapsed_ms: 0,
        run_id: ""
      });
    } finally {
      setIsPreviewing(false);
    }
  };

  return (
    <div className="app-shell">
      <Sidebar snapshot={snapshot} ragEnabled={ragEnabled} setRagEnabled={setRagEnabled} refresh={refresh} />
      <ChatPanel messages={messages} input={input} setInput={setInput} isSending={isSending} onSubmit={submit} />
      <Inspector
        snapshot={snapshot}
        lastChat={lastChat}
        toolPreview={toolPreview}
        previewTool={previewTool}
        isPreviewing={isPreviewing}
      />
      {snapshot.error ? (
        <div className="api-warning">
          <AlertTriangle size={16} />
          API unavailable: {snapshot.error}
        </div>
      ) : null}
    </div>
  );
}
