import { Clock3, ListChecks } from "lucide-react";
import { StatusDot } from "../../components/StatusDot";
import type { WorkflowRunDetail, WorkflowRunSummary } from "../../types";
import { translateStatus } from "../../utils/format";

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
          <h2>工作流时间线</h2>
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
                <strong>{run.workflow_name}</strong>
                <span>{run.run_id}</span>
              </div>
              <em>{loadingRunId === run.run_id ? "..." : `${run.elapsed_ms} ms`}</em>
            </button>
          ))
        ) : (
          <div className="empty-state">还没有工作流审计事件。</div>
        )}
      </div>
      {selectedRun ? (
        <div className="run-detail">
          <div className="run-detail-title">
            <Clock3 size={15} />
            <strong>{selectedRun.run_id}</strong>
          </div>
          {selectedRun.events.map((event, index) => (
            <div className="event-row" key={`${event.event_type}-${index}`}>
              <StatusDot tone={event.status === "succeeded" ? "good" : event.status === "failed" ? "bad" : "warn"} />
              <div>
                <strong>{translateStatus(event.event_type)}</strong>
                <span>{event.message || event.step_id}</span>
                {event.error ? <em>{event.error}</em> : null}
              </div>
              <small>{event.elapsed_ms} ms</small>
            </div>
          ))}
        </div>
      ) : null}
    </section>
  );
}
