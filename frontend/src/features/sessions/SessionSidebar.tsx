import { Archive, Plus } from "lucide-react";
import { useState } from "react";
import { sessionIdFromRow } from "../sessions/SessionsPanel";
import { formatMtime } from "../../utils/format";
import type { SessionRow } from "../../types";

export function SessionSidebar({
  sessions,
  activeSessionId,
  isSending,
  onRestore,
  onArchive,
  onNewSession,
}: {
  sessions: SessionRow[];
  activeSessionId?: string;
  isSending?: boolean;
  onRestore?: (sessionId: string) => void;
  onArchive?: (sessionId: string) => void;
  onNewSession?: () => void;
}) {
  const [confirmArchiveId, setConfirmArchiveId] = useState<string | null>(null);

  return (
    <aside className="session-sidebar">
      <header className="session-sidebar-header">
        <strong>会话</strong>
        <button
          className="ghost-action compact"
          disabled={isSending}
          onClick={onNewSession}
          type="button"
          title="新建会话"
        >
          <Plus size={14} /> 新会话
        </button>
      </header>
      <div className="session-sidebar-list">
        {sessions.length ? (
          sessions.map((session) => {
            const sessionId = sessionIdFromRow(session);
            const isActive = sessionId === activeSessionId;
            const archiving = confirmArchiveId === sessionId;
            return (
              <div
                className={`session-sidebar-row${isActive ? " is-active" : ""}`}
                key={`${session.kind}-${session.name}`}
              >
                <button
                  className="session-sidebar-row-main"
                  disabled={isActive}
                  onClick={() => {
                    if (isSending && !window.confirm("当前回答正在生成，切换会话将停止生成。继续吗？")) {
                      return;
                    }
                    onRestore?.(sessionId);
                  }}
                  type="button"
                >
                  <strong>{session.name}</strong>
                  <span>{formatMtime(session.mtime_ns)}</span>
                </button>
                {isActive && onArchive ? (
                  archiving ? (
                    <div className="session-sidebar-confirm" onClick={(e) => e.stopPropagation()}>
                      <button className="ghost-action compact danger" disabled={isSending} type="button" onClick={() => { onArchive(sessionId); setConfirmArchiveId(null); }}>
                        确认归档
                      </button>
                      <button className="ghost-action compact" disabled={isSending} type="button" onClick={() => setConfirmArchiveId(null)}>
                        取消
                      </button>
                    </div>
                  ) : (
                    <button
                      className="icon-button session-sidebar-archive"
                      disabled={isSending}
                      onClick={(e) => { e.stopPropagation(); setConfirmArchiveId(sessionId); }}
                      title="归档当前会话"
                      type="button"
                    >
                      <Archive size={14} />
                    </button>
                  )
                ) : null}
              </div>
            );
          })
        ) : (
          <div className="empty-state">还没有会话。点击"新会话"开始。</div>
        )}
      </div>
    </aside>
  );
}
