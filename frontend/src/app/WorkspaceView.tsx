import type { Dispatch, RefObject, SetStateAction } from "react";

import AppShell from "../AppShell";
import { ChatPanel } from "../features/single-chat/ChatPanel";
import { GlobalNotices } from "../layout/GlobalNotices";
import { Inspector } from "../layout/Inspector";
import { Sidebar } from "../layout/Sidebar";
import type { ApiSnapshot, ChatSettings, RagSettings } from "../types";
import type { useWorkspaceControllers } from "./useWorkspaceControllers";

type Controllers = ReturnType<typeof useWorkspaceControllers>;

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
  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    await chatController.send(ui.input.trim());
  };
  const handleUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    if (!files.length) return;
    if (
      uploadController.mode === "rebuild" &&
      !window.confirm(
        `将用本次 ${files.length} 个文件重建整个知识库索引，旧索引会被替换。继续吗？`
      )
    ) {
      event.target.value = "";
      return;
    }
    await uploadController.upload(files);
    event.target.value = "";
  };
  const partialErrors = Object.entries(snapshot.errors ?? {}).filter(
    ([key]) => key !== "health"
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
        onNewSession={chatController.startNewSession}
        isSending={chatController.isSending}
        refresh={refresh}
        onUploadClick={() => fileInputRef.current?.click()}
        uploadState={uploadController.status}
        lastChat={chatController.lastChat}
      />
      <ChatPanel
        sessionId={chatController.threadId}
        messages={chatController.messages}
        input={ui.input}
        setInput={ui.setInput}
        isSending={chatController.isSending}
        onSubmit={submit}
        onStop={chatController.stop}
        streamRecovery={chatController.streamRecovery}
        onContinueInterruptedReply={chatController.continueInterrupted}
        onRetry={chatController.retry}
        onCopyInterruptedReply={chatController.copyInterrupted}
        onUploadClick={() => fileInputRef.current?.click()}
        onSearchSources={() => ragController.search(activeQuery)}
        isSearching={ragController.isSearching}
        hasSearchQuery={Boolean(activeQuery)}
        onQuickPrompt={ui.setInput}
        lastChat={chatController.lastChat}
        ragEnabled={ui.ragEnabled}
        memoryStatus={snapshot.memoryStatus}
      />
      <Inspector
        snapshot={snapshot}
        singleChatSessionId={chatController.threadId}
        wechatThreadId={groupThreadId}
        lastChat={chatController.lastChat}
        ragSearch={ragController.result}
        isSearching={ragController.isSearching}
        selectedRun={workflowController.selectedRun}
        loadingRunId={workflowController.loadingRunId}
        selectRun={workflowController.selectRun}
        toolController={toolController}
        onRestoreSession={chatController.restoreSession}
        onArchiveSession={chatController.archiveCurrentSession}
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
        onWechatOpening={groupController.opening}
        onWechatReset={groupController.reset}
        onWechatMarkRead={groupController.markRead}
        onSendWechat={groupController.send}
        onStopWechat={groupController.stop}
        onLookupNews={webLookupController.lookup}
        isWechatBusy={groupController.isBusy}
        wechatError={groupController.error}
        isNewsBusy={webLookupController.isBusy}
        isSending={chatController.isSending}
        memoryController={memoryController}
        uploadController={uploadController}
      />
      <GlobalNotices
        apiError={snapshot.error}
        operationError={ui.operationError}
        partialErrors={partialErrors}
        onDismissOperationError={() => ui.setOperationError("")}
      />
    </AppShell>
  );
}
