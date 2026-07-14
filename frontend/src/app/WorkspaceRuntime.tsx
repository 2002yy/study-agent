import { useRef, useState } from "react";
import { useWorkspace } from "./WorkspaceProvider";
import { useWorkspaceBootstrap } from "./WorkspaceBootstrap";
import {
  CHAT_SETTINGS_DEFAULTS, RAG_SETTINGS_DEFAULTS
} from "../layout/Sidebar";
import { useWorkspaceControllers } from "./useWorkspaceControllers";
import { useWorkspaceRecovery } from "./useWorkspaceRecovery";
import { WorkspaceView } from "./WorkspaceView";
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
  const learningClosureRunId = workspaceRuntime.activeLearningClosureRunId;
  const ragQueryRunId = workspaceRuntime.activeRagQueryRunId;
  const ragWriteRunId = workspaceRuntime.activeRagWriteRunId;
  const webLookupRunId = workspaceRuntime.activeWebLookupRunId;
  const setWechatThreadId = (threadId?: string) => dispatchWorkspace({ type: "SET_ACTIVE_GROUP_THREAD", threadId });
  const setNewsRunId = (runId?: string) => dispatchWorkspace({ type: "SET_ACTIVE_NEWS_RUN", runId });
  const setToolRunId = (runId?: string) => dispatchWorkspace({ type: "SET_ACTIVE_TOOL_RUN", runId });
  const setMemoryRunId = (runId?: string) => dispatchWorkspace({ type: "SET_ACTIVE_MEMORY_RUN", runId });
  const setLearningClosureRunId = (runId?: string) => dispatchWorkspace({ type: "SET_ACTIVE_LEARNING_CLOSURE_RUN", runId });
  const setRagQueryRunId = (runId?: string) => dispatchWorkspace({ type: "SET_ACTIVE_RAG_QUERY_RUN", runId });
  const setRagWriteRunId = (runId?: string) => dispatchWorkspace({ type: "SET_ACTIVE_RAG_WRITE_RUN", runId });
  const setWebLookupRunId = (runId?: string) => dispatchWorkspace({ type: "SET_ACTIVE_WEB_LOOKUP_RUN", runId });
  const [newsQuery, setNewsQuery] = useState("最新新闻 when:1d");
  const [readArticles, setReadArticles] = useState(true);
  const [operationError, setOperationError] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const controllers = useWorkspaceControllers({
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
      learningClosure: learningClosureRunId,
      ragQuery: ragQueryRunId, ragWrite: ragWriteRunId,
      webLookup: webLookupRunId,
    },
    setGroupThreadId: setWechatThreadId,
    setRunId: {
      news: setNewsRunId, tool: setToolRunId, memory: setMemoryRunId,
      learningClosure: setLearningClosureRunId,
      ragQuery: setRagQueryRunId, ragWrite: setRagWriteRunId,
      webLookup: setWebLookupRunId,
    },
  });
  const { groupThreadId: wechatThreadId, chatController } = controllers;

  useWorkspaceRecovery({
    snapshot,
    chatController,
    ids: {
      singleChat: chatController.threadId,
      group: wechatThreadId,
      news: newsRunId,
      tool: toolRunId,
      memory: memoryRunId,
      learningClosure: learningClosureRunId,
      ragQuery: ragQueryRunId,
      ragWrite: ragWriteRunId,
      webLookup: webLookupRunId,
    },
    setIds: {
      group: setWechatThreadId,
      news: setNewsRunId,
      tool: setToolRunId,
      memory: setMemoryRunId,
      learningClosure: setLearningClosureRunId,
      ragQuery: setRagQueryRunId,
      ragWrite: setRagWriteRunId,
      webLookup: setWebLookupRunId,
    },
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
  });

  return (
    <WorkspaceView
      snapshot={snapshot}
      refresh={refresh}
      fileInputRef={fileInputRef}
      controllers={controllers}
      ui={{
        input,
        setInput,
        ragEnabled,
        setRagEnabled,
        chatSettings,
        setChatSettings,
        ragSettings,
        setRagSettings,
        keepCurrentRole,
        setKeepCurrentRole,
        conversationInstruction,
        setConversationInstruction,
        newsQuery,
        setNewsQuery,
        readArticles,
        setReadArticles,
        operationError,
        setOperationError,
      }}
    />
  );
}
