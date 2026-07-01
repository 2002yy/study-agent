import { useEffect, useMemo } from "react";
import type { Dispatch, SetStateAction } from "react";

import type { LocalKnowledgeInvocation } from "../api";
import { createEmptyRag, useChatController } from "../features/chat/chatController";
import { useGroupChatController } from "../features/group-chat/groupChatController";
import { useMemoryController } from "../features/learning-memory/memoryController";
import { useNewsController } from "../features/news-workspace/newsController";
import { useRagController } from "../features/rag/ragController";
import { useUploadController } from "../features/rag/uploadController";
import { useRoleController } from "../features/roles/roleController";
import { useSettingsController } from "../features/settings/settingsController";
import { useToolController } from "../features/tools/toolController";
import { useWebLookupController } from "../features/web-lookup/webLookupController";
import { useWorkflowController } from "../features/workflows/workflowController";
import {
  CHAT_SETTINGS_DEFAULTS,
  RAG_SETTINGS_DEFAULTS,
} from "../layout/Sidebar";
import type { ApiSnapshot, ChatSettings, RagSettings } from "../types";
import { operationRegistry } from "./operationRegistry";
import { WorkspaceCoordinator } from "./WorkspaceCoordinator";

type ValueSetter<T> = Dispatch<SetStateAction<T>>;
type DirectSetter<T> = (value: T) => void;

export function useWorkspaceControllers(options: {
  snapshot: ApiSnapshot;
  setSnapshot: React.Dispatch<React.SetStateAction<ApiSnapshot>>;
  refresh: () => Promise<void>;
  input: string;
  setInput: ValueSetter<string>;
  chatSettings: ChatSettings;
  setChatSettings: ValueSetter<ChatSettings>;
  ragSettings: RagSettings;
  setRagSettings: ValueSetter<RagSettings>;
  ragEnabled: boolean;
  setRagEnabled: ValueSetter<boolean>;
  keepCurrentRole: boolean;
  setKeepCurrentRole: ValueSetter<boolean>;
  conversationInstruction: string;
  setConversationInstruction: ValueSetter<string>;
  newsQuery: string;
  readArticles: boolean;
  operationError: ValueSetter<string>;
  activeGroupThreadId?: string;
  runIds: {
    news?: string;
    tool?: string;
    memory?: string;
    ragQuery?: string;
    ragWrite?: string;
    webLookup?: string;
  };
  setGroupThreadId: DirectSetter<string | undefined>;
  setRunId: {
    news: DirectSetter<string | undefined>;
    tool: DirectSetter<string | undefined>;
    memory: DirectSetter<string | undefined>;
    ragQuery: DirectSetter<string | undefined>;
    ragWrite: DirectSetter<string | undefined>;
    webLookup: DirectSetter<string | undefined>;
  };
}) {
  const roleController = useRoleController(options.chatSettings.selectedRole);
  const workflowController = useWorkflowController();
  const settingsController = useSettingsController({
    chatSettings: options.chatSettings,
    ragSettings: options.ragSettings,
    ragEnabled: options.ragEnabled,
    setRuntimeSettings: (runtimeSettings) =>
      options.setSnapshot((current) => ({ ...current, runtimeSettings })),
    setOperationError: options.operationError,
    refresh: options.refresh,
  });
  const groupThreadId =
    options.activeGroupThreadId ?? options.snapshot.wechat?.group_thread_id;
  const groupController = useGroupChatController({
    wechat: options.snapshot.wechat,
    setWechat: (wechat) =>
      options.setSnapshot((current) => ({ ...current, wechat })),
    chatSettings: options.chatSettings,
    ragSettings: options.ragSettings,
    ragEnabled: options.ragEnabled,
    clearAssociatedNews: () => options.setRunId.news(undefined),
  });
  const newsController = useNewsController({
    query: options.newsQuery,
    readArticles: options.readArticles,
    chatSettings: options.chatSettings,
    groupThreadId,
    activeRunId: options.runIds.news,
    setActiveRunId: options.setRunId.news,
    onDiscussed: (threadId) => {
      options.setGroupThreadId(threadId);
      void options.refresh();
    },
  });
  const webLookupController = useWebLookupController({
    query: options.newsQuery,
    setOperationError: options.operationError,
    activeRunId: options.runIds.webLookup,
    setActiveRunId: options.setRunId.webLookup,
  });
  const memoryController = useMemoryController({
    activeRunId: options.runIds.memory,
    setActiveRunId: options.setRunId.memory,
    onMemoryChanged: options.refresh,
  });
  const ragController = useRagController({
    settings: options.ragSettings,
    activeRunId: options.runIds.ragQuery,
    setActiveRunId: options.setRunId.ragQuery,
    setOperationError: options.operationError,
  });
  const uploadController = useUploadController({
    activeRunId: options.runIds.ragWrite,
    setActiveRunId: options.setRunId.ragWrite,
    setOperationError: options.operationError,
    onChanged: options.refresh,
  });
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
          clearToolRun: () => options.setRunId.tool(undefined),
          clearWorkflow: workflowController.clear,
        }
      ),
    [
      groupController.cancelWorkspace,
      newsController.cancelWorkspace,
      webLookupController.cancel,
      ragController.clear,
      workflowController.clear,
      options.setRunId.tool,
    ]
  );
  const chatController = useChatController({
    chatSettings: options.chatSettings,
    chatSettingsDefaults: CHAT_SETTINGS_DEFAULTS,
    setChatSettings: options.setChatSettings,
    ragSettings: options.ragSettings,
    ragSettingsDefaults: RAG_SETTINGS_DEFAULTS,
    setRagSettings: options.setRagSettings,
    ragEnabled: options.ragEnabled,
    setRagEnabled: options.setRagEnabled,
    keepCurrentRole: options.keepCurrentRole,
    setKeepCurrentRole: options.setKeepCurrentRole,
    conversationInstruction: options.conversationInstruction,
    setConversationInstruction: options.setConversationInstruction,
    webLookupSource: webLookupController.result?.source_block ?? "",
    useWebLookup: webLookupController.useInChat,
    setUseWebLookup: webLookupController.setUseInChat,
    setInput: options.setInput,
    setOperationError: options.operationError,
    clearChatArtifacts:
      workspaceCoordinator.clearChatArtifacts.bind(workspaceCoordinator),
    onWorkspaceCancelled:
      workspaceCoordinator.cancelAllActiveOperations.bind(workspaceCoordinator),
    refresh: options.refresh,
  });
  const activeQuery =
    options.input.trim() || chatController.lastChat?.rag?.query || "";
  const currentToolInvocation: LocalKnowledgeInvocation = {
    query: activeQuery,
    retrievalMode: options.ragSettings.retrievalMode,
    topK: options.ragSettings.chatTopK,
    minScore: options.ragSettings.minScore,
  };
  const toolController = useToolController({
    invocation: currentToolInvocation,
    activeRunId: options.runIds.tool,
    setActiveRunId: options.setRunId.tool,
    onCalled: options.refresh,
  });

  useEffect(() => {
    const serverThreadId = options.snapshot.wechat?.group_thread_id;
    if (serverThreadId && options.activeGroupThreadId !== serverThreadId) {
      options.setGroupThreadId(serverThreadId);
    }
  }, [
    options.snapshot.wechat?.group_thread_id,
    options.activeGroupThreadId,
    options.setGroupThreadId,
  ]);

  return {
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
    createEmptyRag,
  };
}
