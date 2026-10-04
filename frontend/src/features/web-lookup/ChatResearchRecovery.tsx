import { Loader2, RotateCcw } from "lucide-react";
import type { ChatResearchProgress } from "../../types";
import type { ResearchLookupResponse } from "./researchApi";
import { researchStopReasonDisplay } from "./researchStopReason";
import { researchStepLabel, labelFor } from "../../utils/uiLabels";

const stageLabels: Record<string, string> = {
  planned: "正在规划研究",
  searching: "正在搜索",
  assessing: "正在筛选来源",
  reading: "正在读取来源",
  synthesizing: "正在整理证据",
  gating: "正在执行证据校验",
  completed: "研究完成",
  failed: "研究失败",
  cancelled: "研究已停止",
};

function progressMetrics(progress: ChatResearchProgress): string {
  return [
    `候选 ${progress.candidate_count ?? 0}`,
    `已读 ${progress.read_count ?? 0}`,
    `独立证据簇 ${progress.cluster_count ?? 0}`,
    `未闭合关键缺口 ${progress.open_critical_gap_count ?? 0}`,
  ].join(" · ");
}

function terminalProgressDetail(progress: ChatResearchProgress): string {
  if (progress.status === "failed") {
    return `${researchStopReasonDisplay(progress.stop_reason, "联网研究不可用")} 本回答未使用联网来源中的未经校验内容。`;
  }
  return researchStopReasonDisplay(progress.stop_reason, "联网研究已结束");
}

function runDetail(run: ResearchLookupResponse): string {
  if (run.status === "failed") {
    return `${researchStopReasonDisplay(run.stop_reason, "本次研究未完成")}；重试会从已保存的进度继续`;
  }
  if (run.status === "partial") {
    const safetyCopy = "部分结果不会自动用于下一轮聊天；你可以重试以补全研究";
    if (!run.stop_reason) return safetyCopy;
    const reasonDetail = researchStopReasonDisplay(run.stop_reason, "");
    return reasonDetail ? `${reasonDetail} ${safetyCopy}` : safetyCopy;
  }
  if (run.stop_reason) {
    return researchStopReasonDisplay(run.stop_reason, "联网研究已结束");
  }
  if (run.status === "cancelled") {
    return "已停止本次研究；需要时可从已保存的进度重试";
  }
  return labelFor(stageLabels, run.stage, "联网研究已结束");
}

function lineageDetails(run: ResearchLookupResponse) {
  const raw = run.research_context.lineage;
  const lineage = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
  const rawCounts = lineage.evidence_counts;
  const counts = rawCounts && typeof rawCounts === "object"
    ? (rawCounts as Record<string, unknown>)
    : {};
  const count = (key: string) => Number(counts[key] ?? 0);
  return {
    parentQuery: String(lineage.parent_query ?? "既有研究"),
    inherited: count("inherited_candidate"),
    revalidated: count("revalidated"),
    added: count("new"),
    rejected: count("invalid_or_rejected"),
  };
}

export function ChatResearchRecovery({
  run,
  progress = null,
  isBusy,
  canRetry,
  canResume,
  useInChat,
  onRetry,
  onResume,
}: {
  run: ResearchLookupResponse | null;
  progress?: ChatResearchProgress | null;
  isBusy: boolean;
  canRetry: boolean;
  canResume: boolean;
  useInChat: boolean;
  onRetry: () => void;
  onResume: () => void;
}) {
  if (progress && ["pending", "running"].includes(progress.status)) {
    const isDeep = progress.round != null;
    return (
      <div className="memory-note" role="status">
        <Loader2 className="spin" size={16} />
        <div>
          <strong>
            {labelFor(stageLabels, progress.stage, "联网研究进行中")}
            {isDeep ? `（第 ${progress.round} 轮）` : ""}
          </strong>
          <span>
            已发起 {progress.query_attempt_count} 次查询 · {progressMetrics(progress)}
            {isDeep && progress.notes_count
              ? `，已整理 ${progress.notes_count} 条笔记`
              : ""}
            。
          </span>
          {isDeep && progress.last_step_text ? (
            <span className="research-step-line">
              最近一步（{researchStepLabel(progress.last_step_kind)}）：{progress.last_step_text}
            </span>
          ) : null}
        </div>
      </div>
    );
  }
  const progressIsNewer = Boolean(
    progress &&
      !["pending", "running"].includes(progress.status) &&
      (!run || run.run_id !== progress.run_id || run.version < progress.version),
  );
  if (progress && progressIsNewer) {
    const failed = progress.status === "failed";
    return (
      <div className={`memory-note ${failed ? "warn" : ""}`} role="status">
        <div>
          <strong>
            {progress.stop_reason === "evidence_gate_pass"
              ? "研究完成 · 证据校验已通过"
              : progress.status === "partial"
                ? "研究仅得到部分结果"
                : labelFor(stageLabels, progress.stage, "联网研究已结束")}
          </strong>
          <span>
            {terminalProgressDetail(progress)} {progressMetrics(progress)}。
          </span>
        </div>
      </div>
    );
  }
  if (run?.parent_run_id) {
    const lineage = lineageDetails(run);
    const aggregate = run.lineage_summary ?? {};
    return (
      <div className={`memory-note ${run.status === "failed" ? "warn" : ""}`} role="status">
        <div>
          <strong>后续研究 · 已关联父研究</strong>
          <span>父研究：“{lineage.parentQuery}”</span>
          <span>
            继承候选 {lineage.inherited} · 已重新验证 {lineage.revalidated} · 新来源{" "}
            {lineage.added} · 已失效/排除 {lineage.rejected}
          </span>
          <span>
            整条研究链累计搜索 {Number(aggregate.search_count ?? 0)} 次、读取{" "}
            {Number(aggregate.read_count ?? 0)} 次、后续研究 {Number(aggregate.child_count ?? 0)} 个。
          </span>
        </div>
        {canResume ? (
          <button className="ghost-action compact" disabled={isBusy} onClick={onResume} type="button">
            {isBusy ? <Loader2 className="spin" size={14} /> : <RotateCcw size={14} />}
            继续研究
          </button>
        ) : null}
        {canRetry ? (
          <button className="ghost-action compact" disabled={isBusy} onClick={onRetry} type="button">
            {isBusy ? <Loader2 className="spin" size={14} /> : <RotateCcw size={14} />}
            重试研究
          </button>
        ) : null}
      </div>
    );
  }
  if (run?.research_context.run_kind !== "chat_tool_loop") return null;
  const recovered = run.status === "completed" && run.provider_status === "found";
  if (!canRetry && !canResume && !isBusy && !(recovered && useInChat)) return null;
  const detail = runDetail(run);
  const heading = run.status === "partial" ? "研究得到部分可用结果" : labelFor(stageLabels, run.stage, "联网研究可恢复");

  return (
    <div className={`memory-note ${recovered ? "" : "warn"}`} role="status">
      <div>
        <strong>{recovered ? "联网研究已恢复" : heading}</strong>
        <span>
          {recovered && useInChat
            ? "恢复结果已设为下一轮聊天资料。"
            : `${detail}；已保留 ${run.query_attempts.length} 次查询和 ${run.selected_sources.length} 个来源。`}
        </span>
      </div>
      {canResume ? (
        <button className="ghost-action compact" disabled={isBusy} onClick={onResume} type="button">
          {isBusy ? <Loader2 className="spin" size={14} /> : <RotateCcw size={14} />}
          继续研究
        </button>
      ) : null}
      {canRetry ? (
        <button className="ghost-action compact" disabled={isBusy} onClick={onRetry} type="button">
          {isBusy ? <Loader2 className="spin" size={14} /> : <RotateCcw size={14} />}
          重试研究
        </button>
      ) : null}
    </div>
  );
}
