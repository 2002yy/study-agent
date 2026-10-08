import { Archive, Check, Pencil, Search, X } from "lucide-react";

import {
  sessionIdFromRow,
  sessionSubtitle,
  sessionTitle,
  summaryLabel,
  taskLabel,
  type SemanticSessionRow,
  type SessionGroupMode,
} from "./sessionNavigation";
import { useSessionNavigator } from "./useSessionNavigator";

const GROUP_LABELS: Record<SessionGroupMode, string> = {
  time: "按时间",
  status: "按整理状态",
  task: "按任务类型",
};

type Navigator = ReturnType<typeof useSessionNavigator>;

function SessionRowView({
  session,
  navigator,
  isSending,
  canArchive,
}: {
  session: SemanticSessionRow;
  navigator: Navigator;
  isSending: boolean;
  canArchive: boolean;
}) {
  const sessionId = sessionIdFromRow(session);
  const isActive = sessionId === navigator.activeSessionId;
  const isEditing = sessionId === navigator.editingId;

  return (
    <article
      aria-current={isActive ? "page" : undefined}
      className={`session-sidebar-row${isActive ? " is-active" : ""}`}
    >
      {isEditing ? (
        <div className="session-title-editor">
          <input
            aria-label="会话标题"
            autoFocus
            maxLength={120}
            onChange={(event) => navigator.setEditingTitle(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") void navigator.saveRename(session);
              if (event.key === "Escape") navigator.cancelRename();
            }}
            value={navigator.editingTitle}
          />
          <button
            aria-label="保存标题"
            disabled={navigator.isRenaming}
            onClick={() => void navigator.saveRename(session)}
            type="button"
          >
            <Check size={13} />
          </button>
          <button
            aria-label="取消重命名"
            disabled={navigator.isRenaming}
            onClick={navigator.cancelRename}
            type="button"
          >
            <X size={13} />
          </button>
        </div>
      ) : (
        <button
          className="session-sidebar-row-main"
          disabled={isActive}
          onClick={() => navigator.restore(sessionId)}
          type="button"
        >
          <strong>{sessionTitle(session)}</strong>
          <span className="session-sidebar-subtitle">{sessionSubtitle(session)}</span>
          {session.unresolved_gap ? (
            <span className="session-sidebar-gap">待解决：{session.unresolved_gap}</span>
          ) : null}
          <span className="session-sidebar-meta">
            {taskLabel(session.task_intent)}
            {session.phase ? ` · ${session.phase}` : ""}
            {` · ${summaryLabel(session)}`}
            {isActive ? " · 当前会话" : ""}
          </span>
        </button>
      )}
      <div className="session-sidebar-row-actions">
        {!isEditing ? (
          <button
            aria-label="重命名会话"
            className="icon-button session-sidebar-rename"
            disabled={isSending}
            onClick={() => navigator.beginRename(session)}
            type="button"
          >
            <Pencil size={13} />
          </button>
        ) : null}
        {isActive && canArchive ? (
          <button
            aria-label="归档当前会话"
            className="icon-button session-sidebar-archive"
            onClick={() => navigator.requestArchive(sessionId)}
            type="button"
          >
            <Archive size={14} />
          </button>
        ) : null}
      </div>
    </article>
  );
}

export function SessionNavigatorBody({
  navigator,
  isSending,
  canArchive,
  isPanel,
}: {
  navigator: Navigator;
  isSending: boolean;
  canArchive: boolean;
  isPanel: boolean;
}) {
  return (
    <>
      <div className="session-history-heading"><span>最近对话</span><small>{navigator.semanticSessions.length}</small></div>
      <details className="session-history-filter">
        <summary><Search aria-hidden="true" size={14}/><span>查找会话</span></summary>
      <div className={`session-navigation-controls${isPanel ? " wide" : ""}`}>
        <label className="session-search-box">
          <Search aria-hidden="true" size={14} />
          <input
            aria-label="搜索学习会话"
            onChange={(event) => navigator.setQuery(event.target.value)}
            placeholder="搜索对话…"
            value={navigator.query}
          />
        </label>
        <select
          aria-label="会话分组方式"
          onChange={(event) =>
            navigator.setGroupMode(event.target.value as SessionGroupMode)
          }
          value={navigator.groupMode}
        >
          {Object.entries(GROUP_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </div>
      </details>
      {navigator.renameError ? (
        <div className="session-navigation-error" role="alert">
          {navigator.renameError}
        </div>
      ) : null}
      {navigator.serverError ? (
        <div className="session-navigation-error" role="status">
          {navigator.serverError}
        </div>
      ) : null}
      <nav aria-label="学习会话" className="session-sidebar-list">
        {navigator.grouped.length ? (
          navigator.grouped.map((group) => (
            <section className="session-nav-group" key={group.key}>
              <h3 className="session-nav-group-title">{group.label}</h3>
              {group.sessions.map((session) => (
                <SessionRowView
                  canArchive={canArchive}
                  isSending={isSending}
                  key={`${session.kind}-${sessionIdFromRow(session)}`}
                  navigator={navigator}
                  session={session}
                />
              ))}
            </section>
          ))
        ) : (
          <div className="empty-state">
            {navigator.query
              ? "没有匹配的会话。"
              : "还没有会话。点击“新会话”开始。"}
          </div>
        )}
      </nav>
      {navigator.hasMore ? (
        <button
          className="ghost-action compact session-load-more"
          disabled={navigator.isServerSearching}
          onClick={() => void navigator.loadMore()}
          type="button"
        >
          {navigator.isServerSearching
            ? "加载中…"
            : `加载更多会话（已显示 ${navigator.grouped.length}/${navigator.serverTotal}）`}
        </button>
      ) : null}
    </>
  );
}
