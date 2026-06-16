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
  onRestore
}: {
  sessions: SessionRow[];
  onRestore?: (sessionId: string) => void;
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
          {sessions.slice(0, 5).map((session) => (
            <div className="session-row" key={`${session.kind}-${session.name}`}>
              <strong>{session.name}</strong>
              <span>
                {session.kind} · {formatBytes(session.size_bytes)} · {formatMtime(session.mtime_ns)}
              </span>
              {onRestore ? (
                <button className="ghost-action compact" type="button" onClick={() => onRestore(sessionIdFromRow(session))}>
                  恢复到单人聊天
                </button>
              ) : null}
            </div>
          ))}
        </div>
      ) : (
        <div className="empty-state">还没有可展示的会话历史；新回答会先写入当前 session，后续可接入详情和继续会话 API。</div>
      )}
    </section>
  );
}
