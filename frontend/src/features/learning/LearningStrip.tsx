import { AlertTriangle, ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";
import { phaseLabel, protocolLabel } from "../pedagogy/pedagogyLabels";
import { LearningPanel } from "../learning/LearningPanel";
import { taskContractFromRoute, taskIntentLabel } from "../task/taskContract";
import type { ChatResponse, MemoryStatusResponse } from "../../types";

function asLearningState(raw: unknown): { protocol?: string; phase?: string; unresolved_gap?: string } | undefined {
  if (!raw || typeof raw !== "object") return undefined;
  const o = raw as Record<string, unknown>;
  return {
    protocol: String(o.protocol ?? ""),
    phase: String(o.phase ?? ""),
    unresolved_gap: String(o.unresolved_gap ?? ""),
  };
}

export function LearningStrip({
  lastChat,
  visitedPhases,
  memoryStatus,
}: {
  lastChat: ChatResponse | null;
  visitedPhases: string[];
  memoryStatus: MemoryStatusResponse | null;
}) {
  const [open, setOpen] = useState(false);
  const contract = taskContractFromRoute(lastChat?.route);
  const state = asLearningState(lastChat?.route?.learning_state);
  const hasState = Boolean(state?.protocol || state?.phase);

  if (contract && !contract.learning_state_enabled) {
    return (
      <div className="learning-strip task-strip" aria-label="当前任务类型">
        <div className="learning-strip-toggle">
          <span className="learning-strip-summary">
            {taskIntentLabel(contract.task_intent)}
          </span>
          <span className="learning-strip-gap">
            本轮不会计入长期学习进度
          </span>
        </div>
      </div>
    );
  }

  if (!hasState && !lastChat) return null;

  return (
    <div className="learning-strip">
      <button
        className="learning-strip-toggle"
        onClick={() => setOpen((v) => !v)}
        type="button"
      >
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        <span className="learning-strip-summary">
          {state?.protocol ? protocolLabel(state.protocol) : ""}
          {state?.phase ? ` · ${phaseLabel(state.phase)}` : ""}
        </span>
        {state?.unresolved_gap ? (
          <span className="learning-strip-gap">
            <AlertTriangle size={12} /> 缺口：{state.unresolved_gap}
          </span>
        ) : null}
      </button>
      {open ? (
        <div className="learning-strip-detail">
          <LearningPanel lastChat={lastChat} visitedPhases={visitedPhases} memoryStatus={memoryStatus} />
        </div>
      ) : null}
    </div>
  );
}
