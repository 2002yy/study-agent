import { Check, Clock3, Pencil, Search, X } from "lucide-react";
import { useMemo, useState } from "react";
import type { SessionRow } from "../../types";
import { formatMtime } from "../../utils/format";
import { updateSessionTitle } from "./sessionApi";
import {
  groupSessions,
  matchesSessionSearch,
  sessionSubtitle,
  sessionTitle,
  summaryLabel,
  taskLabel,
  type SemanticSessionRow,
  type SessionGroupMode,
} from "./sessionNavigation";

export function sessionIdFromRow(session: SessionRow): string {
  if (session.session_id) {
    return session.session_id;
  }
  if (session.kind === "current") {
    return session.name.replace(/\.md$/, "");
  }
  const match = session.name.match(/_session_([^_]+)_/);
  return match?.[1] ?? session.name.replace(/\.md$/, "");
}

const GROUP_LABELS: Record<SessionGroupMode, string> = {
  time: "按时间",
  status: "按整理状态",
  task: "按任务类型",
};

export function SessionsPanel({
  sessions,
  activeSessionId,
  isSending,
  onRestore,
  onArchive,
  onSessionChanged,
}: {
  sessions: SessionRow[];
  activeSessionId?: string;
  isSending?: boolean;
  onRestore?: (sessionId: string) => void;
  onArchive?: (sessionId: string) => void;
  onSessionChanged?: () => Promise<void> | void;
}) {
  const [confirmArchiveId, setConfirmArchiveId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [groupMode, setGroupMode] = useState<SessionGroupMode>("time");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState("");
  const [renameError, setRenameError] = useState("");
  const [isRenaming, setIsRenaming] = useState(false);
  const semanticSessions = sessions as SemanticSessionRow[];
  const grouped = useMemo(
    () =>
      groupSessions(
        semanticSessions.filter((session) => matchesSessionSearch(session, query)),
        groupMode
      ),
    [semanticSessions, query, groupMode]
  );

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

  const beginRename = (session: SemanticSessionRow) => {
    setEditingId(sessionIdFromRow(session));
    setEditingTitle(session.manual_title || sessionTitle(session));
    setRenameError("");
  };

  const saveRename = async (session: SemanticSessionRow) => {
    if (isRenaming) return;
    const sessionId = sessionIdFromRow(session);
    setIsRenaming(true);
    setRenameError("");
    try {
      await updateSessionTitle(sessionId, editingTitle);
      setEditingId(null);
      await onSessionChanged?.();
    } catch (error) {
      setRenameError(error instanceof Error ? error.message : "会话标题保存失败");
    } finally {
      setIsRenaming(false);
    }
  };

  return (
    <section className="panel" id="sessions">
      <div className="panel-header">
        <div>
          <h2>会话历史</h2>
          <span>{semanticSessions.length} 个会话 · 从学习状态继续，而不是从文件名猜</span>
        </div>
        <Clock3 size={18} />
      </div>
      <div className="session-navigation-controls wide">
        <label className="session-search-box">
          <Search size={14} />
          <input
            aria-label="搜索历史会话"
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索标题、目标、研究摘要、缺口…"
            value={query}
          />
        </label>
        <select
          aria-label="历史会话分组方式"
          onChange={(event) => setGroupMode(event.target.value as SessionGroupMode)}
          value={groupMode}
        >
          {Object.entries(GROUP_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </div>
      {renameError ? <div className="session-navigation-error">{renameError}</div> : null}
      {grouped.length ? (
        <div className="session-list semantic-session-list">
          {grouped.map((group) => (
            <section className="session-history-group" key={group.key}>
              <div className="session-nav-group-title">{group.label}</div>
              {group.sessions.map((session) => {
                const sessionId = sessionIdFromRow(session);
                const isActive = sessionId === activeSessionId;
                const editing = editingId === sessionId;
                return (
                  <div className="session-row semantic-session-row" key={`${session.kind}-${sessionId}`}>
                    <div className="session-row-copy">
                      {editing ? (
                        <div className="session-title-editor">
                          <input
                            aria-label="会话标题"
                            autoFocus
                            maxLength={120}
                            onChange={(event) => setEditingTitle(event.target.value)}
                            onKeyDown={(event) => {
                              if (event.key === "Enter") void saveRename(session);
                              if (event.key === "Escape") setEditingId(null);
                            }}
                            value={editingTitle}
                          />
                          <button
                            aria-label="保存标题"
                            disabled={isRenaming}
                            onClick={() => void saveRename(session)}
                            type="button"
                          >
                            <Check size={13} />
                          </button>
                          <button
                            aria-label="取消重命名"
                            disabled={isRenaming}
                            onClick={() => setEditingId(null)}
                            type="button"
                          >
                            <X size={13} />
                          </button>
                        </div>
                      ) : (
                        <div className="session-semantic-heading">
                          <strong>{sessionTitle(session)}</strong>
                          <button
                            aria-label="重命名会话"
                            className="icon-button small"
                            disabled={isSending}
                            onClick={() => beginRename(session)}
                            title="重命名"
                            type="button"
                          >
                            <Pencil size={13} />
                          </button>
                        </div>
                      )}
                      <p>{sessionSubtitle(session)}</p>
                      {session.unresolved_gap ? (
                        <span className="session-gap">待解决：{session.unresolved_gap}</span>
                      ) : null}
                      <span>
                        {taskLabel(session.task_intent)}
                        {session.phase ? ` · ${session.phase}` : ""}
                        {` · ${summaryLabel(session)}`}
                        {` · ${formatMtime(session.mtime_ns)}`}
                        {isActive ? " · 当前活跃" : ""}
                      </span>
                    </div>
                    <div className="session-actions">
                      {onRestore ? (
                        <button
                          className="ghost-action compact"
                          disabled={isSending || isActive}
                          type="button"
                          onClick={() => onRestore(sessionId)}
                        >
                          {isActive ? "当前会话" : "继续此会话"}
                        </button>
                      ) : null}
                      {onArchive && session.kind === "current" ? (
                        confirmArchiveId === sessionId ? (
                          <>
                            <span className="archive-confirm-text">归档后将自动新建会话，继续吗？</span>
                            <button
                              className="ghost-action compact danger"
                              disabled={isSending}
                              type="button"
                              onClick={confirmArchive}
                            >
                              确认归档
                            </button>
                            <button
                              className="ghost-action compact"
                              disabled={isSending}
                              type="button"
                              onClick={() => setConfirmArchiveId(null)}
                            >
                              取消
                            </button>
                          </>
                        ) : (
                          <button
                            className="ghost-action compact"
                            disabled={isSending}
                            type="button"
                            onClick={() => handleArchiveClick(sessionId)}
                          >
                            归档
                          </button>
                        )
                      ) : null}
                    </div>
                  </div>
                );
              })}
            </section>
          ))}
        </div>
      ) : (
        <div className="empty-state">
          {query
            ? "没有匹配的会话。"
            : "还没有可展示的会话历史；新回答会先写入当前记录，之后可以归档或恢复。"}
        </div>
      )}
    </section>
  );
}
