import type { Dispatch, RefObject, SetStateAction } from "react";
import { useState } from "react";

import AppShell from "../AppShell";
import { SlideOver } from "../components/SlideOver";
import { LearningStrip } from "../features/learning/LearningStrip";
import { MemoryPanel } from "../features/learning-memory/MemoryPanel";
import { SourcesPanel } from "../features/rag/SourcesPanel";
import { UploadLearningPrompt } from "../features/rag/UploadLearningPrompt";
import { RAG_UPLOAD_ACCEPT, RAG_UPLOAD_HELP_TEXT } from "../features/rag/uploadContract";
import { SettingsPanel } from "../features/settings/SettingsPanel";
import { ExternalDataFirstUseNotice } from "../features/settings/ExternalDataFirstUseNotice";
import { ChatPanel } from "../features/single-chat/ChatPanel";
import { MemoryConsentBadge } from "../features/chat/MemoryConsentBadge";
import { SessionNavigator } from "../features/sessions/SessionNavigator";
import { WorkspaceTransitionDialog } from "../features/sessions/WorkspaceTransitionDialog";
import { useWorkspaceTransitionGuard } from "../features/sessions/workspaceTransitionGuard";
import { GlobalNotices } from "../layout/GlobalNotices";
import type { ApiSnapshot, ChatSettings, DrawerId, RagSettings } from "../types";
import { ExtensionDrawers } from "./ExtensionDrawers";
import type { ExtensionViewModel } from "./useExtensionRuntime";
import type { LearningSessionRuntime } from "./useLearningSessionRuntime";
import { useWorkspace } from "./WorkspaceProvider";
import { ReadingLayout, ReadingWorkspaceProvider } from "../features/reading/ReadingWorkspace";
import type { useWorkspaceControllers } from "./useWorkspaceControllers";

type Controllers = ReturnType<typeof useWorkspaceControllers>;
type LearningView = LearningSessionRuntime["view"];

export function WorkspaceView({
  snapshot,
  refresh,
  fileInputRef,
  ui,
  controllers,
  learningView,
  extensionView,
}: {
  snapshot: ApiSnapshot;
  refresh: () => Promise<void>;
  fileInputRef: RefObject<HTMLInputElement | null>;
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
    operationError: string;
    setOperationError: Dispatch<SetStateAction<string>>;
  };
  controllers: Controllers;
  learningView: LearningView;
  extensionView: ExtensionViewModel;
}) {
  const {
    roleController,
    settingsController,
    webLookupController,
    memoryController,
    ragController,
    uploadController,
    chatController,
  } = controllers;
  const { state, dispatch } = useWorkspace();
  const [readingNavigationKey, setReadingNavigationKey] = useState(0);
  const [sourcesInitialTab, setSourcesInitialTab] = useState<"answer" | "library">("answer");
  const openDrawer = (drawer: DrawerId) => {
    if (drawer === "sources") setSourcesInitialTab("answer");
    dispatch({ type: "OPEN_DRAWER", drawer });
  };
  const openReadingLibrary = () => {
    setSourcesInitialTab("library");
    dispatch({ type: "OPEN_DRAWER", drawer: "sources" });
  };
  const closeDrawer = () => dispatch({ type: "CLOSE_DRAWER" });
  // G16 decision 1: badge only participates under the ask policy.
  const memoryPolicy = String(
    snapshot.runtimeSettings?.settings?.memory_policy ?? "auto",
  );

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    await chatController.send(ui.input.trim());
  };

  const requestUpload = (mode: "upload" | "rebuild" = "upload") => {
    uploadController.setMode(mode);
    fileInputRef.current?.click();
  };

  const handleUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    if (!files.length) return;
    const selectedMode = uploadController.mode;
    if (
      selectedMode === "rebuild" &&
      !window.confirm(
        `将用本次 ${files.length} 个文件重建整个资料索引，现有资料索引会被替换。继续吗？`,
      )
    ) {
      event.target.value = "";
      uploadController.setMode("upload");
      return;
    }
    await uploadController.upload(files);
    uploadController.setMode("upload");
    event.target.value = "";
  };

  const partialErrors = Object.entries(snapshot.errors ?? {}).filter(
    ([key]) => key !== "health",
  );
  const transitionGuard = useWorkspaceTransitionGuard({
    isSending: learningView.isSending,
    hasUserMessages: chatController.messages.some((message) => message.role === "user"),
    summaryStatus: learningView.sessionSummary?.status,
    memoryBusy:
      memoryController.isPreviewing ||
      memoryController.isCommitting ||
      Boolean(
        memoryController.closureRun &&
          ["created", "collecting", "generating", "committing"].includes(
            memoryController.closureRun.status,
          ),
    ),
    memoryPreviewReady: Boolean(
      (memoryController.run?.status === "previewed" && memoryController.preview?.writable) ||
        memoryController.closureRun?.status === "preview_ready",
    ),
    researchStatus: webLookupController.result?.status,
    researchBusy: webLookupController.isBusy,
    ragWriteBusy: uploadController.isUploading,
  });
  const closeTransitionSource = () => {
    if (state.activeDrawer) closeDrawer();
  };
  const requestNewSession = () => {
    closeTransitionSource();
    transitionGuard.request("new", () => {
      setReadingNavigationKey(key => key + 1);
      return chatController.startNewSession();
    });
  };
  const requestRestoreSession = (sessionId: string) => {
    closeTransitionSource();
    transitionGuard.request("switch", () => {
      setReadingNavigationKey(key => key + 1);
      return chatController.restoreSession(sessionId);
    });
  };
  const requestArchiveSession = (sessionId: string) => {
    closeTransitionSource();
    transitionGuard.request("archive", () => {
      setReadingNavigationKey(key => key + 1);
      return chatController.archiveCurrentSession(sessionId);
    });
  };

  return (
    <ReadingWorkspaceProvider
      sessionId={learningView.sessionId}
      navigationKey={readingNavigationKey}
      documents={uploadController.documents?.documents ?? []}
      isSending={learningView.isSending}
      onAsk={(prompt) => ui.setInput(current => current.trim() ? `${current}\n\n${prompt}` : prompt)}
      onOpen={closeDrawer}
      onBrowse={openReadingLibrary}
    >
    <AppShell>
      <input
        accept={RAG_UPLOAD_ACCEPT}
        aria-describedby="rag-upload-policy"
        aria-label="上传资料"
        className="visually-hidden"
        multiple
        onChange={handleUpload}
        ref={fileInputRef}
        type="file"
      />
      <span className="visually-hidden" id="rag-upload-policy">
        {RAG_UPLOAD_HELP_TEXT}
      </span>
      <SessionNavigator
        sessions={snapshot.sessions}
        activeSessionId={learningView.sessionId}
        isSending={learningView.isSending}
        onRestore={requestRestoreSession}
        onArchive={requestArchiveSession}
        onNewSession={requestNewSession}
        onSessionChanged={refresh}
      />
      <ReadingLayout>
      <div className="chat-column">
        <LearningStrip
          resume={learningView.learningResume}
          resumeError={learningView.learningResumeError}
          sessionId={learningView.sessionId ?? undefined}
          onRevalidated={learningView.refreshLearningResume}
          lastChat={chatController.lastChat}
          visitedPhases={learningView.visitedPhases}
          memoryStatus={snapshot.memoryStatus}
        />
        <UploadLearningPrompt
          phase={uploadController.flowPhase}
          status={uploadController.status}
          detail={uploadController.detail}
          uploadCount={uploadController.lastUploadCount}
          onStartLearning={() => {
            ui.setInput("请基于刚上传的资料开始系统学习。先和我确认学习目标，再逐步讲解并验证我的理解：");
            uploadController.dismissFlow();
          }}
          onAskDirectly={() => {
            ui.setInput("请基于刚上传的资料回答我的问题：");
            uploadController.dismissFlow();
          }}
          onChooseAgain={() => {
            uploadController.dismissFlow();
            requestUpload("upload");
          }}
          onDismiss={uploadController.dismissFlow}
        />
        <MemoryConsentBadge
          memoryPolicy={memoryPolicy}
          onChanged={() => void refresh()}
          sessionId={learningView.sessionId}
        />
        <ChatPanel
          sessionId={learningView.sessionId}
          sessionNavigation={learningView.activeSession}
          messages={chatController.messages}
          input={ui.input}
          setInput={ui.setInput}
          isSending={learningView.isSending}
          onSubmit={submit}
          onStop={chatController.stop}
          streamRecovery={learningView.streamRecovery}
          onContinueInterruptedReply={chatController.continueInterrupted}
          onRetry={chatController.retry}
          onAbandonInterruptedReply={learningView.abandonRecovery}
          onCopyInterruptedReply={chatController.copyInterrupted}
          onUploadClick={() => requestUpload("upload")}
          onSearchSources={() => ragController.search(extensionView.activeQuery)}
          isSearching={ragController.isSearching}
          hasSearchQuery={Boolean(extensionView.activeQuery)}
          onQuickPrompt={ui.setInput}
          onStartNewTopic={requestNewSession}
          lastChat={chatController.lastChat}
          ragEnabled={ui.ragEnabled}
          memoryStatus={snapshot.memoryStatus}
          onOpenDrawer={openDrawer}
          onEndSession={async () => {
            if (!learningView.sessionId) return;
            await memoryController.generateFromSession(learningView.sessionId);
            openDrawer("memory");
          }}
          isEndingSession={memoryController.isPreviewing}
          researchRun={webLookupController.result}
          researchProgress={chatController.researchProgress}
          isResearchBusy={webLookupController.isBusy}
          canRetryResearch={webLookupController.canRetry}
          canResumeResearch={webLookupController.canResume}
          useResearchInChat={webLookupController.useInChat}
          enterToSend={snapshot.runtimeSettings?.settings?.enter_to_send !== false}
          onRetryResearch={() => void webLookupController.retry()}
          onResumeResearch={() => void webLookupController.resume()}
          firstUseNotice={snapshot.runtimeSettings?.settings ? (
            <ExternalDataFirstUseNotice
              webPolicy={String(snapshot.runtimeSettings.settings.web_policy ?? "auto")}
              cloudContextPolicy={String(
                snapshot.runtimeSettings.settings.cloud_context_policy ?? "allow_local_evidence",
              )}
              onOpenSettings={() => openDrawer("settings")}
            />
          ) : null}
        />
      </div>

      </ReadingLayout>
      <SlideOver open={state.activeDrawer === "sessions"} title="会话历史" onClose={closeDrawer}>
        <SessionNavigator
          sessions={snapshot.sessions}
          activeSessionId={learningView.sessionId}
          isSending={learningView.isSending}
          onRestore={requestRestoreSession}
          onArchive={requestArchiveSession}
          onNewSession={requestNewSession}
          onSessionChanged={refresh}
          variant="panel"
        />
      </SlideOver>

      <SlideOver open={state.activeDrawer === "settings"} title="设置" onClose={closeDrawer}>
        <SettingsPanel
          snapshot={snapshot}
          ragEnabled={ui.ragEnabled}
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
          isSending={learningView.isSending}
          refresh={refresh}
          lastChat={chatController.lastChat}
        />
      </SlideOver>

      <ExtensionDrawers view={extensionView} onClose={closeDrawer} />

      <SlideOver open={state.activeDrawer === "memory"} title="学习成果" onClose={closeDrawer}>
        <MemoryPanel
          memoryStatus={snapshot.memoryStatus}
          controller={memoryController}
          sessionSummary={learningView.sessionSummary}
          onContinueCurrent={closeDrawer}
          onArchiveAndNew={() => {
            if (!learningView.sessionId) return;
            requestArchiveSession(learningView.sessionId);
          }}
        />
      </SlideOver>

      <SlideOver open={state.activeDrawer === "sources"} title="资料与来源" onClose={closeDrawer}>
        <SourcesPanel
          key={sourcesInitialTab}
          initialTab={sourcesInitialTab}
          lastChat={chatController.lastChat}
          ragSearch={ragController.result}
          isSearching={ragController.isSearching}
          knowledgeBase={uploadController.documents}
          sessionId={learningView.sessionId}
          onDeleteDocument={(documentId) => {
            if (window.confirm("确定从长期资料中删除这个文档及其索引片段吗？")) {
              void uploadController.removeDocument(documentId);
            }
          }}
          onRebuildKnowledge={() => requestUpload("rebuild")}
        />
      </SlideOver>

      <GlobalNotices
        apiError={snapshot.error}
        operationError={ui.operationError}
        partialErrors={partialErrors}
        onRetryApi={() => void refresh()}
        onOpenSettings={() => openDrawer("settings")}
        onDismissOperationError={() => ui.setOperationError("")}
      />
      <WorkspaceTransitionDialog
        notice={transitionGuard.notice}
        onCancel={transitionGuard.cancel}
        onConfirm={transitionGuard.confirm}
      />
    </AppShell>
    </ReadingWorkspaceProvider>
  );
}
