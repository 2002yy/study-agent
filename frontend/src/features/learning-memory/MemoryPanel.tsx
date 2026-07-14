import { AlertTriangle, CheckCircle2, Loader2, Plus, RotateCcw, ShieldCheck, Trash2, XCircle } from "lucide-react";
import { StatusDot } from "../../components/StatusDot";
import type { MemoryStatusResponse } from "../../types";
import { basename } from "../../utils/format";
import type { LearningClosureStatus } from "./closureTypes";
import type { useMemoryController } from "./memoryController";
export {
  buildMemoryUpdatePayload,
  buildMemoryUpdatePayloads
} from "./memoryController";

type MemoryController = ReturnType<typeof useMemoryController>;

type MemoryPanelProps = {
  memoryStatus: MemoryStatusResponse | null;
  controller: MemoryController;
};

const TARGET_OPTIONS = [
  { value: "current_focus", label: "current_focus.md", hint: "当前优先任务和边界" },
  { value: "progress", label: "progress.md", hint: "学习进展和阶段记录" },
  { value: "summary", label: "summary.md", hint: "长期摘要和关键结论" },
  { value: "learner_profile", label: "learner_profile.md", hint: "稳定偏好和学习画像" },
  { value: "project_context", label: "project_context.md", hint: "项目背景和长期约束" },
  { value: "revision_notes", label: "revision_notes.md", hint: "后续需要补强的内容" },
  { value: "session_archive", label: "session_archive.md", hint: "本次学习归档" }
] as const;

const CLOSURE_STATUS: Record<LearningClosureStatus, { label: string; tone: "good" | "warn" | "bad" | "neutral" }> = {
  created: { label: "已创建", tone: "neutral" },
  collecting: { label: "收集已提交学习状态", tone: "warn" },
  generating: { label: "生成整理候选", tone: "warn" },
  preview_ready: { label: "候选待确认", tone: "good" },
  committing: { label: "写入长期记忆", tone: "warn" },
  completed: { label: "本次整理已写入", tone: "good" },
  failed: { label: "整理失败", tone: "bad" },
  cancelled: { label: "整理已取消", tone: "neutral" },
};

function previewFile(memoryStatus: MemoryStatusResponse | null, name: string) {
  return memoryStatus?.files.find((file) => file.name === name);
}

export function MemoryPanel({ memoryStatus, controller }: MemoryPanelProps) {
  const {
    drafts,
    preview,
    commitResult,
    closureRun,
    isClosurePreview,
    isPreviewing,
    isCommitting,
    error,
    canPreview,
    updateDraft,
    addDraft,
    removeDraft,
    previewUpdates,
    commitRun,
    retryClosure,
    cancelClosure,
  } = controller;
  const focus = previewFile(memoryStatus, "current_focus.md");
  const progress = previewFile(memoryStatus, "progress.md");
  const summary = previewFile(memoryStatus, "summary.md");
  const activeDraftCount = drafts.filter((draft) => draft.enabled !== false && draft.content.trim()).length;
  const closureStatus = closureRun ? CLOSURE_STATUS[closureRun.status] : null;
  const closureBusy = closureRun?.status === "collecting" || closureRun?.status === "generating" || closureRun?.status === "committing";
  const closureRetryable = closureRun?.status === "failed" || closureRun?.status === "cancelled";
  const closureCancellable = Boolean(
    closureRun && ["created", "collecting", "generating", "preview_ready", "failed"].includes(closureRun.status)
  );

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
          {closureRun && closureStatus ? (
            <div className={`memory-note closure-status ${closureRun.status}`}>
              {closureBusy ? <Loader2 className="spin" size={16} /> : <StatusDot tone={closureStatus.tone} />}
              <div>
                <strong>{closureStatus.label}</strong>
                <span>
                  {closureRun.closure_eligibility === "project_summary" ? "项目收束" : "学习整理"}
                  {closureRun.reason ? ` · ${closureRun.reason}` : ""}
                </span>
              </div>
              <div className="closure-actions">
                {closureRetryable ? (
                  <button className="ghost-action compact" disabled={isPreviewing} onClick={() => void retryClosure()} type="button">
                    <RotateCcw size={14} />
                    重试
                  </button>
                ) : null}
                {closureCancellable ? (
                  <button className="ghost-action compact" disabled={isPreviewing || isCommitting} onClick={() => void cancelClosure()} type="button">
                    <XCircle size={14} />
                    取消整理
                  </button>
                ) : null}
              </div>
            </div>
          ) : null}
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
          <form className="memory-workbench" onSubmit={(event) => { event.preventDefault(); void previewUpdates(); }}>
            <div className="memory-workbench-heading">
              <strong>{isClosurePreview ? "学习整理候选" : "写入候选"}</strong>
              <span>{isClosurePreview ? "来源已冻结，确认后写入" : `${activeDraftCount} 条将进入预览`}</span>
            </div>
            <div className="memory-draft-list">
              {drafts.map((draft, index) => {
                const selectedTarget = TARGET_OPTIONS.find((target) => target.value === draft.target);
                const canReplaceFocus = draft.target === "current_focus";
                return (
                  <article className={`memory-draft ${draft.enabled === false ? "disabled" : ""}`} key={draft.id}>
                    <div className="memory-draft-header">
                      <label className="memory-check">
                        <input
                          checked={draft.enabled !== false}
                          disabled={isClosurePreview}
                          onChange={(event) => updateDraft(draft.id, "enabled", event.target.checked)}
                          type="checkbox"
                        />
                        候选 {index + 1}
                      </label>
                      <button
                        aria-label="删除候选"
                        className="icon-button small"
                        disabled={isClosurePreview || drafts.length === 1}
                        onClick={() => removeDraft(draft.id)}
                        type="button"
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                    <label className="field-row">
                      <span>目标文件</span>
                      <select disabled={isClosurePreview} value={draft.target} onChange={(event) => updateDraft(draft.id, "target", event.target.value)}>
                        {TARGET_OPTIONS.map((target) => (
                          <option key={target.value} value={target.value}>
                            {target.label}
                          </option>
                        ))}
                      </select>
                    </label>
                    <small className="field-hint">{selectedTarget?.hint}</small>
                    {canReplaceFocus ? (
                      <div className="focus-diff">
                        <div>
                          <span>当前 current_focus</span>
                          <p>{focus?.preview || "暂无 current_focus 内容。"}</p>
                        </div>
                        <div>
                          <span>{draft.replaceCurrentFocus ? "将替换为" : "将追加"}</span>
                          <p>{draft.content.trim() || "尚未填写候选内容。"}</p>
                        </div>
                      </div>
                    ) : null}
                    {canReplaceFocus ? (
                      <label className="memory-check">
                        <input
                          checked={draft.replaceCurrentFocus}
                          disabled={isClosurePreview}
                          onChange={(event) => updateDraft(draft.id, "replaceCurrentFocus", event.target.checked)}
                          type="checkbox"
                        />
                        替换 current_focus，而不是追加
                      </label>
                    ) : null}
                    <label className="memory-check">
                      <input
                        checked={draft.learnerPending}
                        disabled={isClosurePreview}
                        onChange={(event) => updateDraft(draft.id, "learnerPending", event.target.checked)}
                        type="checkbox"
                      />
                      标记为“待确认观察”
                    </label>
                    <textarea
                      disabled={isClosurePreview}
                      onChange={(event) => updateDraft(draft.id, "content", event.target.value)}
                      placeholder="写入一条课后更新、当前关注点或待确认观察..."
                      rows={4}
                      value={draft.content}
                    />
                  </article>
                );
              })}
            </div>
            <button className="ghost-action compact" disabled={isClosurePreview} onClick={addDraft} type="button">
              <Plus size={14} />
              添加候选
            </button>
            <div className="memory-actions">
              <button disabled={isClosurePreview || isPreviewing || !canPreview} type="submit">
                {isPreviewing ? "预览中..." : "生成预览"}
              </button>
              <button
                className="secondary"
                disabled={isCommitting || !preview || !preview.writable || closureRun?.status === "completed"}
                onClick={() => void commitRun()}
                type="button"
              >
                {isCommitting ? "提交中..." : isClosurePreview ? "确认并完成本次整理" : "确认写入选中候选"}
              </button>
            </div>
          </form>
          {preview ? (
            <div className={`memory-preview ${preview.writable ? "" : "blocked"}`}>
              <div className="memory-preview-meta">
                <strong>{preview.writable ? "可写预览" : "仅预览，当前不可写"}</strong>
                <span>
                  mode={preview.memory_mode} · safe_mode={String(preview.safe_mode)}
                </span>
              </div>
              {preview.updates.map((item, index) => (
                <div className="memory-preview-item" key={`${item.target}-${item.path}-${index}`}>
                  <span>
                    {item.action} · {item.target} · {basename(item.path)}
                  </span>
                  <pre>{item.preview}</pre>
                </div>
              ))}
            </div>
          ) : null}
          {commitResult ? (
            <div className="memory-result">
              <CheckCircle2 size={16} />
              <span>
                已写入 {commitResult.results.map((result) => `${result.target}(${result.action})`).join(", ")}
              </span>
              {commitResult.errors?.length ? (
                <details style={{ marginTop: 8 }}>
                  <summary>部分失败 ({commitResult.errors.length})</summary>
                  <ul>
                    {commitResult.errors.map((err, idx) => (
                      <li key={idx}>
                        <strong>{err.target}</strong> ({err.action}): {err.error}
                      </li>
                    ))}
                  </ul>
                </details>
              ) : null}
            </div>
          ) : null}
          {error ? (
            <div className="memory-note warn">
              <AlertTriangle size={16} />
              <span>{error}</span>
            </div>
          ) : null}
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
