import {
  AlertTriangle,
  BookOpen,
  CheckCircle2,
  CircleHelp,
  RotateCcw,
  ShieldQuestion,
  Target,
} from "lucide-react";
import { latestMemorySection } from "../single-chat/ChatPanel";
import { moveLabel, phaseLabel, protocolLabel } from "../pedagogy/pedagogyLabels";
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

function supportLabel(hintLevel: number): string {
  const normalized = Number.isFinite(hintLevel)
    ? Math.max(0, Math.min(5, Math.trunc(hintLevel)))
    : 0;
  return normalized === 0 ? "未使用提示" : `已使用第 ${normalized} 级提示`;
}

export function LearningPanel({
  lastChat,
  visitedPhases,
  memoryStatus,
}: {
  lastChat: ChatResponse | null;
  visitedPhases: string[];
  memoryStatus: MemoryStatusResponse | null;
}) {
  const learning = projectTrustworthyLearningStatus(
    lastChat?.route?.learning_state
  );
  const state = learning.state;
  const pedagogy = lastChat?.pedagogy;
  const confirmed = state?.confirmed_points ?? [];
  const focus =
    memoryStatus?.latest_section ||
    latestMemorySection(
      memoryStatus,
      "current_focus.md",
      "尚无当前学习重点。"
    );
  const VerificationIcon = VERIFICATION_ICON[learning.verification.status];

  return (
    <aside className="learning-panel">
      <header className="learning-header">
        <BookOpen size={16} /> 学习伴侣
      </header>

      <section className="learning-card objective-card">
        <div className="card-label">
          <Target size={13} /> 学习目标
        </div>
        <p>{learning.objective || "发一条学习请求以建立目标"}</p>
      </section>

      <section className="learning-card phase-card">
        <div className="card-label">阶段轨迹</div>
        {state ? (
          <div className="phase-indicator">
            <span className="phase-current">
              {protocolLabel(state.protocol)} · {learning.phase ? phaseLabel(learning.phase) : "未开始"}
            </span>
            {visitedPhases.length ? (
              <ol className="phase-trail">
                {visitedPhases.map((phase) => (
                  <li
                    key={phase}
                    className={phase === learning.phase ? "is-current" : ""}
                  >
                    {phaseLabel(phase)}
                  </li>
                ))}
              </ol>
            ) : null}
          </div>
        ) : (
          <p className="muted">尚无学习状态</p>
        )}
      </section>

      <section className={`learning-card verification-card ${learning.verification.status}`}>
        <div className="card-label">
          <VerificationIcon size={13} /> 最近评估
        </div>
        <div className="verification-summary-row">
          <strong>{learning.verification.label}</strong>
          {learning.verification.confidence !== null ? (
            <span>评估置信度 {Math.round(learning.verification.confidence * 100)}%</span>
          ) : null}
        </div>
        <p>{learning.verification.detail}</p>
        <small>此状态来自已提交的 PedagogyEvalRun，不代表启发式掌握百分比。</small>
      </section>

      <section className={`learning-card gap-card${learning.unresolvedGap ? " has-gap" : ""}`}>
        <div className="card-label">
          <AlertTriangle size={13} /> 缺口 / 下一步
        </div>
        {learning.unresolvedGap ? (
          <p>当前缺口：{learning.unresolvedGap}</p>
        ) : learning.nextAction ? (
          <p>下一步：{learning.nextAction}</p>
        ) : (
          <p className="muted">当前没有记录未解决缺口或下一步。</p>
        )}
      </section>

      <section className="learning-card learning-evidence-card">
        <div className="card-label">已记录的学习证据</div>
        <dl className="learning-evidence-grid">
          <div>
            <dt>已确认知识点</dt>
            <dd>{confirmed.length}</dd>
          </div>
          <div>
            <dt>当前缺口</dt>
            <dd>{learning.unresolvedGap ? "待解决" : "暂无"}</dd>
          </div>
          <div>
            <dt>学习轮次</dt>
            <dd>{state?.turn_count ?? 0}</dd>
          </div>
          <div>
            <dt>提示情况</dt>
            <dd>{supportLabel(state?.hint_level ?? 0)}</dd>
          </div>
        </dl>
        <p className="learning-evidence-note">
          数量只表示已持久化证据，不换算为掌握度，也不使用 planned / attempted 状态冒充已完成。
        </p>
      </section>

      <section className="learning-card confirmed-card">
        <div className="card-label">
          <CheckCircle2 size={13} /> 已确认点
        </div>
        {confirmed.length ? (
          <ul className="confirmed-list">
            {confirmed.map((point, index) => (
              <li key={`${point}-${index}`}>{point}</li>
            ))}
          </ul>
        ) : (
          <p className="muted">尚未确认知识点</p>
        )}
      </section>

      {pedagogy ? (
        <section className="learning-card move-card">
          <div className="card-label">本轮动作</div>
          <span className="move-badge">
            {protocolLabel(pedagogy.mode)} · {moveLabel(pedagogy.move)}
          </span>
        </section>
      ) : null}

      <details className="learning-card memory-snapshot">
        <summary>记忆快照</summary>
        <p className="muted">{focus}</p>
      </details>
    </aside>
  );
}
