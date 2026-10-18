import {
  ArrowDown,
  ArrowUp,
  BookOpen,
  Clipboard,
  Clock,
  Search,
  MessageSquare,
  PanelRight,
  Settings2,
  Square,
} from "lucide-react";
import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";

import { MarkdownMessage } from "../../components/MarkdownMessage";
import { AnswerProgress } from "../answer-ui/AnswerProgress";
import { InteractiveComputation } from "../answer-ui/InteractiveComputation";
import { answerCopyText } from "../answer-ui/answerUiProtocol";
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
import { ChatRoleSettings } from "./ChatRoleSettings";
import { ComposerAttachments } from "./ComposerAttachments";

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

// Every steering receipt reflects a server fact; "pending" is the only
// not-yet-applied state and must not read as if the search already changed.
const steeringReceiptCopy: Record<string, string> = {
  pending: "已纳入研究计划 · 等待相关搜索",
  executing: "正在按补充要求执行研究",
  applied: "已应用到后续研究",
  late: "本轮未应用这条补充，请在下一轮继续",
};

type ChatPanelProps = {
  messages: ChatMessage[];
  sessionId?: string;
  sessionNavigation: SemanticSessionRow | null;
  input: string;
  setInput: (value: string) => void;
  selectedRole?: string;
  onSelectRole?: (role: string) => void;
  isSending: boolean;
  canSteer?: boolean;
  canQueue?: boolean;
  onQueue?: (question: string) => void | Promise<void>;
  onSendQueued?: (id: string) => void | Promise<void>;
  isSteering?: boolean;
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
  sourcesOpen?: boolean;
  onToggleSources?: () => void;
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
  onEnsureSession?: () => Promise<string | undefined>;
  /** This message's attachment selection (ids), owned by the workspace. */
  attachmentSelection?: string[];
  onAttachmentSelectionChange?: (ids: string[]) => void;
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
  const [busyInputMode, setBusyInputMode] = useState<"steer" | "queue">("steer");
  const canSubmit = !isSending || Boolean(!props.isSteering && (busyInputMode === "steer" ? props.canSteer : props.canQueue));

  const conversationRef = useRef<HTMLElement | null>(null);
  const composerRef = useRef<HTMLTextAreaElement | null>(null);
  const composingRef = useRef(false);
  useLayoutEffect(() => {
    const textarea = composerRef.current;
    if (!textarea) return;
    let lastWidth = textarea.clientWidth;
    const resize = () => {
      if (!textarea.clientWidth) return;
      textarea.style.height = "0px";
      const height = input.length ? Math.max(42, textarea.scrollHeight) : 42;
      textarea.style.height = `${Math.min(160, height)}px`;
      textarea.style.overflowY = height > 160 ? "auto" : "hidden";
    };
    resize();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(() => {
      if (textarea.clientWidth === lastWidth) return;
      lastWidth = textarea.clientWidth;
      resize();
    });
    observer?.observe(textarea);
    return () => observer?.disconnect();
  }, [input]);
  const roleSettingsButtonRef = useRef<HTMLButtonElement | null>(null);
  const roleSettingsId = useId();
  const [roleSettingsOpen, setRoleSettingsOpen] = useState(false);
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
  // Research progress lives in the conversation timeline; once the run's status
  // is on screen inline, the standalone recovery surface must not repeat it.
  const inlineResearchShown = Boolean(
    researchProgress?.run_id &&
      displayMessages.some((message) => message.researchProgress?.run_id === researchProgress.run_id),
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
      await navigator.clipboard.writeText(answerCopyText(content));
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
    if (event.key !== "Enter") return;
    // Some Chinese/Japanese IMEs report isComposing=false on the confirming
    // Enter keydown; keyCode=229 and the composition lifecycle are additional
    // guards against submitting an unfinished draft (#229).
    if (composingRef.current || event.nativeEvent.isComposing || event.keyCode === 229) return;
    // G17: configurable send key. Default Enter sends / Shift+Enter newline;
    // when enterToSend is off, Enter newlines and Ctrl/Cmd+Enter sends.
    const sendRequested = enterToSend
      ? !event.shiftKey
      : Boolean(event.ctrlKey || event.metaKey);
    if (!sendRequested) return;
    event.preventDefault();
    if (canSubmit && input.trim()) event.currentTarget.form?.requestSubmit();
  };

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (!canSubmit || !input.trim()) return;
    if (!isSending) setIsAtBottom(true);
    clearPendingTaskIntentOverride();
    if (isSending && busyInputMode === "queue") { await props.onQueue?.(input.trim()); return; }
    await onSubmit(event, !isSending && composerMode === "search" ? searchMessage(input) : input.trim());
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
    // A previous session may have been scrolled up. A newly opened session
    // should display its newest turn rather than inherit that scroll lock (#229).
    setIsAtBottom(true);
    clearPendingTaskIntentOverride();
    setComposerMode("chat");
    setRoleSettingsOpen(false);
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
            <h1>{reading?.target ? "伴读对话" : "对话"}</h1>
            <p>搜索资料，或从一个问题开始。</p>
            <div className="topbar-meta" aria-label="当前学习状态">
              <span>任务 {taskLabel}</span>
              <span>资料 {ragEnabled ? "按需使用" : "未启用"}</span>
              <span>会话 {sessionId ? "进行中" : "未开始"}</span>
            </div>
          </div>
          <div className="topbar-actions">
            <button aria-label="打开会话历史" className="icon-button session-dock-button" onClick={()=>onOpenDrawer("sessions")} title="会话历史" type="button"><BookOpen size={18}/></button>
            <button aria-label={props.sourcesOpen ? "收起资料与来源" : "打开资料与来源"}
              aria-expanded={props.sourcesOpen ?? false} aria-haspopup="dialog" className="icon-button sources-dock-button"
              onClick={props.onToggleSources ?? (()=>onOpenDrawer("sources"))} title="资料与来源" type="button"><PanelRight size={18}/></button>
          </div>
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
              <article aria-label={`${label}的消息`} className={`message ${message.role}`} key={`${message.role}-${index}`}>
                <RoleAvatar fallback={message.role === "user" ? "user" : "assistant"} roleId={avatarRole} />
                <div className="message-header">
                  <span className="message-author">{label}</span>
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
                </div>
                <div className="message-body">
                  {message.researchQueued ? (
                    <div className="research-queue-card" role="status">
                      <header className="research-queue-head">
                        <Clock aria-hidden size={14} />
                        <span className="research-queue-title">下一轮任务</span>
                        <span className="research-queue-count">已保存，待发送</span>
                      </header>
                      <p className="research-queue-body">{message.content}</p>
                      {message.researchQueued.attachmentIds?.length ? (
                        <p className="research-queue-note">附带 {message.researchQueued.attachmentIds.length} 个附件，将用于这条问题。</p>
                      ) : null}
                      <p className="research-queue-note">不会修改当前研究的搜索条件；研究完成后需手动发送。</p>
                      {!isSending && props.onSendQueued ? (
                        <button
                          className="ghost-action compact"
                          onClick={() => void props.onSendQueued?.(message.researchQueued!.id)}
                          type="button"
                        >
                          发送排队问题
                        </button>
                      ) : null}
                    </div>
                  ) : (
                    <div className="message-bubble">
                      {cancelNotice ? (
                        <p aria-live="polite" className="turn-status-line tone-pending" role="status">
                          {cancelNotice}
                        </p>
                      ) : null}
                      {message.role === "assistant" && (message.researchProgress || (isSending && !displayMessages.slice(index + 1).some(item => item.role === "assistant")))
                        ? <AnswerProgress hasContent={!!message.content.trim()} progress={message.researchProgress ?? researchProgress} /> : null}
                      <MarkdownMessage content={message.content} interactive={message.role === "assistant"}
                        streaming={message.role === "assistant" && isSending && !displayMessages.slice(index + 1).some(item => item.role === "assistant")}
                        onDraft={prompt => {
                          setComposerMode("chat");
                          setInput(input.trim() ? `${input}\n\n${prompt}` : prompt);
                          composerRef.current?.focus();
                        }} />
                      {message.computation ? <InteractiveComputation payload={message.computation} /> : null}
                      {message.researchSteering ? (
                        <span className="research-steering-receipt" role="status">
                          {steeringReceiptCopy[message.researchSteering.status] ?? steeringReceiptCopy.pending}
                        </span>
                      ) : null}
                    </div>
                  )}
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
            {isSending ? "正在生成 · 回到最新" : "回到最新"}
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
        inlineStatusShown={inlineResearchShown}
        isBusy={isResearchBusy}
        canRetry={canRetryResearch}
        canResume={canResumeResearch}
        useInChat={useResearchInChat}
        onRetry={onRetryResearch}
        onResume={onResumeResearch}
      />

      <form className="composer" onSubmit={handleSubmit}>
        <div className="composer-main">
          <textarea
            ref={composerRef}
            rows={1}
            aria-label="输入学习问题"
            autoFocus
            onChange={(event) => setInput(event.target.value)}
            onCompositionStart={() => { composingRef.current = true; }}
            onCompositionEnd={() => { composingRef.current = false; }}
            onKeyDown={handleComposerKeyDown}
            placeholder={isSending ? busyInputMode === "queue" ? "写下下一条问题…" : props.canSteer ? "补充要求，或调整方向…" : "写下问题，回答完成后发送…" : composerMode === "search" ? "搜索你想了解的问题…" : "输入问题，或继续对话…"}
            aria-describedby={isSending ? "research-composer-hint" : undefined}
            title={
              enterToSend
                ? "回车键发送 · 按住上档键再按回车键换行"
                : "控制键 + 回车键发送 · 回车键换行"
            }
            value={input}
          />
          <div className="composer-toolbar">
          <ComposerAttachments
            sessionId={sessionId}
            onEnsureSession={props.onEnsureSession}
            selectedIds={props.attachmentSelection ?? []}
            onSelectionChange={props.onAttachmentSelectionChange}
          />
          {!isSending ? <div className="composer-modes" role="group" aria-label="输入方式">
            <button type="button" aria-pressed={composerMode === "chat"} onClick={()=>setComposerMode("chat")}><MessageSquare size={15}/>对话</button>
            <button type="button" aria-pressed={composerMode === "search"} onClick={()=>{setComposerMode("search");setRoleSettingsOpen(false);}}><Search size={15}/>搜索</button>
          </div> : null}
          {isSending && (props.canSteer || props.canQueue) ? <select
            className="composer-research-mode" aria-label="追加方式" value={busyInputMode}
            disabled={props.isSteering} onChange={event => setBusyInputMode(event.target.value as "steer" | "queue")}
          >
            <option value="steer" disabled={!props.canSteer}>调整当前研究</option>
            <option value="queue" disabled={!props.canQueue}>完成后再做</option>
          </select> : null}
          {!isSending && composerMode === "chat" && props.onSelectRole ? <button className="chat-role-settings-toggle" type="button"
            aria-label="对话设置" title="对话设置" aria-expanded={roleSettingsOpen} aria-controls={roleSettingsId}
            ref={roleSettingsButtonRef} onClick={()=>setRoleSettingsOpen(open=>!open)}><Settings2 size={16}/></button> : null}
          </div>
          {!isSending && composerMode === "chat" && roleSettingsOpen && props.onSelectRole ? <ChatRoleSettings
            id={roleSettingsId} selectedRole={props.selectedRole ?? "auto"} disabled={isSending}
            onSelect={role=>{props.onSelectRole?.(role);setRoleSettingsOpen(false);composerRef.current?.focus();}}
            onClose={()=>{setRoleSettingsOpen(false);roleSettingsButtonRef.current?.focus();}}
          /> : null}
          <div className="composer-footer">
            {isSending ? <span id="research-composer-hint" className={`research-composer-hint${(props.canSteer || props.canQueue) && !props.isSteering ? " visually-hidden" : ""}`}>
              {props.isSteering ? "正在提交补充…" : busyInputMode === "queue" ? "完成后再做；不会修改当前研究的搜索条件" : props.canSteer ? "追加条件将在后续研究中处理" : "本轮暂不支持中途调整，可以选择完成后再做"}
            </span> : null}
            {isSending && input.trim() && (props.canSteer || props.canQueue) ? <button className="send-button" disabled={!canSubmit} title={busyInputMode === "queue" ? "加入下一轮" : "追加要求"} type="submit">
              <ArrowUp size={20}/><span className="visually-hidden">{busyInputMode === "queue" ? "加入下一轮" : "追加要求"}</span>
            </button> : null}
            {isSending ? (
              <button className="send-button stop-button" onClick={onStop} title="停止生成" type="button">
                <Square size={16} />
                <span className="visually-hidden">停止</span>
              </button>
            ) : (
              <button className="send-button" disabled={!input.trim()} title={composerMode === "search" ? "搜索" : "发送"} type="submit">
                {composerMode === "search" ? <Search size={20}/> : <ArrowUp size={20}/> }
                <span className="visually-hidden">{composerMode === "search" ? "搜索" : "发送"}</span>
              </button>
            )}
          </div>
        </div>
      </form>
    </main>
  );
}
