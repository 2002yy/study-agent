import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  History,
  RotateCcw,
  ShieldQuestion,
  Sparkles,
  Target,
} from "lucide-react";
import { useState } from "react";

import type { ChatResponse, MemoryStatusResponse } from "../../types";
import { phaseLabel } from "../pedagogy/pedagogyLabels";
import { taskContractFromRoute, taskIntentLabel } from "../task/taskContract";
import { useFireflyLessonController } from "./FireflyLessonContext";
import { LearningPanel } from "./LearningPanel";
import type { LearningResumeResponse } from "./learningResumeApi";
import { projectTrustworthyLearningStatus } from "./trustworthyLearningStatus";

function nonLearningResultLabel(taskIntent: string): string {
  if (taskIntent === "research") return "研究结果已返回";
  if (taskIntent === "quick_answer") return "回答已完成";
  if (taskIntent === "conversation") return "本轮对话已完成";
  return "本轮任务已完成";
}

function durableUnderstandingSummary(resume: LearningResumeResponse) {
  if (!resume.claims.length) {
    return {
      label: "等待形成 Claim",
      detail: "当前 Goal 尚无 source-backed Claim。",
      className: "pending_validation",
      icon: CircleHelp,
    };
  }
  const staleCount = resume.claims.filter(
    (claim) => claim.freshness?.status === "stale_candidate",
  ).length;
  if (staleCount) {
    return {
      label: `${staleCount} 条源码已变动`,
      detail: "存在依据的源码已实质变更、尚未重新验证的 Claim。",
      className: "stale_source",
      icon: RotateCcw,
    };
  }
  const counts = {
    confirmed: resume.claims.filter((claim) => claim.understanding_status === "confirmed").length,
    partial: resume.claims.filter((claim) => claim.understanding_status === "partial").length,
    attempted: resume.claims.filter((claim) => claim.understanding_status === "attempted").length,
    proposed: resume.claims.filter((claim) => claim.understanding_status === "proposed").length,
  };
  if (counts.attempted) {
    return {
      label: `${counts.attempted} 条待重验`,
      detail: "存在已尝试但当前未通过验证的 Claim。",
      className: "needs_reteach",
      icon: RotateCcw,
    };
  }
  if (counts.partial) {
    return {
      label: `${counts.partial} 条部分理解`,
      detail: "存在 UnderstandingEvidence=partial 的 Claim。",
      className: "pending_semantic_review",
      icon: ShieldQuestion,
    };
  }
  if (counts.proposed) {
    return {
      label: `${counts.proposed} 条待验证`,
      detail: "存在已有源码依据但尚无 UnderstandingEvidence 的 Claim。",
      className: "pending_validation",
      icon: CircleHelp,
    };
  }
  return {
    label: `${counts.confirmed} 条已验证`,
    detail: "当前展示的 Claim 均有 durable pass UnderstandingEvidence。",
    className: "verified",
    icon: CheckCircle2,
  };
}

export function LearningStrip({
  resume,
  resumeError,
  sessionId,
  onRevalidated,
  lastChat,
  visitedPhases,
  memoryStatus,
}: {
  resume: LearningResumeResponse | null;
  resumeError: string;
  sessionId?: string;
  onRevalidated?: () => void;
  lastChat: ChatResponse | null;
  visitedPhases: string[];
  memoryStatus: MemoryStatusResponse | null;
}) {
  const fireflyLesson = useFireflyLessonController();
  const [open, setOpen] = useState(() => Boolean(fireflyLesson?.state.active));
  const contract = taskContractFromRoute(lastChat?.route);
  const durableActive = resume?.source === "durable" && resume.status === "active";

  if (fireflyLesson?.state.active && !durableActive) {
    return (
      <div className="learning-strip firefly-learning-strip" aria-label="默认流萤课程">
        <button
          aria-expanded={open}
          className="learning-strip-toggle trustworthy-learning-summary durable-learning-summary"
          onClick={() => setOpen((value) => !value)}
          type="button"
        >
          <span className="learning-strip-chevron">
            {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          </span>
          <span className="learning-strip-status-item learning-strip-objective">
            <Sparkles size={12} />
            <span>流萤超击破体系</span>
          </span>
          <span className="learning-strip-status-item learning-strip-phase">
            默认示例 · 10张机制卡
          </span>
          <span className="learning-strip-status-item learning-strip-next">
            <span>首领实验 · 一金怎么花</span>
          </span>
          <span className="learning-verification-badge pending_validation">
            4.2加强后口径
          </span>
        </button>
        {open ? (
          <div className="learning-strip-detail firefly-learning-detail">
            <LearningPanel
              resume={resume}
              resumeError={resumeError}
              sessionId={sessionId}
              onRevalidated={onRevalidated}
              lastChat={lastChat}
              visitedPhases={visitedPhases}
              memoryStatus={memoryStatus}
            />
          </div>
        ) : null}
      </div>
    );
  }

  if (contract && !contract.learning_state_enabled && !durableActive) {
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

  if (!resume && !resumeError) {
    if (!lastChat) return null;
    return (
      <div className="learning-strip" aria-label="学习恢复状态">
        <div className="learning-strip-toggle non-learning-status">
          <span className="learning-strip-summary">正在读取 durable ResumeContext…</span>
          <span className="learning-strip-gap">未确认 legacy_fallback 前不读取旧学习状态</span>
        </div>
      </div>
    );
  }

  if (!resume && resumeError) {
    return (
      <div className="learning-strip" aria-label="学习恢复状态">
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
            <AlertTriangle size={12} />
            <span>durable 学习状态暂不可用</span>
          </span>
          <span className="learning-strip-status-item learning-strip-phase">不回退旧状态</span>
          <span className="learning-strip-status-item learning-strip-next">
            <span>打开查看错误</span>
          </span>
          <span className="learning-verification-badge pending_semantic_review">读取失败</span>
        </button>
        {open ? (
          <div className="learning-strip-detail">
            <LearningPanel
              resume={null}
              resumeError={resumeError}
              sessionId={sessionId}
              onRevalidated={onRevalidated}
              lastChat={lastChat}
              visitedPhases={visitedPhases}
              memoryStatus={memoryStatus}
            />
          </div>
        ) : null}
      </div>
    );
  }

  if (!resume) return null;

  if (resume.source === "durable") {
    const noActiveGoal = resume.status === "no_active_goal";
    const summary = durableUnderstandingSummary(resume);
    const SummaryIcon = summary.icon;
    const objective = noActiveGoal
      ? "当前没有进行中的学习目标"
      : resume.goal.objective || resume.topic.title || "当前 durable Goal";
    const next = noActiveGoal
      ? "已有 durable context，不回退旧 learning_state"
      : resume.unresolved[0]?.text
        ? `Hypothesis：${resume.unresolved[0].text}`
        : resume.next_step.text
          ? `下一步：${resume.next_step.text}`
          : "下一步：未记录";

    return (
      <div className="learning-strip">
        <button
          aria-expanded={open}
          className="learning-strip-toggle trustworthy-learning-summary durable-learning-summary"
          onClick={() => setOpen((value) => !value)}
          type="button"
        >
          <span className="learning-strip-chevron">
            {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          </span>
          <span className="learning-strip-status-item learning-strip-objective">
            <Target size={12} />
            <span>{objective}</span>
          </span>
          <span className="learning-strip-status-item learning-strip-phase">
            {noActiveGoal
              ? "durable · no active Goal"
              : `Claims ${resume.claims.length}/${resume.claim_count}`}
          </span>
          <span
            className={`learning-strip-status-item learning-strip-next${resume.unresolved.length ? " has-gap" : ""}`}
          >
            {resume.unresolved.length ? <AlertTriangle size={12} /> : null}
            <span>{next}</span>
          </span>
          <span
            className={`learning-verification-badge ${noActiveGoal ? "pending_validation" : summary.className}`}
            title={noActiveGoal ? "durable context 已存在；没有 active Goal。" : summary.detail}
          >
            {noActiveGoal ? <CircleHelp size={12} /> : <SummaryIcon size={12} />}
            {noActiveGoal ? "无 active Goal" : summary.label}
          </span>
        </button>
        {open ? (
          <div className="learning-strip-detail">
            <LearningPanel
              resume={resume}
              resumeError=""
              sessionId={sessionId}
              onRevalidated={onRevalidated}
              lastChat={lastChat}
              visitedPhases={visitedPhases}
              memoryStatus={memoryStatus}
            />
          </div>
        ) : null}
      </div>
    );
  }

  const legacy = projectTrustworthyLearningStatus(lastChat?.route?.learning_state);
  const objective = resume.goal.objective || legacy.objective || "旧会话学习状态";
  const next = resume.unresolved[0]?.text
    ? `旧缺口：${resume.unresolved[0].text}`
    : resume.next_step.text
      ? `旧下一步：${resume.next_step.text}`
      : "旧会话未记录下一步";

  return (
    <div className="learning-strip legacy-learning-strip">
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
          <History size={12} />
          <span>{objective}</span>
        </span>
        <span className="learning-strip-status-item learning-strip-phase">
          {legacy.phase ? phaseLabel(legacy.phase) : "legacy fallback"}
        </span>
        <span className="learning-strip-status-item learning-strip-next">
          <span>{next}</span>
        </span>
        <span className="learning-verification-badge pending_validation">
          <History size={12} /> 旧记录 · 未升级
        </span>
      </button>
      {open ? (
        <div className="learning-strip-detail">
          <LearningPanel
            resume={resume}
            resumeError=""
            sessionId={sessionId}
            onRevalidated={onRevalidated}
            lastChat={lastChat}
            visitedPhases={visitedPhases}
            memoryStatus={memoryStatus}
          />
        </div>
      ) : null}
    </div>
  );
}
