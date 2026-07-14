import { AlertTriangle, BookOpen, CheckCircle2, Target } from "lucide-react";
import { latestMemorySection } from "../single-chat/ChatPanel";
import { moveLabel, phaseLabel, protocolLabel } from "../pedagogy/pedagogyLabels";
import type { ChatResponse, LearningState, MemoryStatusResponse } from "../../types";

function asLearningState(raw: unknown): LearningState | null {
  if (!raw || typeof raw !== "object") return null;
  const o = raw as Record<string, unknown>;
  return {
    protocol: String(o.protocol ?? ""),
    objective: String(o.objective ?? ""),
    phase: String(o.phase ?? ""),
    unresolved_gap: String(o.unresolved_gap ?? ""),
    confirmed_points: Array.isArray(o.confirmed_points) ? (o.confirmed_points as string[]) : [],
    hint_level: Number(o.hint_level ?? 0),
    turn_count: Number(o.turn_count ?? 0),
  };
}

function supportLabel(hintLevel: number): string {
  if (hintLevel <= 0) return "尚未使用提示";
  if (hintLevel === 1) return "使用了轻提示";
  if (hintLevel === 2) return "使用了分步提示";
  return "使用了直接讲解";
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
  const state = asLearningState(lastChat?.route?.learning_state);
  const pedagogy = lastChat?.pedagogy;
  const confirmed = state?.confirmed_points ?? [];
  const focus =
    memoryStatus?.latest_section ||
    latestMemorySection(memoryStatus, "current_focus.md", "尚无当前学习重点。");

  return (
    <aside className="learning-panel">
      <header className="learning-header">
        <BookOpen size={16} /> 学习伴侣
      </header>

      <section className="learning-card objective-card">
        <div className="card-label">
          <Target size={13} /> 学习目标
        </div>
        <p>{state?.objective || "发一条学习请求以建立目标"}</p>
      </section>

      <section className="learning-card phase-card">
        <div className="card-label">阶段轨迹</div>
        {state ? (
          <div className="phase-indicator">
            <span className="phase-current">
              {protocolLabel(state.protocol)} · {state.phase ? phaseLabel(state.phase) : "未开始"}
            </span>
            {visitedPhases.length ? (
              <ol className="phase-trail">
                {visitedPhases.map((p) => (
                  <li key={p} className={p === state.phase ? "is-current" : ""}>
                    {phaseLabel(p)}
                  </li>
                ))}
              </ol>
            ) : null}
          </div>
        ) : (
          <p className="muted">尚无学习状态</p>
        )}
      </section>

      <section className="learning-card learning-evidence-card">
        <div className="card-label">本轮学习证据</div>
        <dl className="learning-evidence-grid">
          <div>
            <dt>已确认知识点</dt>
            <dd>{confirmed.length}</dd>
          </div>
          <div>
            <dt>当前缺口</dt>
            <dd>{state?.unresolved_gap ? "待解决" : "暂无"}</dd>
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
        <p className="learning-evidence-note">这里只展示已记录的学习证据，不推算掌握百分比。</p>
      </section>

      <section className={`learning-card gap-card${state?.unresolved_gap ? " has-gap" : ""}`}>
        <div className="card-label">
          <AlertTriangle size={13} /> 当前缺口
        </div>
        <p>{state?.unresolved_gap || "无未解决缺口"}</p>
      </section>

      <section className="learning-card confirmed-card">
        <div className="card-label">
          <CheckCircle2 size={13} /> 已确认点
        </div>
        {confirmed.length ? (
          <ul className="confirmed-list">
            {confirmed.map((c, i) => (
              <li key={i}>{c}</li>
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
