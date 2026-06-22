import { CheckCircle2, Loader2, Sparkles, Wrench } from "lucide-react";
import type { ToolRunResponse } from "../../types";
import { translateStatus } from "../../utils/format";

export function ToolPanel({
  toolCount,
  run,
  error,
  previewTool,
  callTool,
  isPreviewing,
  isCalling,
  canCall = true,
  callBlockedReason = "",
  invocationLabel = ""
}: {
  toolCount: number;
  run: ToolRunResponse | null;
  error?: string;
  previewTool: () => void;
  callTool: () => void;
  isPreviewing: boolean;
  isCalling: boolean;
  canCall?: boolean;
  callBlockedReason?: string;
  invocationLabel?: string;
}) {
  const output = run?.status === "previewed" || run?.status === "blocked" ? run.preview : run?.result;
  const outputStatus = typeof output?.status === "string" ? output.status : "";
  const outputLabel = outputStatus ? translateStatus(outputStatus) : run?.reason || "就绪";
  return (
    <section className="panel" id="tools">
      <div className="panel-header">
        <div>
          <h2>工具调用</h2>
          <span>{toolCount} 个已允许工具</span>
        </div>
        <Wrench size={18} />
      </div>
      <div className="tool-actions">
        <button className="tool-button" disabled={isPreviewing} onClick={previewTool} type="button">
          {isPreviewing ? <Loader2 className="spin" size={16} /> : <Sparkles size={16} />}
          预览
        </button>
        <button className="tool-button secondary" disabled={!run || isCalling || !canCall} onClick={callTool} type="button">
          {isCalling ? <Loader2 className="spin" size={16} /> : <CheckCircle2 size={16} />}
          调用
        </button>
      </div>
      {invocationLabel ? <div className="tool-hint">已预览：{invocationLabel}</div> : null}
      {callBlockedReason ? <div className="tool-hint warn">{callBlockedReason}</div> : null}
      {error ? <div className="tool-hint warn">{error}</div> : null}
      {run ? (
        <div className="tool-result">
          <div className="metric-row">
            <span>状态</span>
            <strong>{translateStatus(run.status)}</strong>
          </div>
          <div className="metric-row">
            <span>结果</span>
            <strong>{outputLabel}</strong>
          </div>
          <div className="metric-row">
            <span>运行</span>
            <strong>{run.id}</strong>
          </div>
        </div>
      ) : (
        <div className="empty-state">先预览参数，再调用只读的本地知识检索工具；正式调用会写入工作流审计。</div>
      )}
    </section>
  );
}
