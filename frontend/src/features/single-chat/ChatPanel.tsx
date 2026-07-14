import { Activity, ArrowDown, BookOpen, Clipboard, Database, Library, Loader2, LogOut, MemoryStick, MessageSquare, MoreHorizontal, Play, RotateCcw, Search, Send, Settings, Square, Upload, Wrench } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";
import { MarkdownMessage } from "../../components/MarkdownMessage";
import { RoleAvatar } from "../../components/RoleAvatar";
import { EvidenceTrail } from "../evidence/EvidenceTrail";
import { closureActionLabel, taskContractFromRoute, taskIntentLabel } from "../task/taskContract";
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
  const [copiedMessageIndex, setCopiedMessageIndex] = useState<number | null>(null);
  const currentFocus = memoryStatus?.latest_section || latestMemorySection(memoryStatus, "current_focus.md", "还没有记录当前学习重点。");
  const progress = latestMemorySection(memoryStatus, "progress.md", "还没有可恢复的最近进度。");
  const summary = latestMemorySection(memoryStatus, "summary.md", "完成几轮学习后，这里会显示长期摘要。");
  const hasConversationMessages = messages.some(
    (message) => message.role === "user" || (message.role === "assistant" && !message.transient)
  );
  const taskContract = taskContractFromRoute(lastChat?.route);
  const closureLabel = closureActionLabel(taskContract);
  const taskLabel = taskContract
    ? `${taskIntentLabel(taskContract.task_intent)}${taskContract.explicit_override ? " · 手动" : ""}`
    : "等待提问";

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

  const copyMessage = async (content: string, index: number) => {
    try {
      await navigator.clipboard.writeText(content);
      setCopiedMessageIndex(index);
      window.setTimeout(() => {
        setCopiedMessageIndex((current) => (current === index ? null : current));
      }, 1600);
    } catch {
      // Clipboard permission or browser support may be unavailable.
    }
  };

  const handleComposerKeyDown = (event: ReactKeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault();
    if (!isSending && input.trim()) {
      event.currentTarget.form?.requestSubmit();
    }
  };

  const openFromMenu = (drawer: DrawerId, target: HTMLButtonElement) => {
    target.closest("details")?.removeAttribute("open");
    onOpenDrawer(drawer);
  };

  useEffect(() => {
    if (isAtBottom) {
      bottomRef.current?.scrollIntoView({ block: "end" });
    }
  }, [messages, streamRecovery, isAtBottom]);

  return (
    <main className="chat-panel" id="chat">
      <header className="topbar">
        <div className="topbar-copy">
          <h1>学习工作台</h1>
          <p>围绕目标提问；需要资料时再调用本地检索或联网证据，结果由你确认后写入记忆。</p>
          <div className="topbar-meta" aria-label="当前学习状态">
            <span>任务 {taskLabel}</span>
            <span>资料 {ragEnabled ? "按需检索" : "未启用"}</span>
            <span>会话 {sessionId ? "进行中" : "未开始"}</span>
          </div>
        </div>
        <div className="topbar-actions" aria-label="学习工作台操作">
          {closureLabel ? (
            <button
              aria-label={closureLabel}
              className="end-session-button"
              disabled={isEndingSession || isSending || !messages.some((m) => m.role === "user")}
              onClick={onEndSession}
              type="button"
              title="生成结果整理候选（确认后才写入）"
            >
              {isEndingSession ? <Loader2 className="spin" size={14} /> : <LogOut size={14} />}
              {closureLabel}
            </button>
          ) : null}
          <button aria-label="上传学习资料" className="icon-button" onClick={onUploadClick} type="button" title="上传学习资料">
            <Upload size={17} />
          </button>
          <button aria-label="打开会话历史" className="icon-button session-dock-button" onClick={() => onOpenDrawer("sessions")} type="button" title="会话历史">
            <BookOpen size={16} />
          </button>
          <button aria-label="打开引用来源与知识库" className="icon-button" onClick={() => onOpenDrawer("sources")} type="button" title="引用来源与知识库">
            <Library size={16} />
          </button>
          <button aria-label="打开设置" className="icon-button" onClick={() => onOpenDrawer("settings")} type="button" title="设置">
            <Settings size={16} />
          </button>
          <details className="workspace-menu">
            <summary aria-label="打开更多学习工具" className="workspace-menu-trigger" title="更多学习工具">
              <MoreHorizontal size={18} />
              <span>更多</span>
            </summary>
            <div className="workspace-menu-popover" role="menu">
              <button onClick={(event) => openFromMenu("group", event.currentTarget)} role="menuitem" type="button">
                <MessageSquare size={16} />
                <span><strong>群聊讨论</strong><small>让多位角色从不同角度讨论</small></span>
              </button>
              <button onClick={(event) => openFromMenu("news", event.currentTarget)} role="menuitem" type="button">
                <Database size={16} />
                <span><strong>新闻研究</strong><small>检索公开信息并保留来源</small></span>
              </button>
              <button onClick={(event) => openFromMenu("tools", event.currentTarget)} role="menuitem" type="button">
                <Wrench size={16} />
                <span><strong>受控工具</strong><small>预览并运行本地知识工具</small></span>
              </button>
              <button onClick={(event) => openFromMenu("memory", event.currentTarget)} role="menuitem" type="button">
                <MemoryStick size={16} />
                <span><strong>学习记忆</strong><small>预览和确认长期记忆写入</small></span>
              </button>
              <button onClick={(event) => openFromMenu("timeline", event.currentTarget)} role="menuitem" type="button">
                <Activity size={16} />
                <span><strong>工作流记录</strong><small>查看任务执行阶段与失败原因</small></span>
              </button>
            </div>
          </details>
        </div>
      </header>

      <section className="conversation" aria-label="学习对话" onScroll={updateScrollState} ref={conversationRef}>
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
                {message.role === "assistant" && message.content ? (
                  <button
                    aria-label="复制回答正文"
                    className="ghost-action compact message-copy-button"
                    onClick={() => void copyMessage(message.content, index)}
                    type="button"
                  >
                    <Clipboard size={13} />
                    {copiedMessageIndex === index ? "已复制" : "复制"}
                  </button>
                ) : null}
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
          aria-label="输入学习问题"
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={handleComposerKeyDown}
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
