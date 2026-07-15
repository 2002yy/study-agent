import { describe, expect, it } from "vitest";

import {
  groupSessions,
  matchesSessionSearch,
  sessionSubtitle,
  sessionTitle,
  summaryLabel,
  taskLabel,
  type SemanticSessionRow,
} from "./sessionNavigation";

const base: SemanticSessionRow = {
  session_id: "session-1",
  kind: "current",
  name: "session-1.md",
  path: "",
  size_bytes: 0,
  mtime_ns: 0,
  title: "二分查找复习",
  title_source: "manual",
  manual_title: "二分查找复习",
  auto_title: "理解二分查找",
  objective: "理解二分查找",
  preview: "继续检查边界条件",
  task_intent: "learn",
  phase: "guided_practice",
  unresolved_gap: "left <= right 的边界",
  updated_at: "2026-07-15T10:00:00Z",
  summary: {
    thread_id: "session-1",
    status: "needs_update",
    current_last_completed_turn_id: "turn-2",
    last_completed_turn_id: "turn-1",
    can_summarize: true,
  },
};

describe("semantic session navigation", () => {
  it("prefers manual title and semantic subtitle", () => {
    expect(sessionTitle(base)).toBe("二分查找复习");
    expect(sessionSubtitle(base)).toBe("理解二分查找");
    expect(taskLabel(base.task_intent)).toBe("学习");
    expect(summaryLabel(base)).toBe("有新增内容");
  });

  it("searches title, objective, preview and unresolved gap", () => {
    expect(matchesSessionSearch(base, "二分")).toBe(true);
    expect(matchesSessionSearch(base, "边界")).toBe(true);
    expect(matchesSessionSearch(base, "学习")).toBe(true);
    expect(matchesSessionSearch(base, "已整理")).toBe(false);
    expect(matchesSessionSearch(base, "数据库事务")).toBe(false);
  });

  it("groups by summary status and task intent", () => {
    const research: SemanticSessionRow = {
      ...base,
      session_id: "session-2",
      title: "Python 研究",
      task_intent: "research",
      summary: {
        ...base.summary!,
        thread_id: "session-2",
        status: "summarized",
        can_summarize: false,
      },
    };

    const statusGroups = groupSessions([base, research], "status");
    const taskGroups = groupSessions([base, research], "task");

    expect(statusGroups.map((group) => group.label)).toEqual([
      "有新增内容",
      "本次已整理",
    ]);
    expect(taskGroups.map((group) => group.label)).toEqual(["学习", "研究"]);
  });

  it("groups current-day and older sessions by time", () => {
    const older: SemanticSessionRow = {
      ...base,
      session_id: "session-old",
      updated_at: "2026-07-01T10:00:00Z",
    };
    const groups = groupSessions(
      [base, older],
      "time",
      new Date("2026-07-15T12:00:00Z")
    );

    expect(groups.map((group) => group.label)).toEqual(["今天", "更早"]);
  });
});
