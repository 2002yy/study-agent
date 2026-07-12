import { Activity, ArrowDown, BookOpen, Clipboard, Database, Library, Loader2, LogOut, MemoryStick, MessageSquare, Play, RotateCcw, Search, Send, Settings, Square, Upload, Wrench } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { MarkdownMessage } from "../../components/MarkdownMessage";
import { RoleAvatar } from "../../components/RoleAvatar";
import { EvidenceTrail } from "../evidence/EvidenceTrail";
import type { ChatMessage, ChatResponse, DrawerId, MemoryStatusResponse } from "../../types";
import { roleLabel } from "../roles/roleCatalog";

const quickPrompts = [
  "继续上次学习，先给我一个下一步建议",
  "根据当前学习重点，帮我安排今天 25 分钟",
  "我想开始一个新主题，先帮我拆学习路径"
];

export function latestMemorySection(memoryStatus: MemoryStatusResponse | null, name: string, fallback: string): string {
  const preview = memoryStatus?.files.find((file) => file.name === name)?.preview.trim();
  if (!preview) {
    return fallback;
  }
  const sections = preview
    .split(/\n(?=#{1,6}\s+)/)
    .map((section) => section.trim())
    .filter(Boolean);
  return sections.length ? sections[sections.length - 1] : preview;
}

export function ChatPanel({
  messages,
  sessionId,
  input,
  setInput,
  isSending,
  onSubmit,
  onStop,
  streamRecovery,
  onContinueInterruptedReply,
  onRetry,
  onCopyInterruptedReply,
  onUploadClick,
  onSearchSources,
  isSearching,
  hasSearchQuery,
  onQuickPrompt,
  lastChat,
  ragEnabled,
  memoryStatus,
  onOpenDrawer,
  onEndSession,
  isEndingSession
}: {
  messages: ChatMessage[];
  sessionId?: string;
  input: string;
  setInput: (value: string) => void;
  isSending: boolean;
  onSubmit: (event: FormEvent) => void;
  onStop: () => void;
  streamRecovery: { question: string; reply: string; reason: string; sessionId?: string; turnId?: string | null } | null;
  onContinueInterruptedReply: () => void;
  onRetry: () => void;
  onCopyInterruptedReply: () => void;
  onUploadClick: () => void;
  onSearchSources: () => void;
  isSearching: boolean;
  hasSearchQuery: boolean;
  onQuickPrompt: (value: string) => void;
  lastChat: ChatResponse | null;
  ragEnabled: boolean;
  memoryStatus: MemoryStatusResponse | null;
  onOpenDrawer: (drawer: DrawerId) => void;
  onEndSession: () => void;
  isEndingSession?: boolean;
}) {
  const conversationRef = useRef<HTMLElement | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const [isAtBottom, setIsAtBottom] = useState(true);
  const currentFocus = memoryStatus?.latest_section || latestMemorySection(memoryStatus, "current_focus.md", "还没有记录当前学习重点。");
  const progress = latestMemorySection(memoryStatus, "progress.md", "还没有可恢复的最近进度。");
  const summary = latestMemorySection(memoryStatus, "summary.md", "完成几轮学习后，这里会显示长期摘要。");
  const hasConversationMessages = messages.some(
    (message) => message.role === "user" || (message.role === "assistant" && !message.transient)
  );

  const updateScrollState = () => {
    const element = conversationRef.current;
    if (!element) {
      return;
    }
    const distanceFromBottom = element.scrollHeight - element.scrollTop - element.clientHeight;
    setIsAtBottom(distanceFromBottom < 80);
  };

  const scrollToLatest = () => {
    bottomRef.current?.scrollIntoView({ block: "end", behavior: "smooth" });
    setIsAtBottom(true);
  };

  useEffect(() => {
    if (isAtBottom) {
      bottomRef.current?.scrollIntoView({ block: "end" });
    }
  }, [messages, streamRecovery, isAtBottom]);

  return (
    <main className="chat-panel" id="chat">
      <header className="topbar">
        <div>
          <h1>学习工作台</h1>
          <p>提问、检索本地资料、检查执行链路，再决定哪些内容写入记忆。</p>
          <div className="topbar-meta">
            <span>RAG {ragEnabled ? "已启用" : "未启用"}</span>
            <span>路由 {lastChat?.route?.mode ? `${lastChat.route.mode} · ${lastChat.route.role ?? "auto"}` : "等待提问"}</span>
            <span>记录 ID {sessionId ?? "未开始"}</span>
          </div>
        </div>
        <div className="topbar-actions">
          <button
            className="end-session-button"
            disabled={isEndingSession || isSending || !messages.some((m) => m.role === "user")}
            onClick={onEndSession}
            type="button"
            title="生成课后总结候选（确认后才写入）"
          >
            {isEndingSession ? <Loader2 className="spin" size={14} /> : <LogOut size={14} />}
            整理学习
          </button>
          <button className="icon-button" onClick={onUploadClick} type="button" title="上传资料">
            <Upload size={17} />
          </button>
          <button className="icon-button" disabled={!hasSearchQuery} onClick={onSearchSources} type="button" title={hasSearchQuery ? "检索来源" : "输入关键词或通过 RAG 提问后可检索"}>
            {isSearching ? <Loader2 className="spin" size={17} /> : <Search size={17} />}
          </button>
          <span className="dock-divider" />
          <button className="icon-button session-dock-button" onClick={() => onOpenDrawer("sessions")} type="button" title="会话历史"><BookOpen size={16} /></button>
          <button className="icon-button" onClick={() => onOpenDrawer("group")} type="button" title="群聊"><MessageSquare size={16} /></button>
          <button className="icon-button" onClick={() => onOpenDrawer("news")} type="button" title="新闻"><Database size={16} /></button>
          <button className="icon-button" onClick={() => onOpenDrawer("tools")} type="button" title="工具"><Wrench size={16} /></button>
          <button className="icon-button" onClick={() => onOpenDrawer("memory")} type="button" title="记忆"><MemoryStick size={16} /></button>
          <button className="icon-button" onClick={() => onOpenDrawer("sources")} type="button" title="引用来源与知识库"><Library size={16} /></button>
          <button className="icon-button" onClick={() => onOpenDrawer("timeline")} type="button" title="工作流时间线"><Activity size={16} /></button>
          <button className="icon-button" onClick={() => onOpenDrawer("settings")} type="button" title="设置"><Settings size={16} /></button>
        </div>
      </header>

      <section className="conversation" aria-label="Conversation" onScroll={updateScrollState} ref={conversationRef}>
        <details className="home-brief" key={hasConversationMessages ? "collapsed-home-brief" : "expanded-home-brief"} open={!hasConversationMessages}>
          <summary>
            <span>继续学习</span>
            {hasConversationMessages ? <small>已折叠</small> : null}
          </summary>
          <div>
            <p>先从你的记忆和最近进度恢复上下文；需要资料时再打开本地检索或联网来源。</p>
            <div className="learning-snapshot">
              <div>
                <span>当前学习重点</span>
                <strong>{currentFocus}</strong>
              </div>
              <div>
                <span>上次停在哪里</span>
                <strong>{progress}</strong>
              </div>
              <div>
                <span>长期摘要</span>
                <strong>{summary}</strong>
              </div>
            </div>
          </div>
          <div className="quick-grid">
            {quickPrompts.map((prompt) => (
              <button key={prompt} onClick={() => onQuickPrompt(prompt)} type="button">
                {prompt}
              </button>
            ))}
          </div>
        </details>
        {messages.map((message, index) => {
          const avatarRole = message.avatarRole ?? (message.role === "user" ? "user" : "auto");
          const label = message.role === "user" ? "你" : roleLabel(avatarRole);
          return (
            <article className={`message ${message.role}`} key={`${message.role}-${index}`}>
              <RoleAvatar fallback={message.role === "user" ? "user" : "assistant"} roleId={avatarRole} />
              <div className="message-body">
                <span>{label}</span>
                <MarkdownMessage content={message.content} />
                {message.role === "assistant" && message.evidence ? <EvidenceTrail evidence={message.evidence} /> : null}
              </div>
            </article>
          );
        })}
        <div ref={bottomRef} />
      </section>
      {!isAtBottom ? (
        <button className="back-to-latest" onClick={scrollToLatest} type="button">
          <ArrowDown size={14} />
          回到最新
        </button>
      ) : null}

      {streamRecovery ? (
        <div className="stream-recovery">
          <div>
            <strong>生成已中断</strong>
            <span>{streamRecovery.reason}</span>
          </div>
          <button
            className="ghost-action compact"
            disabled={isSending || !streamRecovery.reply}
            onClick={onContinueInterruptedReply}
            type="button"
          >
            <Play size={14} />
            继续生成
          </button>
          <button className="ghost-action compact" disabled={isSending} onClick={onRetry} type="button">
            <RotateCcw size={14} />
            重试
          </button>
          <button
            className="ghost-action compact"
            disabled={!streamRecovery.reply}
            onClick={onCopyInterruptedReply}
            type="button"
          >
            <Clipboard size={14} />
            复制已有内容
          </button>
        </div>
      ) : null}

      <form className="composer" onSubmit={onSubmit}>
        <textarea
          aria-label="Message"
          onChange={(event) => setInput(event.target.value)}
          placeholder="输入你的问题，或让本地资料帮你解释一个概念..."
          value={input}
        />
        {isSending ? (
          <button className="send-button stop-button" onClick={onStop} type="button">
            <Square size={16} />
            停止
          </button>
        ) : (
          <button className="send-button" disabled={!input.trim()} type="submit">
            <Send size={17} />
            发送
          </button>
        )}
      </form>
    </main>
  );
}
