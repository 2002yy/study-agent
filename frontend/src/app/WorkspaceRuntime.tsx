import { ChangeEvent, FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { LocalKnowledgeInvocation } from "../api";
import { operationRegistry } from "./operationRegistry";
import { useWorkspace } from "./WorkspaceProvider";
import { useWorkspaceBootstrap } from "./WorkspaceBootstrap";
import { WorkspaceCoordinator } from "./WorkspaceCoordinator";
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
import { useMemoryController } from "../features/learning-memory/memoryController";
import { useRagController } from "../features/rag/ragController";
import { useUploadController } from "../features/rag/uploadController";
import { createEmptyRag, useChatController } from "../features/chat/chatController";
import { ChatPanel } from "../features/single-chat/ChatPanel";
import { seedMessages } from "../features/single-chat/chatHistory";
import { useToolController } from "../features/tools/toolController";
import { useRoleController } from "../features/roles/roleController";
import { useSettingsController } from "../features/settings/settingsController";
import { useGroupChatController } from "../features/group-chat/groupChatController";
import { useNewsController } from "../features/news-workspace/newsController";
import { useWebLookupController } from "../features/web-lookup/webLookupController";
import { useWorkflowController } from "../features/workflows/workflowController";
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
  const wechatThreadId = workspaceRuntime.activeGroupThreadId ?? snapshot.wechat?.group_thread_id;
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
  const roleController = useRoleController(chatSettings.selectedRole);
  const workflowController = useWorkflowController();
  const settingsController = useSettingsController({
    chatSettings,
    ragSettings,
    ragEnabled,
    setRuntimeSettings: (runtimeSettings) =>
      setSnapshot((current) => ({ ...current, runtimeSettings })),
    setOperationError,
    refresh,
  });

  const groupController = useGroupChatController({
    wechat: snapshot.wechat,
    setWechat: (wechat) => setSnapshot((current) => ({ ...current, wechat })),
    chatSettings,
    ragSettings,
    ragEnabled,
    clearAssociatedNews: () => {
      setNewsRunId(undefined);
    },
  });

  const newsController = useNewsController({
    query: newsQuery,
    readArticles,
    chatSettings,
    groupThreadId: wechatThreadId,
    activeRunId: newsRunId,
    setActiveRunId: setNewsRunId,
    onDiscussed: (threadId) => {
      setWechatThreadId(threadId);
      void refresh();
    },
  });
  const webLookupController = useWebLookupController({
    query: newsQuery,
    setOperationError,
    activeRunId: webLookupRunId,
    setActiveRunId: setWebLookupRunId,
  });
  const memoryController = useMemoryController({
    activeRunId: memoryRunId,
    setActiveRunId: setMemoryRunId,
    onMemoryChanged: refresh,
  });
  const ragController = useRagController({
    settings: ragSettings,
    activeRunId: ragQueryRunId,
    setActiveRunId: setRagQueryRunId,
    setOperationError,
  });
  const uploadController = useUploadController({
    activeRunId: ragWriteRunId,
    setActiveRunId: setRagWriteRunId,
    setOperationError,
    onChanged: refresh,
  });
  const webLookup = webLookupController.result;
  const useWebLookup = webLookupController.useInChat;
  const setUseWebLookup = webLookupController.setUseInChat;
  const workspaceCoordinator = useMemo(
    () =>
      new WorkspaceCoordinator(
        {
          cancelChat: () => operationRegistry.cancelAll(),
          cancelGroup: groupController.cancelWorkspace,
          cancelNews: newsController.cancelWorkspace,
          cancelWebLookup: webLookupController.cancel,
          invalidateTool: () => operationRegistry.invalidate("tool"),
        },
        {
          clearRag: ragController.clear,
          clearToolRun: () => setToolRunId(undefined),
          clearWorkflow: workflowController.clear,
        }
      ),
    [
      groupController.cancelWorkspace,
      newsController.cancelWorkspace,
      webLookupController.cancel,
      ragController.clear,
      workflowController.clear,
    ]
  );

  useEffect(() => {
    const serverThreadId = snapshot.wechat?.group_thread_id;
    if (serverThreadId && workspaceRuntime.activeGroupThreadId !== serverThreadId) {
      setWechatThreadId(serverThreadId);
    }
  }, [snapshot.wechat?.group_thread_id, workspaceRuntime.activeGroupThreadId]);

  const chatController = useChatController({
    chatSettings,
    chatSettingsDefaults: CHAT_SETTINGS_DEFAULTS,
    setChatSettings,
    ragSettings,
    ragSettingsDefaults: RAG_SETTINGS_DEFAULTS,
    setRagSettings,
    ragEnabled,
    setRagEnabled,
    keepCurrentRole,
    setKeepCurrentRole,
    conversationInstruction,
    setConversationInstruction,
    webLookupSource: webLookup?.source_block ?? "",
    useWebLookup,
    setUseWebLookup,
    setInput,
    setOperationError,
    clearChatArtifacts: workspaceCoordinator.clearChatArtifacts.bind(workspaceCoordinator),
    onWorkspaceCancelled:
      workspaceCoordinator.cancelAllActiveOperations.bind(workspaceCoordinator),
    refresh,
  });
  const singleChatMessages = chatController.messages;
  const setSingleChatMessages = chatController.setMessages;
  const lastChat = chatController.lastChat;
  const setLastChat = chatController.setLastChat;
  const streamRecovery = chatController.streamRecovery;
  const singleChatSessionId = chatController.threadId;
  const setSingleChatSessionId = chatController.setThreadId;
  const isSending = chatController.isSending;
  const cancelWorkspaceRuns = chatController.cancelWorkspaceRuns;

  const activeQuery = input.trim() || lastChat?.rag?.query || "";
  const partialErrors = Object.entries(snapshot.errors ?? {}).filter(([key]) => key !== "health");
  const currentToolInvocation: LocalKnowledgeInvocation = {
    query: activeQuery,
    retrievalMode: ragSettings.retrievalMode,
    topK: ragSettings.chatTopK,
    minScore: ragSettings.minScore
  };
  const toolController = useToolController({
    invocation: currentToolInvocation,
    activeRunId: toolRunId,
    setActiveRunId: setToolRunId,
    onCalled: async () => {
      await refresh();
    },
  });

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
