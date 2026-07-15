import {
  Archive,
  Check,
  Pencil,
  Plus,
  Search,
  X,
} from "lucide-react";
import { useMemo, useState } from "react";
import type { SessionRow } from "../../types";
import { sessionIdFromRow } from "./SessionsPanel";
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

type SessionSidebarProps = {
  sessions: SessionRow[];
  activeSessionId?: string;
  isSending?: boolean;
  onRestore?: (sessionId: string) => void;
  onArchive?: (sessionId: string) => void;
  onNewSession?: () => void;
  onSessionChanged?: () => Promise<void> | void;
};

const GROUP_LABELS: Record<SessionGroupMode, string> = {
  time: "按时间",
  status: "按状态",
  task: "按任务",
};

function formatSessionTime(session: SemanticSessionRow): string {
  const time = session.updated_at
    ? new Date(session.updated_at)
    : new Date(Math.floor(session.mtime_ns / 1_000_000));
  if (Number.isNaN(time.getTime())) return "时间未知";
  return time.toLocaleString([], {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function SessionSidebar({
  sessions,
  activeSessionId,
  isSending = false,
  onRestore,
  onArchive,
  onNewSession,
  onSessionChanged,
}: SessionSidebarProps) {
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

  const beginRename = (session: SemanticSessionRow) => {
    const sessionId = sessionIdFromRow(session);
    setEditingId(sessionId);
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
    <aside className="session-sidebar">
      <header className="session-sidebar-header">
        <div>
          <strong>学习会话</strong>
          <span>{semanticSessions.length} 个记录</span>
        </div>
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
      <div className="session-navigation-controls">
        <label className="session-search-box">
          <Search size={14} />
          <input
            aria-label="搜索学习会话"
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索标题、目标、缺口…"
            value={query}
          />
        </label>
        <select
          aria-label="会话分组方式"
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
      <div className="session-sidebar-list">
        {grouped.length ? (
          grouped.map((group) => (
            <section className="session-nav-group" key={group.key}>
              <div className="session-nav-group-title">{group.label}</div>
              {group.sessions.map((session) => {
                const sessionId = sessionIdFromRow(session);
                const isActive = sessionId === activeSessionId;
                const archiving = confirmArchiveId === sessionId;
                const editing = editingId === sessionId;
                return (
                  <div
                    className={`session-sidebar-row${isActive ? " is-active" : ""}`}
                    key={`${session.kind}-${sessionId}`}
                  >
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
                      <button
                        className="session-sidebar-row-main"
                        disabled={isActive}
                        onClick={() => {
                          if (
                            isSending &&
                            !window.confirm("当前回答正在生成，切换会话将停止生成。继续吗？")
                          ) {
                            return;
                          }
                          onRestore?.(sessionId);
                        }}
                        type="button"
                      >
                        <strong>{sessionTitle(session)}</strong>
                        <span className="session-sidebar-subtitle">
                          {sessionSubtitle(session)}
                        </span>
                        {session.unresolved_gap ? (
                          <span className="session-sidebar-gap">
                            待解决：{session.unresolved_gap}
                          </span>
                        ) : null}
                        <span className="session-sidebar-meta">
                          {taskLabel(session.task_intent)}
                          {session.phase ? ` · ${session.phase}` : ""}
                          {` · ${summaryLabel(session)} · ${formatSessionTime(session)}`}
                        </span>
                      </button>
                    )}
                    <div className="session-sidebar-row-actions">
                      {!editing ? (
                        <button
                          aria-label="重命名会话"
                          className="icon-button session-sidebar-rename"
                          disabled={isSending}
                          onClick={() => beginRename(session)}
                          title="重命名"
                          type="button"
                        >
                          <Pencil size={13} />
                        </button>
                      ) : null}
                      {isActive && onArchive ? (
                        archiving ? (
                          <div className="session-sidebar-confirm" onClick={(event) => event.stopPropagation()}>
                            <button
                              className="ghost-action compact danger"
                              disabled={isSending}
                              type="button"
                              onClick={() => {
                                onArchive(sessionId);
                                setConfirmArchiveId(null);
                              }}
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
                          </div>
                        ) : (
                          <button
                            className="icon-button session-sidebar-archive"
                            disabled={isSending}
                            onClick={(event) => {
                              event.stopPropagation();
                              setConfirmArchiveId(sessionId);
                            }}
                            title="归档当前会话"
                            type="button"
                          >
                            <Archive size={14} />
                          </button>
                        )
                      ) : null}
                    </div>
                  </div>
                );
              })}
            </section>
          ))
        ) : (
          <div className="empty-state">
            {query ? "没有匹配的会话。" : "还没有会话。点击“新会话”开始。"}
          </div>
        )}
      </div>
    </aside>
  );
}
