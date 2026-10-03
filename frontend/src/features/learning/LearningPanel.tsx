import {
  AlertTriangle,
  BookOpen,
  CheckCircle2,
  CircleHelp,
  History,
  RefreshCw,
  RotateCcw,
  ShieldQuestion,
  Target,
} from "lucide-react";
import { useState } from "react";

import type { ChatResponse, MemoryStatusResponse } from "../../types";
import { DurableEvidenceTrail } from "../evidence/DurableEvidenceTrail";
import { phaseLabel, protocolLabel } from "../pedagogy/pedagogyLabels";
import { latestMemorySection } from "../single-chat/ChatPanel";
import { FireflyDefaultLesson } from "./FireflyDefaultLesson";
import { useFireflyLessonController } from "./FireflyLessonContext";
import {
  revalidateClaim,
  type LearningResumeClaim,
  type LearningResumeResponse,
} from "./learningResumeApi";
import { projectTrustworthyLearningStatus } from "./trustworthyLearningStatus";

const UNDERSTANDING_META = {
  confirmed: {
    label: "已验证理解",
    detail: "最近一次 durable UnderstandingEvidence 为 pass。",
    icon: CheckCircle2,
    className: "verified",
  },
  partial: {
    label: "部分理解",
    detail: "已有验证证据，但当前只支持 partial。",
    icon: ShieldQuestion,
    className: "pending_semantic_review",
  },
  attempted: {
    label: "已尝试，尚未通过",
    detail: "已有验证尝试，但当前不能视为 confirmed。",
    icon: RotateCcw,
    className: "needs_reteach",
  },
  proposed: {
    label: "待验证",
    detail: "Claim 已有 durable source evidence，但尚无 UnderstandingEvidence。",
    icon: CircleHelp,
    className: "pending_validation",
  },
} as const;

function validationMethodLabel(method?: string): string {
  if (method === "explain") return "解释验证";
  if (method === "apply") return "应用验证";
  if (method === "practice") return "练习验证";
  return method || "尚无验证";
}

function freshnessNote(claim: LearningResumeClaim): string {
  const freshness = claim.freshness;
  const reason = freshness?.reason || freshness?.primary?.reason;
  if (reason) return reason;
  return "Claim 依据的 primary 源码已发生实质变更，尚未对最新源码重新验证。";
}

function ClaimCard({
  claim,
  sessionId,
  onRevalidated,
}: {
  claim: LearningResumeClaim;
  sessionId?: string;
  onRevalidated?: () => void;
}) {
  const meta = UNDERSTANDING_META[claim.understanding_status];
  const StatusIcon = meta.icon;
  const latest = claim.latest_validation;
  const [revalidating, setRevalidating] = useState(false);
  const [revalidateError, setRevalidateError] = useState("");

  const handleRevalidate = async () => {
    if (!sessionId || revalidating) return;
    setRevalidating(true);
    setRevalidateError("");
    try {
      await revalidateClaim(sessionId, claim.claim_id);
      onRevalidated?.();
    } catch (error) {
      setRevalidateError(
        error instanceof Error ? error.message : "重新验证失败",
      );
    } finally {
      setRevalidating(false);
    }
  };

  return (
    <li className="durable-claim-item">
      <div className="durable-claim-head">
        <strong>{claim.text}</strong>
        <span className={`learning-verification-badge ${meta.className}`}>
          <StatusIcon size={12} /> {meta.label}
        </span>
      </div>
      <p className="durable-claim-meta">
        {[claim.claim_kind, claim.scope].filter(Boolean).join(" · ") || "durable Claim"}
      </p>
      <p className="durable-validation-note">
        {latest?.method
          ? `${validationMethodLabel(latest.method)} · ${meta.detail}`
          : meta.detail}
      </p>
      {claim.freshness?.status === "stale_candidate" ? (
        <div className="durable-freshness-row">
          <span className="learning-verification-badge stale_source">
            <RefreshCw size={12} /> 源码已变动
          </span>
          <p className="durable-freshness-note">{freshnessNote(claim)}</p>
          {revalidating ? (
            <span className="durable-revalidation-status">重新验证中…</span>
          ) : (
            <button
              aria-label={`重新验证 ${claim.text}`}
              className="durable-revalidate-button"
              onClick={handleRevalidate}
              type="button"
            >
              <RefreshCw size={12} /> 重新验证
            </button>
          )}
          {revalidateError ? (
            <p className="durable-revalidation-error">{revalidateError}</p>
          ) : null}
        </div>
      ) : claim.freshness?.status === "unavailable" ? (
        <p className="durable-freshness-note muted">
          源码新鲜度暂不可用：
          {claim.freshness.unavailable_reason || "评估失败"}
        </p>
      ) : null}
      <DurableEvidenceTrail
        primary={claim.primary_evidence}
        supporting={claim.supporting_evidence}
      />
    </li>
  );
}

function DurablePanel({
  resume,
  sessionId,
  onRevalidated,
}: {
  resume: LearningResumeResponse;
  sessionId?: string;
  onRevalidated?: () => void;
}) {
  if (resume.status === "no_active_goal") {
    return (
      <aside className="learning-panel">
        <header className="learning-header">
          <BookOpen size={16} /> 学习伴侣
        </header>
        <section className="learning-card objective-card durable-no-active-goal">
          <div className="card-label">
            <Target size={13} /> 当前学习目标
          </div>
          <p>当前没有进行中的 durable Goal。</p>
          <small>
            这个会话已经拥有 durable learning context，因此不会读取旧 learning_state 或 confirmed_points 来恢复目标。
          </small>
        </section>
      </aside>
    );
  }

  const objective = resume.goal.objective || resume.topic.title || "当前 durable Goal";
  const primaryNextStep = resume.next_step.text?.trim() || "";

  return (
    <aside className="learning-panel">
      <header className="learning-header">
        <BookOpen size={16} /> 学习伴侣
      </header>

      <section className="learning-card objective-card">
        <div className="card-label">
          <Target size={13} /> 当前 Goal
        </div>
        <p>{objective}</p>
        {resume.topic.title && resume.topic.title !== objective ? (
          <small>Topic：{resume.topic.title}</small>
        ) : null}
      </section>

      <section className="learning-card durable-claims-card">
        <div className="card-label">
          <CheckCircle2 size={13} /> Durable Claims
        </div>
        {resume.claims.length ? (
          <>
            <ul className="durable-claim-list">
              {resume.claims.map((claim) => (
                <ClaimCard
                  key={claim.revision_id}
                  claim={claim}
                  sessionId={sessionId}
                  onRevalidated={onRevalidated}
                />
              ))}
            </ul>
            <p className="learning-evidence-note">
              当前展示最近 {resume.claims.length} 条；该 Goal 共 {resume.claim_count} 条 Claim。理解状态来自 durable UnderstandingEvidence，不换算为掌握百分比。
            </p>
          </>
        ) : (
          <p className="muted">当前 Goal 尚未形成 source-backed Claim。</p>
        )}
      </section>

      <section className={`learning-card gap-card${resume.unresolved.length ? " has-gap" : ""}`}>
        <div className="card-label">
          <AlertTriangle size={13} /> 未解决 Hypothesis
        </div>
        {resume.unresolved.length ? (
          <ul className="durable-hypothesis-list">
            {resume.unresolved.map((item, index) => (
              <li key={item.hypothesis_id || `${item.text}-${index}`}>
                <strong>待验证假设</strong>
                <span>{item.text}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">当前没有记录未解决 Hypothesis。</p>
        )}
      </section>

      <section className="learning-card durable-next-step-card">
        <div className="card-label">Primary NextStep</div>
        {primaryNextStep ? (
          <p>{primaryNextStep}</p>
        ) : (
          <p className="muted">当前没有 active Primary NextStep。</p>
        )}
      </section>
    </aside>
  );
}

function LegacyPanel({
  resume,
  lastChat,
  visitedPhases,
  memoryStatus,
}: {
  resume: LearningResumeResponse;
  lastChat: ChatResponse | null;
  visitedPhases: string[];
  memoryStatus: MemoryStatusResponse | null;
}) {
  const legacy = projectTrustworthyLearningStatus(lastChat?.route?.learning_state);
  const state = legacy.state;
  const objective = resume.goal.objective || legacy.objective || "旧会话未记录学习目标";
  const unresolved = resume.unresolved[0]?.text || legacy.unresolvedGap;
  const nextStep = resume.next_step.text || legacy.nextAction;
  const legacyPoints = resume.legacy_confirmed_points ?? [];
  const focus =
    memoryStatus?.latest_section ||
    latestMemorySection(memoryStatus, "current_focus.md", "尚无旧版学习重点。 ");

  return (
    <aside className="learning-panel legacy-learning-panel">
      <header className="learning-header">
        <History size={16} /> 旧会话兼容状态
      </header>

      <section className="learning-card legacy-compat-card">
        <div className="card-label">兼容边界</div>
        <p>这个 thread 尚未获得 durable Goal context，因此后端明确返回 legacy_fallback。</p>
        <small>以下内容只用于继续旧会话，不会升级为 formal Claim 或 confirmed mastery。</small>
      </section>

      <section className="learning-card objective-card">
        <div className="card-label">
          <Target size={13} /> 旧学习目标
        </div>
        <p>{objective}</p>
      </section>

      {state ? (
        <section className="learning-card phase-card">
          <div className="card-label">旧教学阶段</div>
          <div className="phase-indicator">
            <span className="phase-current">
              {protocolLabel(state.protocol)} · {legacy.phase ? phaseLabel(legacy.phase) : "未开始"}
            </span>
            {visitedPhases.length ? (
              <ol className="phase-trail">
                {visitedPhases.map((phase) => (
                  <li key={phase} className={phase === legacy.phase ? "is-current" : ""}>
                    {phaseLabel(phase)}
                  </li>
                ))}
              </ol>
            ) : null}
          </div>
        </section>
      ) : null}

      <section className={`learning-card gap-card${unresolved ? " has-gap" : ""}`}>
        <div className="card-label">
          <AlertTriangle size={13} /> 旧缺口 / 下一步
        </div>
        {unresolved ? (
          <p>旧记录缺口：{unresolved}</p>
        ) : nextStep ? (
          <p>旧记录下一步：{nextStep}</p>
        ) : (
          <p className="muted">旧会话没有记录缺口或下一步。</p>
        )}
      </section>

      <section className="learning-card legacy-points-card">
        <div className="card-label">
          <History size={13} /> legacy confirmed_points
        </div>
        {legacyPoints.length ? (
          <ul className="legacy-point-list">
            {legacyPoints.map((point, index) => (
              <li key={`${point}-${index}`}>{point}</li>
            ))}
          </ul>
        ) : (
          <p className="muted">没有旧 confirmed_points。</p>
        )}
        <small>这些条目不是 Claims，也不作为 verified mastery 呈现。</small>
      </section>

      <details className="learning-card memory-snapshot">
        <summary>旧记忆快照</summary>
        <p className="muted">{focus}</p>
      </details>
    </aside>
  );
}

export function LearningPanel({
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
  const durableActive = resume?.source === "durable" && resume.status === "active";
  if (fireflyLesson?.state.active && !durableActive) {
    return <FireflyDefaultLesson controller={fireflyLesson} />;
  }

  if (resume?.source === "durable") {
    return (
      <DurablePanel
        resume={resume}
        sessionId={sessionId}
        onRevalidated={onRevalidated}
      />
    );
  }
  if (resume?.source === "legacy_fallback") {
    return (
      <LegacyPanel
        resume={resume}
        lastChat={lastChat}
        visitedPhases={visitedPhases}
        memoryStatus={memoryStatus}
      />
    );
  }

  return (
    <aside className="learning-panel">
      <header className="learning-header">
        <BookOpen size={16} /> 学习伴侣
      </header>
      <section className="learning-card">
        <div className="card-label">学习恢复状态</div>
        <p className="muted">
          {resumeError ? `暂时无法读取 durable ResumeContext：${resumeError}` : "正在读取 durable ResumeContext…"}
        </p>
        <small>未得到后端明确的 legacy_fallback 前，不使用旧 learning_state 作为恢复真相。</small>
      </section>
    </aside>
  );
}
