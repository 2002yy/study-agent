import { AlertTriangle, ShieldCheck } from "lucide-react";
import { StatusDot } from "../../components/StatusDot";
import type { MemoryStatusResponse } from "../../types";

export function MemoryPanel({ memoryStatus }: { memoryStatus: MemoryStatusResponse | null }) {
  const focus = memoryStatus?.files.find((file) => file.name === "current_focus.md");
  const progress = memoryStatus?.files.find((file) => file.name === "progress.md");
  const summary = memoryStatus?.files.find((file) => file.name === "summary.md");
  return (
    <section className="panel compact" id="memory">
      <div className="panel-header">
        <div>
          <h2>学习记忆</h2>
          <span>{memoryStatus ? `${memoryStatus.context_mode} · ${memoryStatus.writable ? "可写" : "只读"}` : "等待 API"}</span>
        </div>
        <ShieldCheck size={18} />
      </div>
      {memoryStatus ? (
        <>
          <div className="memory-note">
            <StatusDot tone={memoryStatus.writable ? "good" : memoryStatus.safe_mode ? "bad" : "warn"} />
            <span>
              memory_mode={memoryStatus.memory_mode} · safe_mode={String(memoryStatus.safe_mode)} · reason={memoryStatus.reason}
            </span>
          </div>
          <div className="memory-grid">
            {[focus, progress, summary].map((file) =>
              file ? (
                <details className="memory-file" key={file.name}>
                  <summary>{file.name}</summary>
                  <p>{file.preview || "暂无内容"}</p>
                </details>
              ) : null
            )}
          </div>
        </>
      ) : (
        <div className="memory-note">
          <AlertTriangle size={16} />
          记忆状态接口暂不可用。
        </div>
      )}
    </section>
  );
}
