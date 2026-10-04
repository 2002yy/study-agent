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
import { humanizeUiError, uiReasonLabel } from "../../utils/uiLabels";

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
    detail: "最近一次已保存的理解验证证据已通过校验。",
    icon: CheckCircle2,
    className: "verified",
  },
  partial: {
    label: "部分理解",
    detail: "已有验证证据，但当前只支持部分通过。",
    icon: ShieldQuestion,
    className: "pending_semantic_review",
  },
  attempted: {
    label: "已尝试，尚未通过",
    detail: "已有验证尝试，但当前不能视为已确认。",
    icon: RotateCcw,
    className: "needs_reteach",
  },
  proposed: {
    label: "待验证",
    detail: "学习命题的来源证据已保存，尚无理解验证证据。",
    icon: CircleHelp,
    className: "pending_validation",
  },
} as const;

function validationMethodLabel(method?: string): string {
  if (method === "explain") return "解释验证";
  if (method === "apply") return "应用验证";
  if (method === "practice") return "练习验证";
  return method ? "其他验证方式" : "尚无验证";
}

function freshnessNote(claim: LearningResumeClaim): string {
  const freshness = claim.freshness;
  const reason = freshness?.reason || freshness?.primary?.reason;
  if (reason) return uiReasonLabel(reason);
  return "学习命题依据的主要源码已发生实质变更，尚未对最新源码重新验证。";
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
  const meta = Object.prototype.hasOwnProperty.call(UNDERSTANDING_META, claim.understanding_status)
    ? UNDERSTANDING_META[claim.understanding_status] : {
    label: "状态未知", detail: "理解验证状态暂无法确认。", icon: CircleHelp, className: "pending_validation",
  };
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
        humanizeUiError(error, "重新验证失败，请稍后重试。"),
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
       已保存的学习命题
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
          评估失败，请稍后重试。
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
          <p>当前没有进行中的已保存的学习目标。</p>
          <small>
            这个会话的学习状态已保存，因此不会读取旧学习状态或已确认点来恢复目标。
          </small>
        </section>
      </aside>
    );
  }

  const objective = resume.goal.objective || resume.topic.title || "当前已保存的学习目标";
  const primaryNextStep = resume.next_step.text?.trim() || "";

  return (
    <aside className="learning-panel">
      <header className="learning-header">
        <BookOpen size={16} /> 学习伴侣
      </header>

      <section className="learning-card objective-card">
        <div className="card-label">
          <Target size={13} /> 当前学习目标
        </div>
        <p>{objective}</p>
        {resume.topic.title && resume.topic.title !== objective ? (
          <small>主题：{resume.topic.title}</small>
        ) : null}
      </section>

      <section className="learning-card durable-claims-card">
        <div className="card-label">
          <CheckCircle2 size={13} />已保存的学习命题
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
              当前展示最近 {resume.claims.length} 条；该学习目标共 {resume.claim_count} 条学习命题。理解状态来自已保存的理解验证证据，不换算为掌握百分比。
            </p>
          </>
        ) : (
          <p className="muted">当前学习目标尚未形成有来源依据的学习命题。</p>
        )}
      </section>

      <section className={`learning-card gap-card${resume.unresolved.length ? " has-gap" : ""}`}>
        <div className="card-label">
          <AlertTriangle size={13} /> 未解决待验证假设
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
          <p className="muted">当前没有记录未解决待验证假设。</p>
        )}
      </section>

      <section className="learning-card durable-next-step-card">
        <div className="card-label">主要下一步</div>
        {primaryNextStep ? (
          <p>{primaryNextStep}</p>
        ) : (
          <p className="muted">当前没有进行中的主要下一步。</p>
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
        <p>这个会话尚未保存学习目标，当前显示旧版兼容状态。</p>
        <small>以下内容只用于继续旧会话，不会升级为正式学习命题或已确认掌握。</small>
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
          <History size={13} /> 旧版已确认点
        </div>
        {legacyPoints.length ? (
          <ul className="legacy-point-list">
            {legacyPoints.map((point, index) => (
              <li key={`${point}-${index}`}>{point}</li>
            ))}
          </ul>
        ) : (
          <p className="muted">没有旧已确认点。</p>
        )}
        <small>这些条目不是学习命题，也不作为已确认掌握呈现。</small>
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
          {resumeError ? `暂时无法读取学习恢复状态：${humanizeUiError(resumeError, "学习恢复状态读取失败，请稍后重试。")}` : "正在读取学习恢复状态…"}
        </p>
        <small>未得到后端明确的旧版兼容状态前，不使用旧学习状态作为恢复真相。</small>
      </section>
    </aside>
  );
}
