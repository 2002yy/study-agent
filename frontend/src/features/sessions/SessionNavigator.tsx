import type { ReactNode } from "react";
import { BookOpen, Plus } from "lucide-react";
import { ReadingLibraryNavigation } from "../reading/ReadingLibraryNavigation";

import type { SessionRow } from "../../types";
import { SessionNavigatorBody } from "./SessionNavigatorBody";
import {
  useSessionNavigator,
  type SessionNavigatorActions,
} from "./useSessionNavigator";

export type SessionNavigatorProps = SessionNavigatorActions & {
  sessions: SessionRow[];
  activeSessionId?: string;
  isSending?: boolean;
  onNewSession?: () => void;
  variant?: "sidebar" | "panel";
  actions?: ReactNode;
};

export function SessionNavigator({
  sessions,
  activeSessionId,
  isSending = false,
  onRestore,
  onArchive,
  onNewSession,
  onSessionChanged,
  variant = "sidebar",
  actions,
}: SessionNavigatorProps) {
  const navigator = useSessionNavigator(sessions, activeSessionId, {
    onRestore,
    onArchive,
    onSessionChanged,
  });
  const isPanel = variant === "panel";
  const body = (
    <SessionNavigatorBody
      canArchive={Boolean(onArchive)}
      isPanel={isPanel}
      isSending={isSending}
      navigator={navigator}
    />
  );

  if (isPanel) {
    return (
      <section className="panel session-navigator panel-mode" id="sessions">
        <div className="panel-header">
          <div>
            <h2>会话历史</h2>
            <span>{navigator.semanticSessions.length} 个会话 · 从学习状态继续</span>
          </div>
          {onNewSession ? (
            <button
              className="ghost-action compact"
              onClick={onNewSession}
              type="button"
            >
              <Plus size={14} /> 新会话
            </button>
          ) : null}
        </div>
        <ReadingLibraryNavigation/>
        {body}
        {actions}
      </section>
    );
  }

  return (
    <aside className="session-sidebar session-navigator">
      <header className="session-sidebar-header">
        <div className="workspace-sidebar-brand">
          <BookOpen size={20} aria-hidden="true"/>
          <strong>学习工作台</strong>
        </div>
        <button
          className="ghost-action compact"
          aria-label="新会话"
          onClick={onNewSession}
          type="button"
        >
          <Plus size={17} /> 新对话
        </button>
      </header>
      <ReadingLibraryNavigation/>
      {body}
      {actions}
    </aside>
  );
}
