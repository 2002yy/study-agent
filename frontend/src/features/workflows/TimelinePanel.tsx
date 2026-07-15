import { Clock3, ListChecks } from "lucide-react";
import { StatusDot } from "../../components/StatusDot";
import type { WorkflowRunDetail, WorkflowRunSummary } from "../../types";
import { translateStatus } from "../../utils/format";

const WORKFLOW_LABELS: Record<string, string> = {
  chat: "学习对话",
  single_chat: "学习对话",
  learning_closure: "学习整理",
  memory_update: "记忆更新",
  news_lookup: "新闻研究",
  web_lookup: "联网检索",
  tool_call: "工具调用",
};

export function workflowLabel(name: string): string {
  return WORKFLOW_LABELS[name] ?? "任务运行";
}

export function workflowTimeLabel(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "最近运行";
  return date.toLocaleString("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function workflowDurationLabel(elapsedMs: number): string {
  if (!Number.isFinite(elapsedMs) || elapsedMs < 0) return "-";
  if (elapsedMs < 1000) return `${Math.round(elapsedMs)} 毫秒`;
  return `${(elapsedMs / 1000).toFixed(1)} 秒`;
}

export function TimelinePanel({
  runs,
  selectedRun,
  loadingRunId,
  onSelectRun
}: {
  runs: WorkflowRunSummary[];
  selectedRun: WorkflowRunDetail | null;
  loadingRunId: string;
  onSelectRun: (runId: string) => void;
}) {
  return (
    <section className="panel" id="timeline">
      <div className="panel-header">
        <div>
          <h2>工作流记录</h2>
          <span>最近 {runs.length} 次运行</span>
        </div>
        <ListChecks size={18} />
      </div>
      <div className="timeline">
        {runs.length ? (
          runs.slice(0, 6).map((run) => (
            <button className="timeline-row" key={run.run_id} onClick={() => onSelectRun(run.run_id)} type="button">
              <StatusDot tone={run.status === "succeeded" ? "good" : run.status === "failed" ? "bad" : "warn"} />
              <div>
                <strong>{workflowLabel(run.workflow_name)}</strong>
                <span>{workflowTimeLabel(run.started_at)} · {run.event_count} 个步骤</span>
              </div>
              <em>{loadingRunId === run.run_id ? "..." : workflowDurationLabel(run.elapsed_ms)}</em>
            </button>
          ))
        ) : (
          <div className="empty-state">还没有工作流记录。</div>
        )}
      </div>
      {selectedRun ? (
        <div className="run-detail">
          <div className="run-detail-title">
            <Clock3 size={15} />
            <strong>{workflowLabel(selectedRun.workflow_name)}</strong>
            <span>{workflowTimeLabel(selectedRun.started_at)}</span>
          </div>
          {selectedRun.events.map((event, index) => (
            <div className="event-row" key={`${event.event_type}-${index}`}>
              <StatusDot tone={event.status === "succeeded" ? "good" : event.status === "failed" ? "bad" : "warn"} />
              <div>
                <strong>{event.message || `步骤 ${index + 1}`}</strong>
                <span>{translateStatus(event.status)}</span>
                {event.error ? <em>{event.error}</em> : null}
              </div>
              <small>{workflowDurationLabel(event.elapsed_ms)}</small>
            </div>
          ))}
        </div>
      ) : null}
    </section>
  );
}
