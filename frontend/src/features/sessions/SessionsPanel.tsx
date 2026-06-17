import { Clock3 } from "lucide-react";
import type { SessionRow } from "../../types";
import { formatBytes, formatMtime } from "../../utils/format";

export function sessionIdFromRow(session: SessionRow): string {
  if (session.kind === "current") {
    return session.name.replace(/\.md$/, "");
  }
  const match = session.name.match(/_session_([^_]+)_/);
  return match?.[1] ?? session.name.replace(/\.md$/, "");
}

export function SessionsPanel({
  sessions,
  onRestore,
  onArchive
}: {
  sessions: SessionRow[];
  onRestore?: (sessionId: string) => void;
  onArchive?: (sessionId: string) => void;
}) {
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
            return (
              <div className="session-row" key={`${session.kind}-${session.name}`}>
                <strong>{session.name}</strong>
                <span>
                  {session.kind} · {formatBytes(session.size_bytes)} · {formatMtime(session.mtime_ns)}
                </span>
                <div className="session-actions">
                  {onRestore ? (
                    <button className="ghost-action compact" type="button" onClick={() => onRestore(sessionId)}>
                      恢复到单人聊天
                    </button>
                  ) : null}
                  {onArchive && session.kind === "current" ? (
                    <button className="ghost-action compact" type="button" onClick={() => onArchive(sessionId)}>
                      归档
                    </button>
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
