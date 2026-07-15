import type { SessionRow } from "../../types";
import type { SessionSummary } from "./sessionSummary";

export type SessionGroupMode = "time" | "status" | "task";

export type DisclosedSessionSource = {
  source_id?: string;
  type?: string;
  citation: string;
};

export type SemanticSessionRow = SessionRow & {
  status?: string;
  version?: number;
  navigation_schema_version?: string;
  title?: string;
  title_source?: "auto" | "manual" | string;
  manual_title?: string;
  auto_title?: string;
  objective?: string;
  research_summary?: string;
  preview?: string;
  task_intent?: string;
  phase?: string;
  unresolved_gap?: string;
  confirmed_points?: string[];
  next_action?: string;
  disclosed_sources?: DisclosedSessionSource[];
  last_completed_turn_id?: string | null;
  has_completed_turns?: boolean;
  summary?: SessionSummary;
  updated_at?: string;
};

export const TASK_LABELS: Record<string, string> = {
  learn: "学习",
  explain_back: "理解检验",
  research: "研究",
  project_execution: "项目",
  organize: "整理",
  quick_answer: "问答",
  conversation: "对话",
};

export const SUMMARY_LABELS: Record<string, string> = {
  summarized: "本次已整理",
  needs_update: "有新增内容",
  not_summarized: "待整理",
};

export function sessionTitle(session: SemanticSessionRow): string {
  return session.title?.trim() || session.name || session.session_id || "未命名会话";
}

export function sessionSubtitle(session: SemanticSessionRow): string {
  if (session.objective?.trim()) return session.objective.trim();
  if (session.research_summary?.trim()) return session.research_summary.trim();
  return session.preview?.trim() || "暂无内容预览";
}

export function taskLabel(intent?: string): string {
  return TASK_LABELS[intent ?? ""] ?? "其他";
}

export function summaryLabel(session: SemanticSessionRow): string {
  const status = session.summary?.status ?? "not_summarized";
  return SUMMARY_LABELS[status] ?? "待整理";
}

export function matchesSessionSearch(
  session: SemanticSessionRow,
  query: string
): boolean {
  const normalized = query.trim().toLowerCase();
  if (!normalized) return true;
  return [
    sessionTitle(session),
    session.objective,
    session.research_summary,
    session.preview,
    session.unresolved_gap,
    session.phase,
    ...(session.confirmed_points ?? []),
    ...(session.disclosed_sources ?? []).map((source) => source.citation),
    taskLabel(session.task_intent),
    summaryLabel(session),
  ]
    .filter(Boolean)
    .some((value) => String(value).toLowerCase().includes(normalized));
}

export function groupSessions(
  sessions: SemanticSessionRow[],
  mode: SessionGroupMode,
  now = new Date()
): Array<{ key: string; label: string; sessions: SemanticSessionRow[] }> {
  const groups = new Map<string, { label: string; sessions: SemanticSessionRow[] }>();
  for (const session of sessions) {
    const { key, label } = groupDescriptor(session, mode, now);
    const group = groups.get(key) ?? { label, sessions: [] };
    group.sessions.push(session);
    groups.set(key, group);
  }
  return Array.from(groups.entries()).map(([key, group]) => ({ key, ...group }));
}

function groupDescriptor(
  session: SemanticSessionRow,
  mode: SessionGroupMode,
  now: Date
): { key: string; label: string } {
  if (mode === "status") {
    const status = session.summary?.status ?? "not_summarized";
    return { key: status, label: SUMMARY_LABELS[status] ?? "待整理" };
  }
  if (mode === "task") {
    const intent = session.task_intent || "other";
    return { key: intent, label: taskLabel(intent) };
  }
  const updated = session.updated_at ? new Date(session.updated_at) : null;
  if (!updated || Number.isNaN(updated.getTime())) {
    return { key: "older", label: "更早" };
  }
  const dayMs = 24 * 60 * 60 * 1000;
  const startToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  if (updated.getTime() >= startToday) {
    return { key: "today", label: "今天" };
  }
  if (updated.getTime() >= startToday - 6 * dayMs) {
    return { key: "week", label: "最近 7 天" };
  }
  return { key: "older", label: "更早" };
}
