import {
  Activity, BookOpen, Database, FileText, MemoryStick, MessageSquare, Wrench
} from "lucide-react";
import type { FormEvent } from "react";
import { MemoryPanel } from "../features/learning-memory/MemoryPanel";
import { useMemoryController } from "../features/learning-memory/memoryController";
import { RoadmapPanel } from "../features/migration/RoadmapPanel";
import type { NewsController } from "../features/news-workspace/newsController";
import { SourcesPanel } from "../features/rag/SourcesPanel";
import { useUploadController } from "../features/rag/uploadController";
import { RoutePanel } from "../features/route/RoutePanel";
import { SessionsPanel } from "../features/sessions/SessionsPanel";
import { ToolPanel } from "../features/tools/ToolPanel";
import type { ToolController } from "../features/tools/toolController";
import { WechatPanel } from "../features/wechat-workspace/WechatPanel";
import type { ResearchLookupResponse } from "../features/web-lookup/researchApi";
import { TimelinePanel } from "../features/workflows/TimelinePanel";
import { displayValue } from "../utils/format";
import type {
  ApiSnapshot, ChatResponse, RagQueryResponse, WorkflowRunDetail
} from "../types";

export function Inspector({
  snapshot,
  singleChatSessionId,
  wechatThreadId,
  lastChat,
  ragSearch,
  isSearching,
  selectedRun,
  loadingRunId,
  selectRun,
  toolController,
  onRestoreSession,
  onArchiveSession,
  newsController,
  webLookup,
  useWebLookup,
  setUseWebLookup,
  wechatInput,
  setWechatInput,
  newsQuery,
  setNewsQuery,
  readArticles,
  setReadArticles,
  onWechatOpening,
  onWechatReset,
  onWechatMarkRead,
  onSendWechat,
  onStopWechat,
  onLookupNews,
  isWechatBusy,
  wechatError,
  isNewsBusy,
  isSending,
  memoryController,
  uploadController
}: {
  snapshot: ApiSnapshot;
  singleChatSessionId?: string;
  wechatThreadId?: string;
  lastChat: ChatResponse | null;
  ragSearch: RagQueryResponse | null;
  isSearching: boolean;
  selectedRun: WorkflowRunDetail | null;
  loadingRunId: string;
  selectRun: (runId: string) => void;
  toolController: ToolController;
  onRestoreSession: (sessionId: string) => void;
  onArchiveSession: (sessionId: string) => void;
  newsController: NewsController;
  webLookup: ResearchLookupResponse | null;
  useWebLookup: boolean;
  setUseWebLookup: (value: boolean) => void;
  wechatInput: string;
  setWechatInput: (value: string) => void;
  newsQuery: string;
  setNewsQuery: (value: string) => void;
  readArticles: boolean;
  setReadArticles: (value: boolean) => void;
  onWechatOpening: () => void;
  onWechatReset: () => void;
  onWechatMarkRead: () => void;
  onSendWechat: (event: FormEvent) => void;
  onStopWechat: () => void;
  onLookupNews: () => void;
  isWechatBusy: boolean;
  wechatError: string;
  isNewsBusy: boolean;
  isSending: boolean;
  memoryController: ReturnType<typeof useMemoryController>;
  uploadController: ReturnType<typeof useUploadController>;
}) {
  return (
    <aside className="inspector">
      <RoutePanel lastChat={lastChat} />
      <WechatPanel
        wechat={snapshot.wechat}
        newsController={newsController}
        webLookup={webLookup}
        useWebLookup={useWebLookup}
        setUseWebLookup={setUseWebLookup}
        wechatInput={wechatInput}
        setWechatInput={setWechatInput}
        newsQuery={newsQuery}
        setNewsQuery={setNewsQuery}
        readArticles={readArticles}
        setReadArticles={setReadArticles}
        sessionId={wechatThreadId}
        onOpening={onWechatOpening}
        onReset={onWechatReset}
        onMarkRead={onWechatMarkRead}
        onSendWechat={onSendWechat}
        onStopWechat={onStopWechat}
        onLookupNews={onLookupNews}
        isWechatBusy={isWechatBusy}
        error={wechatError}
        isNewsBusy={isNewsBusy}
      />
      <SourcesPanel
        lastChat={lastChat}
        ragSearch={ragSearch}
        isSearching={isSearching}
        knowledgeBase={uploadController.documents}
        onDeleteDocument={(documentId) => void uploadController.removeDocument(documentId)}
      />
      <TimelinePanel
        runs={snapshot.workflowRuns}
        selectedRun={selectedRun}
        loadingRunId={loadingRunId}
        onSelectRun={selectRun}
      />
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
      <SessionsPanel sessions={snapshot.sessions} activeSessionId={singleChatSessionId} isSending={isSending} onRestore={onRestoreSession} onArchive={onArchiveSession} />
      <RoadmapPanel />
      <MemoryPanel memoryStatus={snapshot.memoryStatus} controller={memoryController} />
    </aside>
  );
}

export const inspectorLabels = {
  activity: Activity,
  book: BookOpen,
  database: Database,
  file: FileText,
  memory: MemoryStick,
  message: MessageSquare,
  wrench: Wrench,
  displayValue
};
