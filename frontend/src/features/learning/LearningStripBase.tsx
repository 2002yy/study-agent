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
import { useEffect, useState } from "react";

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
      label: "等待形成学习命题",
      detail: "当前学习目标尚无 有来源依据的学习命题。",
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
      detail: "存在依据的源码已实质变更、尚未重新验证的学习命题。",
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
      detail: "存在已尝试但当前未通过验证的学习命题。",
      className: "needs_reteach",
      icon: RotateCcw,
    };
  }
  if (counts.partial) {
    return {
      label: `${counts.partial} 条部分理解`,
      detail: "存在部分通过的理解验证证据的学习命题。",
      className: "pending_semantic_review",
      icon: ShieldQuestion,
    };
  }
  if (counts.proposed) {
    return {
      label: `${counts.proposed} 条待验证`,
      detail: "存在已有源码依据但尚无理解验证证据的学习命题。",
      className: "pending_validation",
      icon: CircleHelp,
    };
  }
  if (counts.confirmed !== resume.claims.length) {
    return { label: "状态未知", detail: "部分学习命题的理解验证状态暂无法确认。",
      className: "pending_validation", icon: CircleHelp };
  }
  return {
    label: `${counts.confirmed} 条已验证`,
    detail: "当前展示的学习命题均有 已保存且已通过的理解验证证据。",
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
  const durableContext = resume?.source === "durable";
  const [open, setOpen] = useState(() => Boolean(fireflyLesson?.state.active && !durableContext));
  const contract = taskContractFromRoute(lastChat?.route);
  const durableActive = resume?.source === "durable" && resume.status === "active";
  useEffect(() => {
    if (durableContext) setOpen(false);
  }, [durableContext]);

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
          <span className="learning-strip-summary">正在读取学习恢复状态…</span>
          <span className="learning-strip-gap">未确认旧版兼容状态前不读取旧学习状态</span>
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
            <span>已保存的学习状态暂不可用</span>
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
      : resume.goal.objective || resume.topic.title || "当前已保存的学习目标";
    const next = noActiveGoal
      ? "学习状态已保存，不回退旧学习状态"
      : resume.unresolved[0]?.text
        ? `待验证假设：${resume.unresolved[0].text}`
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
              ? "已保存 · 没有进行中的学习目标"
              : `学习命题 ${resume.claims.length}/${resume.claim_count}`}
          </span>
          <span
            className={`learning-strip-status-item learning-strip-next${resume.unresolved.length ? " has-gap" : ""}`}
          >
            {resume.unresolved.length ? <AlertTriangle size={12} /> : null}
            <span>{next}</span>
          </span>
          <span
            className={`learning-verification-badge ${noActiveGoal ? "pending_validation" : summary.className}`}
            title={noActiveGoal ? "已保存的学习状态 已存在；没有进行中的学习目标。" : summary.detail}
          >
            {noActiveGoal ? <CircleHelp size={12} /> : <SummaryIcon size={12} />}
            {noActiveGoal ? "没有进行中的学习目标" : summary.label}
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
          {legacy.phase ? phaseLabel(legacy.phase) : "旧版兼容"}
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
