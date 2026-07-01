import { ChangeEvent, FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useWorkspace } from "./WorkspaceProvider";
import { useWorkspaceBootstrap } from "./WorkspaceBootstrap";
import {
  useWorkspacePersistence,
  type WorkspaceRecovery,
} from "./WorkspacePersistence";
import AppShell from "../AppShell";
import {
  CHAT_SETTINGS_DEFAULTS, RAG_SETTINGS_DEFAULTS, Sidebar, modeOptions
} from "../layout/Sidebar";
import { Inspector } from "../layout/Inspector";
import { GlobalNotices } from "../layout/GlobalNotices";
import { useWorkspaceControllers } from "./useWorkspaceControllers";
import { createEmptyRag } from "../features/chat/chatController";
import { ChatPanel } from "../features/single-chat/ChatPanel";
import { seedMessages } from "../features/single-chat/chatHistory";
import type {
  ChatSettings,
  RagSettings
} from "../types";

export default function WorkspaceRuntime() {
  const { snapshot, setSnapshot, refresh } = useWorkspaceBootstrap();
  const { state: workspaceRuntime, dispatch: dispatchWorkspace } = useWorkspace();
  const [input, setInput] = useState("");
  const [ragEnabled, setRagEnabled] = useState(true);
  const [chatSettings, setChatSettings] = useState<ChatSettings>(CHAT_SETTINGS_DEFAULTS);
  const [ragSettings, setRagSettings] = useState<RagSettings>(RAG_SETTINGS_DEFAULTS);
  const [keepCurrentRole, setKeepCurrentRole] = useState(false);
  const [conversationInstruction, setConversationInstruction] = useState("");
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
  const [newsQuery, setNewsQuery] = useState("最新新闻 when:1d");
  const [readArticles, setReadArticles] = useState(true);
  const [operationError, setOperationError] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const runtimeHydratedRef = useRef(false);
  const sessionSettingsRestoredRef = useRef(false);
  const {
    activeQuery,
    groupThreadId: wechatThreadId,
    roleController,
    workflowController,
    settingsController,
    groupController,
    newsController,
    webLookupController,
    memoryController,
    ragController,
    uploadController,
    chatController,
    toolController,
  } = useWorkspaceControllers({
    snapshot,
    setSnapshot,
    refresh,
    input,
    setInput,
    chatSettings,
    setChatSettings,
    ragSettings,
    setRagSettings,
    ragEnabled,
    setRagEnabled,
    keepCurrentRole,
    setKeepCurrentRole,
    conversationInstruction,
    setConversationInstruction,
    newsQuery,
    readArticles,
    operationError: setOperationError,
    activeGroupThreadId: workspaceRuntime.activeGroupThreadId,
    runIds: {
      news: newsRunId, tool: toolRunId, memory: memoryRunId,
      ragQuery: ragQueryRunId, ragWrite: ragWriteRunId,
      webLookup: webLookupRunId,
    },
    setGroupThreadId: setWechatThreadId,
    setRunId: {
      news: setNewsRunId, tool: setToolRunId, memory: setMemoryRunId,
      ragQuery: setRagQueryRunId, ragWrite: setRagWriteRunId,
      webLookup: setWebLookupRunId,
    },
  });
  const webLookup = webLookupController.result;
  const useWebLookup = webLookupController.useInChat;
  const setUseWebLookup = webLookupController.setUseInChat;
  const singleChatMessages = chatController.messages;
  const setSingleChatMessages = chatController.setMessages;
  const lastChat = chatController.lastChat;
  const setLastChat = chatController.setLastChat;
  const streamRecovery = chatController.streamRecovery;
  const singleChatSessionId = chatController.threadId;
  const isSending = chatController.isSending;
  const partialErrors = Object.entries(snapshot.errors ?? {}).filter(
    ([key]) => key !== "health"
  );

  const restoreWorkspace = useCallback((parsed: WorkspaceRecovery | null) => {
    if (!parsed) {
      setSingleChatMessages(seedMessages);
      return;
    }
    const restoredThreadId = parsed.singleChatSessionId ?? parsed.sessionId ?? "";
    if (parsed.wechatThreadId) setWechatThreadId(parsed.wechatThreadId);
    if (parsed.newsRunId) setNewsRunId(parsed.newsRunId);
    if (parsed.toolRunId) setToolRunId(parsed.toolRunId);
    if (parsed.memoryRunId) setMemoryRunId(parsed.memoryRunId);
    if (parsed.ragQueryRunId) setRagQueryRunId(parsed.ragQueryRunId);
    if (parsed.ragWriteRunId) setRagWriteRunId(parsed.ragWriteRunId);
    if (parsed.webLookupRunId) setWebLookupRunId(parsed.webLookupRunId);
    if (parsed.chatSettings) {
      sessionSettingsRestoredRef.current = true;
      setChatSettings({ ...CHAT_SETTINGS_DEFAULTS, ...parsed.chatSettings });
    }
    if (parsed.ragSettings) {
      sessionSettingsRestoredRef.current = true;
      setRagSettings({ ...RAG_SETTINGS_DEFAULTS, ...parsed.ragSettings });
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
      void chatController.hydrateSession(restoredThreadId, parsed.cachedMessages);
    } else {
      setSingleChatMessages(seedMessages);
    }
    if (parsed.lastRoute) {
      setLastChat({
        reply: "",
        session_id: parsed.lastSessionId ?? restoredThreadId ?? "restored",
        route: parsed.lastRoute,
        rag: parsed.lastRag ?? createEmptyRag(),
      });
    }
  }, [chatController, setLastChat, setSingleChatMessages]);

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

  const persistenceState = useMemo(() => ({
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
      isSending,
    }), [
      singleChatSessionId, wechatThreadId, newsRunId, toolRunId, memoryRunId,
      ragQueryRunId, ragWriteRunId, webLookupRunId, chatSettings, ragSettings,
      ragEnabled, keepCurrentRole, conversationInstruction, lastChat,
      singleChatMessages, isSending,
    ]);
  useWorkspacePersistence({
    state: persistenceState,
    onRestore: restoreWorkspace,
  });

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    await chatController.send(input.trim());
  };

  const stopChatGeneration = chatController.stop;

  const retryInterruptedChat = chatController.retry;
  const continueInterruptedChat = chatController.continueInterrupted;
  const copyInterruptedReply = chatController.copyInterrupted;

  const searchSources = () => ragController.search(activeQuery);

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
    <AppShell>
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
        onSaveSettings={settingsController.save}
        isSavingSettings={settingsController.isSaving}
        onLoadRole={roleController.load}
        roleDetail={roleController.detail}
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
        selectedRun={workflowController.selectedRun}
        loadingRunId={workflowController.loadingRunId}
        selectRun={workflowController.selectRun}
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
      <GlobalNotices
        apiError={snapshot.error}
        operationError={operationError}
        partialErrors={partialErrors}
        onDismissOperationError={() => setOperationError("")}
      />
    </AppShell>
  );
}
