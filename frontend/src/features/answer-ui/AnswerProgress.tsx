import { Loader2 } from "lucide-react";
import type { ChatResearchProgress } from "../../types";
import { approachFocus, approachSummary, isResearchActive } from "../web-lookup/researchApproach";

const stages: Record<string, string> = {
  planned: "正在规划查找范围", searching: "正在搜索资料", assessing: "正在筛选来源",
  reading: "正在阅读来源", synthesizing: "正在整理证据", gating: "正在核对答案与来源",
};

export function AnswerProgress({ hasContent, progress }: { hasContent: boolean; progress?: ChatResearchProgress | null }) {
  const researching = isResearchActive(progress);
  const cancelled = progress?.status === "cancelled";
  const summary = approachSummary(progress);
  const focus = approachFocus(progress);
  const statusText = researching
    ? stages[progress!.stage] ?? "正在查找资料"
    : cancelled
      ? "研究已停止"
      : hasContent
        ? "回答正在补充，可以先阅读"
        : "正在组织回答";
  return <div className="answer-progress" role="status" aria-live="polite">
    {/* Terminal states must not keep spinning. */}
    {researching ? <Loader2 className="spin" size={14} /> : null}
    {/* Research opening: display-only, never part of the answer text. */}
    {summary ? <span className="answer-progress-approach">{summary}</span> : null}
    {focus.length ? <span className="answer-progress-focus">{focus.join(" · ")}</span> : null}
    <span>{statusText}</span>
    {researching ? <span>已查询 {progress!.query_attempt_count} 次 · 已读 {progress!.read_count ?? 0} 份{hasContent ? "" : " · 核验后显示结论"}</span> : null}
  </div>;
}
