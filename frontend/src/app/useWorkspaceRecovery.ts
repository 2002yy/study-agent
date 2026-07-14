import { useCallback, useEffect, useMemo, useRef } from "react";
import type { Dispatch, SetStateAction } from "react";

import { createEmptyRag, useChatController } from "../features/chat/chatController";
import { seedMessages } from "../features/single-chat/chatHistory";
import {
  CHAT_SETTINGS_DEFAULTS,
  RAG_SETTINGS_DEFAULTS,
  modeOptions,
} from "../layout/Sidebar";
import type { ApiSnapshot, ChatSettings, RagSettings } from "../types";
import {
  useWorkspacePersistence,
  type WorkspaceRecovery,
} from "./WorkspacePersistence";

type DirectSetter = (value?: string) => void;

export function useWorkspaceRecovery(options: {
  snapshot: ApiSnapshot;
  chatController: ReturnType<typeof useChatController>;
  ids: {
    singleChat?: string;
    group?: string;
    news?: string;
    tool?: string;
    memory?: string;
    learningClosure?: string;
    ragQuery?: string;
    ragWrite?: string;
    webLookup?: string;
  };
  setIds: {
    group: DirectSetter;
    news: DirectSetter;
    tool: DirectSetter;
    memory: DirectSetter;
    learningClosure: DirectSetter;
    ragQuery: DirectSetter;
    ragWrite: DirectSetter;
    webLookup: DirectSetter;
  };
  chatSettings: ChatSettings;
  setChatSettings: Dispatch<SetStateAction<ChatSettings>>;
  ragSettings: RagSettings;
  setRagSettings: Dispatch<SetStateAction<RagSettings>>;
  ragEnabled: boolean;
  setRagEnabled: Dispatch<SetStateAction<boolean>>;
  keepCurrentRole: boolean;
  setKeepCurrentRole: Dispatch<SetStateAction<boolean>>;
  conversationInstruction: string;
  setConversationInstruction: Dispatch<SetStateAction<string>>;
}) {
  const runtimeHydratedRef = useRef(false);
  const sessionSettingsRestoredRef = useRef(false);
  const {
    chatController,
    chatSettings,
    ragSettings,
    ragEnabled,
    keepCurrentRole,
    conversationInstruction,
  } = options;

  const restoreWorkspace = useCallback((parsed: WorkspaceRecovery | null) => {
    if (!parsed) {
      chatController.setMessages(seedMessages);
      return;
    }
    const restoredThreadId = parsed.singleChatSessionId ?? parsed.sessionId ?? "";
    if (parsed.wechatThreadId) options.setIds.group(parsed.wechatThreadId);
    if (parsed.newsRunId) options.setIds.news(parsed.newsRunId);
    if (parsed.toolRunId) options.setIds.tool(parsed.toolRunId);
    if (parsed.memoryRunId) options.setIds.memory(parsed.memoryRunId);
    if (parsed.learningClosureRunId) {
      options.setIds.learningClosure(parsed.learningClosureRunId);
    }
    if (parsed.ragQueryRunId) options.setIds.ragQuery(parsed.ragQueryRunId);
    if (parsed.ragWriteRunId) options.setIds.ragWrite(parsed.ragWriteRunId);
    if (parsed.webLookupRunId) options.setIds.webLookup(parsed.webLookupRunId);
    if (parsed.chatSettings) {
      sessionSettingsRestoredRef.current = true;
      options.setChatSettings({
        ...CHAT_SETTINGS_DEFAULTS,
        ...parsed.chatSettings,
      });
    }
    if (parsed.ragSettings) {
      sessionSettingsRestoredRef.current = true;
      options.setRagSettings({ ...RAG_SETTINGS_DEFAULTS, ...parsed.ragSettings });
    }
    if (typeof parsed.ragEnabled === "boolean") {
      sessionSettingsRestoredRef.current = true;
      options.setRagEnabled(parsed.ragEnabled);
    }
    if (typeof parsed.keepCurrentRole === "boolean") {
      options.setKeepCurrentRole(parsed.keepCurrentRole);
    }
    if (typeof parsed.conversationInstruction === "string") {
      options.setConversationInstruction(parsed.conversationInstruction);
    }
    if (restoredThreadId) {
      void chatController.hydrateSession(restoredThreadId, parsed.cachedMessages);
    } else {
      chatController.setMessages(seedMessages);
    }
    if (parsed.lastRoute) {
      chatController.setLastChat({
        reply: "",
        session_id: parsed.lastSessionId ?? restoredThreadId ?? "restored",
        route: parsed.lastRoute,
        rag: parsed.lastRag ?? createEmptyRag(),
      });
    }
  }, [chatController, options.setIds]);

  useEffect(() => {
    const settings = options.snapshot.runtimeSettings?.settings;
    if (!settings || runtimeHydratedRef.current) return;
    runtimeHydratedRef.current = true;
    if (sessionSettingsRestoredRef.current) return;
    const visibleMode = modeOptions.some(([value]) => value === settings.selected_mode)
      ? settings.selected_mode
      : "auto";
    options.setChatSettings({
      selectedRole: settings.selected_role,
      selectedMode: visibleMode,
      selectedModel: settings.selected_model,
      relationshipMode: settings.relationship_mode,
      contextMode:
        settings.context_mode === "fast" ||
        settings.context_mode === "light" ||
        settings.context_mode === "deep"
          ? settings.context_mode
          : "",
    });
    options.setRagEnabled(settings.rag_enabled);
    options.setRagSettings({
      retrievalMode: settings.rag_retrieval_mode,
      topK: settings.rag_search_top_k ?? settings.rag_top_k,
      chatTopK: settings.rag_chat_top_k ?? settings.rag_top_k,
      minScore: settings.rag_min_score,
    });
  }, [options.snapshot.runtimeSettings]);

  const persistenceState = useMemo(
    () => ({
      singleChatSessionId: options.ids.singleChat,
      wechatThreadId: options.ids.group,
      newsRunId: options.ids.news,
      toolRunId: options.ids.tool,
      memoryRunId: options.ids.memory,
      learningClosureRunId: options.ids.learningClosure,
      ragQueryRunId: options.ids.ragQuery,
      ragWriteRunId: options.ids.ragWrite,
      webLookupRunId: options.ids.webLookup,
      chatSettings,
      ragSettings,
      ragEnabled,
      keepCurrentRole,
      conversationInstruction,
      lastRoute: chatController.lastChat?.route,
      lastRag: chatController.lastChat?.rag,
      lastSessionId: chatController.lastChat?.session_id,
      cachedMessages: chatController.messages,
      isSending: chatController.isSending,
    }),
    [
      options.ids,
      chatSettings,
      ragSettings,
      ragEnabled,
      keepCurrentRole,
      conversationInstruction,
      chatController.lastChat,
      chatController.messages,
      chatController.isSending,
    ]
  );
  useWorkspacePersistence({ state: persistenceState, onRestore: restoreWorkspace });
}
