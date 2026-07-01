import { useEffect, useRef } from "react";

import { SESSION_STORAGE_KEY } from "../features/single-chat/chatHistory";
import type { ChatMessage, ChatResponse, ChatSettings, RagSettings } from "../types";

export const WORKSPACE_STORAGE_SCHEMA_VERSION = 2;

export type WorkspaceRecovery = {
  sessionId?: string;
  singleChatSessionId?: string;
  wechatThreadId?: string;
  newsRunId?: string;
  toolRunId?: string;
  memoryRunId?: string;
  ragQueryRunId?: string;
  ragWriteRunId?: string;
  webLookupRunId?: string;
  chatSettings?: ChatSettings;
  ragSettings?: RagSettings;
  ragEnabled?: boolean;
  keepCurrentRole?: boolean;
  conversationInstruction?: string;
  lastRoute?: ChatResponse["route"];
  lastRag?: ChatResponse["rag"];
  lastSessionId?: string;
  cachedMessages?: ChatMessage[];
};

export type WorkspacePersistenceState = WorkspaceRecovery & {
  isSending: boolean;
};

type StoredWorkspaceEnvelope = {
  schemaVersion: number;
  savedAt: string;
  workspace: WorkspaceRecovery;
};

export function parseWorkspaceRecovery(raw: string): WorkspaceRecovery | null {
  try {
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    if (parsed.schemaVersion === WORKSPACE_STORAGE_SCHEMA_VERSION) {
      const workspace = parsed.workspace;
      return workspace && typeof workspace === "object"
        ? (workspace as WorkspaceRecovery)
        : null;
    }
    // Version 1 stored workspace fields at the root. Read once and rewrite as v2.
    return parsed as WorkspaceRecovery;
  } catch {
    return null;
  }
}

export function serializeWorkspaceRecovery(
  workspace: WorkspaceRecovery
): string {
  const envelope: StoredWorkspaceEnvelope = {
    schemaVersion: WORKSPACE_STORAGE_SCHEMA_VERSION,
    savedAt: new Date().toISOString(),
    workspace,
  };
  return JSON.stringify(envelope);
}

export function useWorkspacePersistence(options: {
  state: WorkspacePersistenceState;
  onRestore: (recovery: WorkspaceRecovery | null) => void;
}) {
  const payloadRef = useRef("");
  const restoredRef = useRef(false);

  useEffect(() => {
    if (restoredRef.current) return;
    restoredRef.current = true;
    const raw = window.localStorage.getItem(SESSION_STORAGE_KEY);
    const recovery = raw ? parseWorkspaceRecovery(raw) : null;
    if (raw && !recovery) window.localStorage.removeItem(SESSION_STORAGE_KEY);
    options.onRestore(recovery);
  }, [options.onRestore]);

  useEffect(() => {
    const { isSending, ...workspace } = options.state;
    const payload = serializeWorkspaceRecovery(workspace);
    payloadRef.current = payload;
    const timeout = window.setTimeout(() => {
      window.localStorage.setItem(SESSION_STORAGE_KEY, payload);
    }, isSending ? 800 : 200);
    return () => window.clearTimeout(timeout);
  }, [options.state]);

  useEffect(() => {
    const flush = () => {
      if (document.visibilityState === "hidden" && payloadRef.current) {
        window.localStorage.setItem(SESSION_STORAGE_KEY, payloadRef.current);
      }
    };
    document.addEventListener("visibilitychange", flush);
    return () => document.removeEventListener("visibilitychange", flush);
  }, []);
}
