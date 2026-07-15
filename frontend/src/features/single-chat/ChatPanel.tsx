import { Activity, ArrowDown, BookOpen, Clipboard, Database, Library, Loader2, LogOut, MemoryStick, MessageSquare, MoreHorizontal, Search, Send, Settings, Square, Upload, Wrench } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";
import { MarkdownMessage } from "../../components/MarkdownMessage";
import { RoleAvatar } from "../../components/RoleAvatar";
import { EvidenceTrail } from "../evidence/EvidenceTrail";
import { ChatResearchRecovery } from "../web-lookup/ChatResearchRecovery";
import type { ResearchLookupResponse } from "../web-lookup/researchApi";
import type { SemanticSessionRow } from "../sessions/sessionNavigation";
import {
  TURN_TASK_INTENT_OPTIONS,
  clearPendingTaskIntentOverride,
  closureActionLabel,
  setPendingTaskIntentOverride,
  taskContractFromRoute,
  taskIntentLabel,
  type TaskIntent,
} from "../task/taskContract";
import type { ChatMessage, ChatResponse, DrawerId, MemoryStatusResponse } from "../../types";
import { roleLabel } from "../roles/roleCatalog";
import { RestoreCard } from "./RestoreCard";

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
  sessionNavigation,
  input,
  setInput,
  isSending,
  onSubmit,
  onStop,
  streamRecovery,
  onContinueInterruptedReply,
  onRetry,
  onAbandonInterruptedReply,
  onCopyInterruptedReply,
  onUploadClick,
  onSearchSources,
  isSearching,
  hasSearchQuery,
  onQuickPrompt,
  onStartNewTopic,
  lastChat,
  ragEnabled,
  memoryStatus,
  onOpenDrawer,
  onEndSession,
  isEndingSession,
  researchRun,
  isResearchBusy,
  canRetryResearch,
  canResumeResearch,
  useResearchInChat,
  onRetryResearch,
  onResumeResearch,
}: {
  messages: ChatMessage[];
  sessionId?: string;
  sessionNavigation: SemanticSessionRow | null;
  input: string;
  setInput: (value: string) => void;
  isSending: boolean;
  onSubmit: (event: FormEvent) => void | Promise<void>;
  onStop: () => void;
  streamRecovery: { question: string; reply: string; reason: string; sessionId?: string; turnId?: string | null } | null;
  onContinueInterruptedReply: () => void;
  onRetry: () => void;
  onAbandonInterruptedReply: () => Promise<void> | void;
  onCopyInterruptedReply: () => void;
  onUploadClick: () => void;
  onSearchSources: () => void;
  isSearching: boolean;
  hasSearchQuery: boolean;
  onQuickPrompt: (value: string) => void;
  onStartNewTopic: () => void;
  lastChat: ChatResponse | null;
  ragEnabled: boolean;
  memoryStatus: MemoryStatusResponse | null;
  onOpenDrawer: (drawer: DrawerId) => void;
  onEndSession: () => void;
  isEndingSession?: boolean;
  researchRun: ResearchLookupResponse | null;
  isResearchBusy: boolean;
  canRetryResearch: boolean;
  canResumeResearch: boolean;
  useResearchInChat: boolean;
  onRetryResearch: () => void;
  onResumeResearch: () => void;
}) {
  const conversationRef = useRef<HTMLElement | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const [isAtBottom, setIsAtBottom] = useState(true);
  const [copiedMessageIndex, setCopiedMessageIndex] = useState<number | null>(null);
  const [taskIntentOverride, setTaskIntentOverride] = useState<"" | TaskIntent>("");
  const taskContract = taskContractFromRoute(lastChat?.route);
  const closureLabel = closureActionLabel(taskContract);
  const taskLabel = taskContract
    ? `${taskIntentLabel(taskContract.task_intent)}${taskContract.explicit_override ? " · 手动" : ""}`
    : "等待提问";
  const selectedTaskIntent = TURN_TASK_INTENT_OPTIONS.find(
    (option) => option.value === taskIntentOverride
  ) ?? TURN_TASK_INTENT_OPTIONS[0];
  const displayMessages = sessionNavigation?.has_completed_turns
    ? messages
    : messages.filter(
        (message) =>
          !(
            message.role === "assistant" &&
            message.transient &&
            !message.turnId
          )
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

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (isSending || !input.trim()) return;
    setPendingTaskIntentOverride(taskIntentOverride || undefined);
    try {
      await onSubmit(event);
    } finally {
      clearPendingTaskIntentOverride();
      setTaskIntentOverride("");
    }
  };

  const handleRestoreEntry = (intent: TaskIntent, prompt: string) => {
    setTaskIntentOverride(intent);
    onQuickPrompt(prompt);
  };

  const closeWorkspaceMenu = (target: HTMLButtonElement) => {
    const menu = target.closest("details");
    menu?.removeAttribute("open");
    menu?.querySelector<HTMLElement>("summary")?.focus();
  };

  const openFromMenu = (drawer: DrawerId, target: HTMLButtonElement) => {
    closeWorkspaceMenu(target);
    onOpenDrawer(drawer);
  };

  const searchFromMenu = (target: HTMLButtonElement) => {
    closeWorkspaceMenu(target);
    onSearchSources();
  };

  useEffect(() => {
    if (isAtBottom) {
      bottomRef.current?.scrollIntoView({ block: "end" });
    }
  }, [messages, streamRecovery, isAtBottom]);

  useEffect(() => {
    clearPendingTaskIntentOverride();
    setTaskIntentOverride("");
    return clearPendingTaskIntentOverride;
  }, [sessionId]);

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
          <details className="workspace-menu">
            <summary aria-label="打开更多学习工具" className="workspace-menu-trigger" title="更多学习工具">
              <MoreHorizontal size={18} />
              <span>更多</span>
            </summary>
            <div className="workspace-menu-popover" role="menu">
              <button
                aria-label="检索当前问题的资料来源"
                disabled={!hasSearchQuery}
                onClick={(event) => searchFromMenu(event.currentTarget)}
                role="menuitem"
                type="button"
              >
                {isSearching ? <Loader2 className="spin" size={16} /> : <Search size={16} />}
                <span>
                  <strong>检索当前问题</strong>
                  <small>{hasSearchQuery ? "查找本地资料与可用来源" : "输入问题后即可检索资料来源"}</small>
                </span>
              </button>
              <button onClick={(event) => openFromMenu("sources", event.currentTarget)} role="menuitem" type="button">
                <Library size={16} />
                <span><strong>引用来源</strong><small>查看本次引用与长期知识库</small></span>
              </button>
              <button onClick={(event) => openFromMenu("settings", event.currentTarget)} role="menuitem" type="button">
                <Settings size={16} />
                <span><strong>设置</strong><small>调整角色、模型与检索策略</small></span>
              </button>
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
        <RestoreCard
          session={sessionNavigation}
          streamRecovery={streamRecovery}
          onSelectEntry={handleRestoreEntry}
          onUpload={onUploadClick}
          onContinueHere={onQuickPrompt}
          onStartNewTopic={onStartNewTopic}
          onContinueInterrupted={onContinueInterruptedReply}
          onRetryInterrupted={onRetry}
          onAbandonInterrupted={onAbandonInterruptedReply}
        />
        {displayMessages.map((message, index) => {
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

      {streamRecovery?.reply ? (
        <div className="interrupted-copy-shortcut">
          <span>部分回答已保留；恢复、重试或放弃请使用上方恢复卡。</span>
          <button
            className="ghost-action compact"
            disabled={isSending}
            onClick={onCopyInterruptedReply}
            type="button"
          >
            <Clipboard size={14} />
            复制已有内容
          </button>
        </div>
      ) : null}

      <ChatResearchRecovery
        run={researchRun}
        isBusy={isResearchBusy}
        canRetry={canRetryResearch}
        canResume={canResumeResearch}
        useInChat={useResearchInChat}
        onRetry={onRetryResearch}
        onResume={onResumeResearch}
      />

      <form className="composer" onSubmit={handleSubmit}>
        <div className="composer-main">
          <label className="turn-intent-control">
            <span>下一条按</span>
            <select
              aria-label="下一条消息的任务类型"
              disabled={isSending}
              onChange={(event) => setTaskIntentOverride(event.target.value as "" | TaskIntent)}
              value={taskIntentOverride}
            >
              {TURN_TASK_INTENT_OPTIONS.map((option) => (
                <option key={option.value || "auto"} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <small>{selectedTaskIntent.description}；仅影响下一条新消息</small>
          </label>
          <textarea
            aria-label="输入学习问题"
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={handleComposerKeyDown}
            placeholder="输入你的问题，或让本地资料帮你解释一个概念..."
            value={input}
          />
        </div>
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
