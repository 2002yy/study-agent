import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  RotateCcw,
  ShieldQuestion,
  Target,
} from "lucide-react";
import { useState } from "react";
import { phaseLabel } from "../pedagogy/pedagogyLabels";
import { LearningPanel } from "../learning/LearningPanel";
import { taskContractFromRoute, taskIntentLabel } from "../task/taskContract";
import type { ChatResponse, MemoryStatusResponse } from "../../types";
import {
  projectTrustworthyLearningStatus,
  type LearningVerificationStatus,
} from "./trustworthyLearningStatus";

const VERIFICATION_ICON = {
  verified: CheckCircle2,
  pending_validation: CircleHelp,
  needs_reteach: RotateCcw,
  pending_semantic_review: ShieldQuestion,
} satisfies Record<LearningVerificationStatus, typeof CheckCircle2>;

function nonLearningResultLabel(taskIntent: string): string {
  if (taskIntent === "research") return "研究结果已返回";
  if (taskIntent === "quick_answer") return "回答已完成";
  if (taskIntent === "conversation") return "本轮对话已完成";
  return "本轮任务已完成";
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
  const learning = projectTrustworthyLearningStatus(lastChat?.route?.learning_state);
  const hasState = Boolean(
    learning.state?.protocol || learning.objective || learning.phase
  );

  if (contract && !contract.learning_state_enabled) {
    return (
      <div className="learning-strip task-strip" aria-label="当前任务类型">
        <div className="learning-strip-toggle non-learning-status">
          <span className="learning-strip-summary">
            {taskIntentLabel(contract.task_intent)}
          </span>
          <span className="learning-strip-gap">
            {nonLearningResultLabel(contract.task_intent)} · 不推进长期学习状态
          </span>
        </div>
      </div>
    );
  }

  if (!hasState && !lastChat) return null;

  const VerificationIcon = VERIFICATION_ICON[learning.verification.status];
  const gapOrNext = learning.unresolvedGap
    ? `缺口：${learning.unresolvedGap}`
    : learning.nextAction
      ? `下一步：${learning.nextAction}`
      : "下一步：未记录";

  return (
    <div className="learning-strip">
      <button
        aria-expanded={open}
        className="learning-strip-toggle trustworthy-learning-summary"
        onClick={() => setOpen((value) => !value)}
        type="button"
      >
        <span className="learning-strip-chevron">
          {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </span>
        <span className="learning-strip-status-item learning-strip-objective">
          <Target size={12} />
          <span>{learning.objective || "尚未建立学习目标"}</span>
        </span>
        <span className="learning-strip-status-item learning-strip-phase">
          {learning.phase ? phaseLabel(learning.phase) : "阶段未开始"}
        </span>
        <span
          className={`learning-strip-status-item learning-strip-next${learning.unresolvedGap ? " has-gap" : ""}`}
        >
          {learning.unresolvedGap ? <AlertTriangle size={12} /> : null}
          <span>{gapOrNext}</span>
        </span>
        <span
          className={`learning-verification-badge ${learning.verification.status}`}
          title={learning.verification.detail}
        >
          <VerificationIcon size={12} />
          {learning.verification.label}
        </span>
      </button>
      {open ? (
        <div className="learning-strip-detail">
          <LearningPanel
            lastChat={lastChat}
            visitedPhases={visitedPhases}
            memoryStatus={memoryStatus}
          />
        </div>
      ) : null}
    </div>
  );
}
