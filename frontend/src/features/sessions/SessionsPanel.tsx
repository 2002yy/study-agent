import { Clock3 } from "lucide-react";
import type { SessionRow } from "../../types";
import { formatBytes, formatMtime } from "../../utils/format";
import { useState } from "react";

export function sessionIdFromRow(session: SessionRow): string {
  if (session.kind === "current") {
    return session.name.replace(/\.md$/, "");
  }
  const match = session.name.match(/_session_([^_]+)_/);
  return match?.[1] ?? session.name.replace(/\.md$/, "");
}

export function SessionsPanel({
  sessions,
  activeSessionId,
  isSending,
  onRestore,
  onArchive
}: {
  sessions: SessionRow[];
  activeSessionId?: string;
  isSending?: boolean;
  onRestore?: (sessionId: string) => void;
  onArchive?: (sessionId: string) => void;
}) {
  const [confirmArchiveId, setConfirmArchiveId] = useState<string | null>(null);

  const handleArchiveClick = (sessionId: string) => {
    if (sessionId === activeSessionId) {
      setConfirmArchiveId(sessionId);
    } else {
      onArchive?.(sessionId);
    }
  };

  const confirmArchive = () => {
    if (confirmArchiveId) {
      onArchive?.(confirmArchiveId);
      setConfirmArchiveId(null);
    }
  };

  return (
    <section className="panel" id="sessions">
      <div className="panel-header">
        <div>
          <h2>会话历史</h2>
          <span>{sessions.length} 个会话文件</span>
        </div>
        <Clock3 size={18} />
      </div>
      {sessions.length ? (
        <div className="session-list">
          {sessions.slice(0, 5).map((session) => {
            const sessionId = sessionIdFromRow(session);
            const isActive = sessionId === activeSessionId;
            return (
              <div className="session-row" key={`${session.kind}-${session.name}`}>
                <strong>{session.name}</strong>
                <span>
                  {session.kind} · {formatBytes(session.size_bytes)} · {formatMtime(session.mtime_ns)}
                  {isActive ? " · 当前活跃" : ""}
                </span>
                <div className="session-actions">
                  {onRestore ? (
                    <button className="ghost-action compact" disabled={isSending} type="button" onClick={() => onRestore(sessionId)}>
                      恢复到单人聊天
                    </button>
                  ) : null}
                  {onArchive && session.kind === "current" ? (
                    confirmArchiveId === sessionId ? (
                      <>
                        <span className="archive-confirm-text">归档后将自动新建会话，继续吗？</span>
                        <button className="ghost-action compact danger" disabled={isSending} type="button" onClick={confirmArchive}>
                          确认归档
                        </button>
                        <button className="ghost-action compact" disabled={isSending} type="button" onClick={() => setConfirmArchiveId(null)}>
                          取消
                        </button>
                      </>
                    ) : (
                      <button className="ghost-action compact" disabled={isSending} type="button" onClick={() => handleArchiveClick(sessionId)}>
                        归档
                      </button>
                    )
                  ) : null}
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="empty-state">还没有可展示的会话历史；新回答会先写入当前记录，之后可以归档或恢复。</div>
      )}
    </section>
  );
}
