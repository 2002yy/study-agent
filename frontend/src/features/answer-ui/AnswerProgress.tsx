import { Loader2 } from "lucide-react";
import type { ChatResearchProgress } from "../../types";

const stages: Record<string, string> = {
  planned: "正在规划查找范围", searching: "正在搜索资料", assessing: "正在筛选来源",
  reading: "正在阅读来源", synthesizing: "正在整理证据", gating: "正在核对答案与来源",
};

export function AnswerProgress({ hasContent, progress }: { hasContent: boolean; progress?: ChatResearchProgress | null }) {
  const researching = progress && ["pending", "running"].includes(progress.status);
  return <div className="answer-progress" role="status" aria-live="polite">
    <Loader2 className="spin" size={14} />
    <span>{researching ? stages[progress.stage] ?? "正在查找资料" : hasContent ? "回答正在补充，可以先阅读" : "正在组织回答"}</span>
    {researching ? <span>已查询 {progress.query_attempt_count} 次 · 已读 {progress.read_count ?? 0} 份{hasContent ? "" : " · 核验后显示结论"}</span> : null}
  </div>;
}
