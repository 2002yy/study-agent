import {
  ArrowDown,
  BookOpen,
  Clipboard,
  Send,
  Search,
  MessageSquare,
  Square,
} from "lucide-react";
import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";

import { MarkdownMessage } from "../../components/MarkdownMessage";
import { RoleAvatar } from "../../components/RoleAvatar";
import { useReadingWorkspace } from "../reading/ReadingContext";
import type {
  ChatMessage,
  ChatResearchProgress,
  ChatResponse,
  DrawerId,
  MemoryStatusResponse,
} from "../../types";
import { EvidenceTrail } from "../evidence/EvidenceTrail";
import { roleLabel } from "../roles/roleCatalog";
import type { SemanticSessionRow } from "../sessions/sessionNavigation";
import {
  clearPendingTaskIntentOverride,
  taskContractFromRoute,
  taskIntentLabel,
  type TaskIntent,
} from "../task/taskContract";
import { ChatResearchRecovery } from "../web-lookup/ChatResearchRecovery";
import type { ResearchLookupResponse } from "../web-lookup/researchApi";
import { RestoreCard } from "./RestoreCard";

// A search is an explicit chat request; no separate retrieval or task override.
export function searchMessage(input: string): string {
  const query=input.trim();
  return /^(?:请|帮我)?(?:搜索|搜一下|查找|检索)/.test(query) ? query : `帮我搜索：${query}`;
}

export function latestMemorySection(
  memoryStatus: MemoryStatusResponse | null,
  name: string,
  fallback: string,
): string {
  const preview = memoryStatus?.files.find((file) => file.name === name)?.preview.trim();
  if (!preview) return fallback;
  const sections = preview
    .split(/\n(?=#{1,6}\s+)/)
    .map((section) => section.trim())
    .filter(Boolean);
  return sections.length ? sections[sections.length - 1] : preview;
}

type ChatPanelProps = {
  messages: ChatMessage[];
  sessionId?: string;
  sessionNavigation: SemanticSessionRow | null;
  input: string;
  setInput: (value: string) => void;
  isSending: boolean;
  onSubmit: (event: FormEvent, question?: string) => void | Promise<void>;
  onStop: () => void;
  streamRecovery: {
    question: string;
    reply: string;
    reason: string;
    sessionId?: string;
    turnId?: string | null;
  } | null;
  onContinueInterruptedReply: () => void;
  onRetry: () => void;
  onAbandonInterruptedReply: () => Promise<void> | void;
  onCopyInterruptedReply: () => Promise<void> | void;
  onUploadClick: () => void;
  onQuickPrompt: (value: string) => void;
  onStartNewTopic: () => void;
  lastChat: ChatResponse | null;
  ragEnabled: boolean;
  memoryStatus: MemoryStatusResponse | null;
  onOpenDrawer: (drawer: DrawerId) => void;
  onEndSession: () => void;
  isEndingSession?: boolean;
  researchRun: ResearchLookupResponse | null;
  researchProgress?: ChatResearchProgress | null;
  isResearchBusy: boolean;
  canRetryResearch: boolean;
  canResumeResearch: boolean;
  useResearchInChat: boolean;
  onRetryResearch: () => void;
  onResumeResearch: () => void;
  firstUseNotice?: ReactNode;
  enterToSend?: boolean;
};

type CopyState = "idle" | "success" | "error";

export function ChatPanel(props: ChatPanelProps) {
  const reading=useReadingWorkspace();
  const {
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
    onQuickPrompt,
    onStartNewTopic,
    lastChat,
    ragEnabled,
    onOpenDrawer,
    researchRun,
    researchProgress = null,
    isResearchBusy,
    canRetryResearch,
    canResumeResearch,
    useResearchInChat,
    onRetryResearch,
    onResumeResearch,
    firstUseNotice,
    enterToSend = true,
  } = props;

  const conversationRef = useRef<HTMLElement | null>(null);
  const [isAtBottom, setIsAtBottom] = useState(true);
  const [messageCopy, setMessageCopy] = useState<{ index: number; state: CopyState } | null>(null);
  const [interruptedCopy, setInterruptedCopy] = useState<CopyState>("idle");
  const [copyAnnouncement, setCopyAnnouncement] = useState("");
  const [composerMode, setComposerMode] = useState<"chat" | "search">("chat");
  const taskContract = taskContractFromRoute(lastChat?.route);
  const taskLabel = taskContract
    ? `${taskIntentLabel(taskContract.task_intent)}${taskContract.explicit_override ? " · 手动" : ""}`
    : "等待提问";
  const displayMessages = sessionNavigation?.has_completed_turns
    ? messages
    : messages.filter(
        (message) =>
          !(
            message.role === "assistant" &&
            message.transient &&
            !message.turnId
          ),
      );

  const resetCopyFeedbackLater = (kind: "message" | "interrupted", index?: number) => {
    window.setTimeout(() => {
      if (kind === "message") {
        setMessageCopy((current) => (current?.index === index ? null : current));
      } else {
        setInterruptedCopy("idle");
      }
      setCopyAnnouncement("");
    }, 2400);
  };

  const updateScrollState = () => {
    const element = conversationRef.current;
    if (!element) return;
    const distanceFromBottom = element.scrollHeight - element.scrollTop - element.clientHeight;
    setIsAtBottom(distanceFromBottom < 80);
  };

  const scrollToLatest = () => {
    const element = conversationRef.current;
    if (!element) return;
    setIsAtBottom(true);
    element.scrollTo({ top: element.scrollHeight, behavior: "smooth" });
  };

  const copyMessage = async (content: string, index: number) => {
    try {
      if (!navigator.clipboard?.writeText) throw new Error("clipboard unavailable");
      await navigator.clipboard.writeText(content);
      setMessageCopy({ index, state: "success" });
      setCopyAnnouncement("回答已复制");
    } catch {
      setMessageCopy({ index, state: "error" });
      setCopyAnnouncement("复制失败，请检查浏览器剪贴板权限后重试");
    }
    resetCopyFeedbackLater("message", index);
  };

  const copyInterruptedReply = async () => {
    try {
      await onCopyInterruptedReply();
      setInterruptedCopy("success");
      setCopyAnnouncement("已有内容已复制");
    } catch {
      setInterruptedCopy("error");
      setCopyAnnouncement("复制失败，请检查浏览器剪贴板权限后重试");
    }
    resetCopyFeedbackLater("interrupted");
  };

  const handleComposerKeyDown = (event: ReactKeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== "Enter" || event.nativeEvent.isComposing) return;
    // G17: configurable send key. Default Enter sends / Shift+Enter newline;
    // when enterToSend is off, Enter newlines and Ctrl/Cmd+Enter sends.
    const sendRequested = enterToSend
      ? !event.shiftKey
      : Boolean(event.ctrlKey || event.metaKey);
    if (!sendRequested) return;
    event.preventDefault();
    if (!isSending && input.trim()) event.currentTarget.form?.requestSubmit();
  };

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (isSending || !input.trim()) return;
    setIsAtBottom(true);
    clearPendingTaskIntentOverride();
    await onSubmit(event, composerMode === "search" ? searchMessage(input) : input.trim());
  };

  const handleRestoreEntry = (_intent: TaskIntent, prompt: string) => onQuickPrompt(prompt);

  useLayoutEffect(() => {
    if (!isAtBottom) return;
    const element = conversationRef.current;
    if (!element) return;

    const pinToLatest = () => {
      element.scrollTop = element.scrollHeight;
    };
    pinToLatest();
    let followupFrame = 0;
    const frame = window.requestAnimationFrame(() => {
      pinToLatest();
      followupFrame = window.requestAnimationFrame(pinToLatest);
    });
    return () => {
      window.cancelAnimationFrame(frame);
      if (followupFrame) window.cancelAnimationFrame(followupFrame);
    };
  }, [messages, streamRecovery, isAtBottom]);

  useEffect(() => {
    clearPendingTaskIntentOverride();
    setComposerMode("chat");
    return clearPendingTaskIntentOverride;
  }, [sessionId]);

  const restoreCard=<RestoreCard
    session={sessionNavigation} streamRecovery={streamRecovery}
    onSelectEntry={handleRestoreEntry} onUpload={onUploadClick}
    onContinueHere={onQuickPrompt} onStartNewTopic={onStartNewTopic}
    onContinueInterrupted={onContinueInterruptedReply}
    onRetryInterrupted={onRetry} onAbandonInterrupted={onAbandonInterruptedReply}
  />;
  return (
    <main className={`chat-panel${!displayMessages.length && !streamRecovery ? " chat-start" : ""}`} id="chat">
      <span className="visually-hidden" aria-live="polite" role="status">
        {copyAnnouncement}
      </span>
      <header className="topbar">
          <div className="topbar-copy">
            <h1>{reading?.target ? "伴读对话" : "学习工作台"}</h1>
            <p>搜索资料，或从一个问题开始。</p>
            <div className="topbar-meta" aria-label="当前学习状态">
              <span>任务 {taskLabel}</span>
              <span>资料 {ragEnabled ? "按需使用" : "未启用"}</span>
              <span>会话 {sessionId ? "进行中" : "未开始"}</span>
            </div>
          </div>
          <button aria-label="打开会话历史" className="icon-button session-dock-button" onClick={()=>onOpenDrawer("sessions")} type="button"><BookOpen size={18}/></button>
      </header>

      <div className="conversation-shell">
        <section className="conversation" aria-label="学习对话" onScroll={updateScrollState} ref={conversationRef}>
          {firstUseNotice}
          {streamRecovery ? restoreCard : sessionNavigation?.has_completed_turns ? <details className="reading-session-context"><summary>本会话学习上下文</summary>{restoreCard}</details> : !displayMessages.length ? <section className="chat-welcome" aria-label="开始新任务"><span>你的学习空间</span><h2>今天想了解什么？</h2><p>直接对话，或搜索你想核对的资料。</p></section> : null}
          {displayMessages.map((message, index) => {
            const avatarRole = message.avatarRole ?? (message.role === "user" ? "user" : "auto");
            const label = message.role === "user" ? "你" : roleLabel(avatarRole);
            const currentCopyState = messageCopy?.index === index ? messageCopy.state : "idle";
            const cancelNotice = message.cancelNotice ?? null;
            return (
              <article className={`message ${message.role}`} key={`${message.role}-${index}`}>
                <RoleAvatar fallback={message.role === "user" ? "user" : "assistant"} roleId={avatarRole} />
                <div className="message-body">
                  <span>{label}</span>
                  {message.role === "assistant" && message.content ? (
                    <button
                      aria-label="复制回答正文"
                      className={`ghost-action compact message-copy-button${currentCopyState === "error" ? " copy-error" : ""}`}
                      onClick={() => void copyMessage(message.content, index)}
                      type="button"
                    >
                      <Clipboard size={13} />
                      {currentCopyState === "success" ? "已复制" : currentCopyState === "error" ? "复制失败" : "复制"}
                    </button>
                  ) : null}
                  {cancelNotice ? (
                    <p aria-live="polite" className="turn-status-line tone-pending" role="status">
                      {cancelNotice}
                    </p>
                  ) : null}
                  <MarkdownMessage content={message.content} />
                  {message.role === "assistant" && message.evidence ? <EvidenceTrail evidence={message.evidence} /> : null}
                </div>
              </article>
            );
          })}
          <div />
        </section>
        {!isAtBottom ? (
          <button className="back-to-latest" onClick={scrollToLatest} type="button">
            <ArrowDown size={14} />
            回到最新
          </button>
        ) : null}
      </div>

      {streamRecovery?.reply ? (
        <div className="interrupted-copy-shortcut">
          <span>部分回答已保留；恢复、重试或放弃请使用上方恢复卡。</span>
          <button
            className={`ghost-action compact${interruptedCopy === "error" ? " copy-error" : ""}`}
            disabled={isSending}
            onClick={() => void copyInterruptedReply()}
            type="button"
          >
            <Clipboard size={14} />
            {interruptedCopy === "success" ? "已复制" : interruptedCopy === "error" ? "复制失败" : "复制已有内容"}
          </button>
        </div>
      ) : null}

      <ChatResearchRecovery
        run={researchRun}
        progress={researchProgress}
        isBusy={isResearchBusy}
        canRetry={canRetryResearch}
        canResume={canResumeResearch}
        useInChat={useResearchInChat}
        onRetry={onRetryResearch}
        onResume={onResumeResearch}
      />

      <form className="composer" onSubmit={handleSubmit}>
        <div className="composer-main">
          <div className="composer-modes" role="group" aria-label="输入方式">
            <button type="button" aria-pressed={composerMode === "chat"} onClick={()=>setComposerMode("chat")}><MessageSquare size={15}/>对话</button>
            <button type="button" aria-pressed={composerMode === "search"} onClick={()=>setComposerMode("search")}><Search size={15}/>搜索</button>
          </div>
          <textarea
            aria-label="输入学习问题"
            autoFocus
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={handleComposerKeyDown}
            placeholder={composerMode === "search" ? "搜索你想了解的问题…" : "输入你的问题，或继续当前对话…"}
            title={
              enterToSend
                ? "回车键发送 · 按住上档键再按回车键换行"
                : "控制键 + 回车键发送 · 回车键换行"
            }
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
            {composerMode === "search" ? <Search size={17}/> : <Send size={17}/> }
            {composerMode === "search" ? "搜索" : "发送"}
          </button>
        )}
      </form>
    </main>
  );
}
