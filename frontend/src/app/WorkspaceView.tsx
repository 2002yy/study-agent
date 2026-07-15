import type { Dispatch, RefObject, SetStateAction } from "react";

import AppShell from "../AppShell";
import { SlideOver } from "../components/SlideOver";
import { abandonInterruptedTurn } from "../features/chat/recoveryApi";
import { LearningStrip } from "../features/learning/LearningStrip";
import { MemoryPanel } from "../features/learning-memory/MemoryPanel";
import { NewsWorkspace } from "../features/news-workspace/NewsWorkspace";
import { SourcesPanel } from "../features/rag/SourcesPanel";
import { ChatPanel } from "../features/single-chat/ChatPanel";
import { SessionSidebar } from "../features/sessions/SessionSidebar";
import { SessionsPanel } from "../features/sessions/SessionsPanel";
import type { SemanticSessionRow } from "../features/sessions/sessionNavigation";
import type { SessionSummary } from "../features/sessions/sessionSummary";
import { ToolPanel } from "../features/tools/ToolPanel";
import { WechatPanel } from "../features/wechat-workspace/WechatPanel";
import { TimelinePanel } from "../features/workflows/TimelinePanel";
import { GlobalNotices } from "../layout/GlobalNotices";
import { Sidebar } from "../layout/Sidebar";
import type { ApiSnapshot, ChatSettings, DrawerId, RagSettings, SessionRow } from "../types";
import { useWorkspace } from "./WorkspaceProvider";
import type { useWorkspaceControllers } from "./useWorkspaceControllers";

type Controllers = ReturnType<typeof useWorkspaceControllers>;
type SessionRowWithSummary = SessionRow & { summary?: SessionSummary };

export function WorkspaceView({
  snapshot,
  refresh,
  fileInputRef,
  ui,
  controllers,
}: {
  snapshot: ApiSnapshot;
  refresh: () => Promise<void>;
  fileInputRef: RefObject<HTMLInputElement>;
  ui: {
    input: string;
    setInput: Dispatch<SetStateAction<string>>;
    ragEnabled: boolean;
    setRagEnabled: Dispatch<SetStateAction<boolean>>;
    chatSettings: ChatSettings;
    setChatSettings: Dispatch<SetStateAction<ChatSettings>>;
    ragSettings: RagSettings;
    setRagSettings: Dispatch<SetStateAction<RagSettings>>;
    keepCurrentRole: boolean;
    setKeepCurrentRole: Dispatch<SetStateAction<boolean>>;
    conversationInstruction: string;
    setConversationInstruction: Dispatch<SetStateAction<string>>;
    newsQuery: string;
    setNewsQuery: Dispatch<SetStateAction<string>>;
    readArticles: boolean;
    setReadArticles: Dispatch<SetStateAction<boolean>>;
    operationError: string;
    setOperationError: Dispatch<SetStateAction<string>>;
  };
  controllers: Controllers;
}) {
  const {
    activeQuery,
    groupThreadId,
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
  } = controllers;
  const { state, dispatch } = useWorkspace();
  const openDrawer = (drawer: DrawerId) => dispatch({ type: "OPEN_DRAWER", drawer });
  const closeDrawer = () => dispatch({ type: "CLOSE_DRAWER" });
  const activeSession = snapshot.sessions.find(
    (session) => session.session_id === chatController.threadId
  ) as SemanticSessionRow | undefined;
  const serverSummary = (activeSession as SessionRowWithSummary | undefined)?.summary;
  const localSummary =
    state.sessionSummary?.thread_id === chatController.threadId
      ? state.sessionSummary
      : null;
  const sessionSummary =
    serverSummary?.status === "not_summarized" &&
    localSummary &&
    localSummary.status !== "not_summarized"
      ? localSummary
      : serverSummary ?? localSummary;
  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    await chatController.send(ui.input.trim());
  };
  const requestNewSession = () => {
    const hasMessages = chatController.messages.some((message) => message.role === "user");
    if (
      hasMessages &&
      !window.confirm(
        sessionSummary?.status === "summarized"
          ? "当前会话已整理但尚未归档。直接开始新会话时，旧会话会保留在历史中。继续吗？"
          : "当前学习尚未整理，直接开始新会话？旧会话会保留在历史中。"
      )
    ) {
      return;
    }
    void chatController.startNewSession();
  };
  const abandonRecovery = async () => {
    const recovery = chatController.streamRecovery;
    if (!recovery) return;
    if (!recovery.sessionId || !recovery.turnId) {
      chatController.setStreamRecovery(null);
      return;
    }
    try {
      await abandonInterruptedTurn(recovery.sessionId, recovery.turnId);
      chatController.setStreamRecovery(null);
      await refresh();
    } catch (error) {
      ui.setOperationError(
        `放弃恢复失败：${error instanceof Error ? error.message : "未知错误"}`
      );
    }
  };
  const handleUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    if (!files.length) return;
    if (
      uploadController.mode === "rebuild" &&
      !window.confirm(
        `将用本次 ${files.length} 个文件重建整个知识库索引，旧索引会被替换。继续吗？`,
      )
    ) {
      event.target.value = "";
      return;
    }
    await uploadController.upload(files);
    event.target.value = "";
  };
  const partialErrors = Object.entries(snapshot.errors ?? {}).filter(
    ([key]) => key !== "health",
  );

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
      <SessionSidebar
        sessions={snapshot.sessions}
        activeSessionId={chatController.threadId}
        isSending={chatController.isSending}
        onRestore={chatController.restoreSession}
        onArchive={chatController.archiveCurrentSession}
        onNewSession={requestNewSession}
        onSessionChanged={refresh}
      />
      <div className="chat-column">
        <LearningStrip
          lastChat={chatController.lastChat}
          visitedPhases={state.pedagogyPhases}
          memoryStatus={snapshot.memoryStatus}
        />
        <ChatPanel
          sessionId={chatController.threadId}
          sessionNavigation={activeSession ?? null}
          messages={chatController.messages}
          input={ui.input}
          setInput={ui.setInput}
          isSending={chatController.isSending}
          onSubmit={submit}
          onStop={chatController.stop}
          streamRecovery={chatController.streamRecovery}
          onContinueInterruptedReply={chatController.continueInterrupted}
          onRetry={chatController.retry}
          onAbandonInterruptedReply={abandonRecovery}
          onCopyInterruptedReply={chatController.copyInterrupted}
          onUploadClick={() => fileInputRef.current?.click()}
          onSearchSources={() => ragController.search(activeQuery)}
          isSearching={ragController.isSearching}
          hasSearchQuery={Boolean(activeQuery)}
          onQuickPrompt={ui.setInput}
          onStartNewTopic={requestNewSession}
          lastChat={chatController.lastChat}
          ragEnabled={ui.ragEnabled}
          memoryStatus={snapshot.memoryStatus}
          onOpenDrawer={openDrawer}
          onEndSession={async () => {
            if (!chatController.threadId) return;
            await memoryController.generateFromSession(chatController.threadId);
            openDrawer("memory");
          }}
          isEndingSession={memoryController.isPreviewing}
          researchRun={webLookupController.result}
          isResearchBusy={webLookupController.isBusy}
          canRetryResearch={webLookupController.canRetry}
          canResumeResearch={webLookupController.canResume}
          useResearchInChat={webLookupController.useInChat}
          onRetryResearch={() => void webLookupController.retry()}
          onResumeResearch={() => void webLookupController.resume()}
        />
      </div>
      <SlideOver open={state.activeDrawer === "sessions"} title="会话历史" onClose={closeDrawer}>
        <SessionsPanel
          sessions={snapshot.sessions}
          activeSessionId={chatController.threadId}
          isSending={chatController.isSending}
          onRestore={chatController.restoreSession}
          onArchive={chatController.archiveCurrentSession}
          onSessionChanged={refresh}
        />
      </SlideOver>
      <SlideOver open={state.activeDrawer === "settings"} title="设置" onClose={closeDrawer}>
        <Sidebar
          snapshot={snapshot}
          ragEnabled={ui.ragEnabled}
          ragUploadMode={uploadController.mode}
          setRagUploadMode={uploadController.setMode}
          setRagEnabled={ui.setRagEnabled}
          chatSettings={ui.chatSettings}
          setChatSettings={ui.setChatSettings}
          ragSettings={ui.ragSettings}
          setRagSettings={ui.setRagSettings}
          onSaveSettings={settingsController.save}
          isSavingSettings={settingsController.isSaving}
          onLoadRole={roleController.load}
          roleDetail={roleController.detail}
          keepCurrentRole={ui.keepCurrentRole}
          setKeepCurrentRole={ui.setKeepCurrentRole}
          conversationInstruction={ui.conversationInstruction}
          setConversationInstruction={ui.setConversationInstruction}
          onNewSession={requestNewSession}
          isSending={chatController.isSending}
          refresh={refresh}
          onUploadClick={() => fileInputRef.current?.click()}
          uploadState={uploadController.status}
          lastChat={chatController.lastChat}
        />
      </SlideOver>
      <SlideOver open={state.activeDrawer === "group"} title="群聊" onClose={closeDrawer}>
        <WechatPanel
          wechat={snapshot.wechat}
          newsController={newsController}
          webLookup={webLookupController.result}
          useWebLookup={webLookupController.useInChat}
          setUseWebLookup={webLookupController.setUseInChat}
          wechatInput={groupController.input}
          setWechatInput={groupController.setInput}
          newsQuery={ui.newsQuery}
          setNewsQuery={ui.setNewsQuery}
          readArticles={ui.readArticles}
          setReadArticles={ui.setReadArticles}
          sessionId={groupThreadId}
          onOpening={groupController.opening}
          onReset={groupController.reset}
          onMarkRead={groupController.markRead}
          onSendWechat={groupController.send}
          onStopWechat={groupController.stop}
          onLookupNews={webLookupController.lookup}
          onStopLookup={webLookupController.cancel}
          isWechatBusy={groupController.isBusy}
          error={groupController.error}
          isNewsBusy={webLookupController.isBusy}
        />
      </SlideOver>
      <SlideOver open={state.activeDrawer === "news"} title="新闻" onClose={closeDrawer}>
        <NewsWorkspace
          query={ui.newsQuery}
          setQuery={ui.setNewsQuery}
          readArticles={ui.readArticles}
          setReadArticles={ui.setReadArticles}
          controller={newsController}
          onLookupNews={webLookupController.lookup}
          onStopLookup={webLookupController.cancel}
          isLookupBusy={webLookupController.isBusy}
        />
      </SlideOver>
      <SlideOver open={state.activeDrawer === "tools"} title="工具" onClose={closeDrawer}>
        <ToolPanel
          toolCount={snapshot.tools.length}
          run={toolController.run}
          error={toolController.error}
          previewTool={toolController.preview}
          callTool={toolController.call}
          isPreviewing={toolController.isPreviewing}
          isCalling={toolController.isCalling}
          canCall={toolController.canCall}
          callBlockedReason={toolController.callBlockedReason}
          invocationLabel={toolController.invocationLabel}
        />
      </SlideOver>
      <SlideOver open={state.activeDrawer === "memory"} title="学习记忆" onClose={closeDrawer}>
        <MemoryPanel
          memoryStatus={snapshot.memoryStatus}
          controller={memoryController}
          sessionSummary={sessionSummary}
          onContinueCurrent={closeDrawer}
          onArchiveAndNew={async () => {
            if (!chatController.threadId) return;
            await chatController.archiveCurrentSession(chatController.threadId);
            closeDrawer();
          }}
        />
      </SlideOver>
      <SlideOver open={state.activeDrawer === "sources"} title="引用来源与知识库" onClose={closeDrawer}>
        <SourcesPanel
          lastChat={chatController.lastChat}
          ragSearch={ragController.result}
          isSearching={ragController.isSearching}
          knowledgeBase={uploadController.documents}
          onDeleteDocument={(documentId) => {
            if (window.confirm("确定从长期知识库中删除这个文档及其索引片段吗？")) {
              void uploadController.removeDocument(documentId);
            }
          }}
        />
      </SlideOver>
      <SlideOver open={state.activeDrawer === "timeline"} title="工作流时间线" onClose={closeDrawer}>
        <TimelinePanel
          runs={snapshot.workflowRuns}
          selectedRun={workflowController.selectedRun}
          loadingRunId={workflowController.loadingRunId}
          onSelectRun={workflowController.selectRun}
        />
      </SlideOver>
      <GlobalNotices
        apiError={snapshot.error}
        operationError={ui.operationError}
        partialErrors={partialErrors}
        onDismissOperationError={() => ui.setOperationError("")}
      />
    </AppShell>
  );
}
