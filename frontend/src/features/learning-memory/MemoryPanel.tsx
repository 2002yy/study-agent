import { AlertTriangle, CheckCircle2, Plus, ShieldCheck, Trash2 } from "lucide-react";
import { FormEvent, useMemo, useState } from "react";
import { commitMemoryUpdates, previewMemoryUpdates } from "../../api";
import { StatusDot } from "../../components/StatusDot";
import type { MemoryCommitResponse, MemoryPreviewResponse, MemoryStatusResponse, MemoryUpdate } from "../../types";
import { basename } from "../../utils/format";

export type MemoryDraft = {
  id?: string;
  target: string;
  content: string;
  replaceCurrentFocus: boolean;
  learnerPending: boolean;
  enabled?: boolean;
};

type MemoryPanelProps = {
  memoryStatus: MemoryStatusResponse | null;
  onMemoryChanged?: () => Promise<void> | void;
};

const TARGET_OPTIONS = [
  { value: "current_focus", label: "current_focus.md", hint: "当前优先任务和边界" },
  { value: "progress", label: "progress.md", hint: "学习进展和阶段记录" },
  { value: "summary", label: "summary.md", hint: "长期摘要和关键结论" },
  { value: "learner_profile", label: "learner_profile.md", hint: "稳定偏好和学习画像" },
  { value: "project_context", label: "project_context.md", hint: "项目背景和长期约束" }
] as const;

const createDraft = (index: number): MemoryDraft => ({
  id: `draft-${Date.now()}-${index}`,
  target: index === 0 ? "progress" : "summary",
  content: "",
  replaceCurrentFocus: false,
  learnerPending: false,
  enabled: true
});

export function buildMemoryUpdatePayload(draft: MemoryDraft): MemoryUpdate | null {
  if (draft.enabled === false) {
    return null;
  }
  const content = draft.content.trim();
  if (!content) {
    return null;
  }
  return {
    target: draft.target,
    content,
    append: draft.target === "current_focus" ? !draft.replaceCurrentFocus : true,
    learner_pending: draft.learnerPending
  };
}

export function buildMemoryUpdatePayloads(drafts: MemoryDraft[]): MemoryUpdate[] {
  return drafts.flatMap((draft) => {
    const payload = buildMemoryUpdatePayload(draft);
    return payload ? [payload] : [];
  });
}

function previewFile(memoryStatus: MemoryStatusResponse | null, name: string) {
  return memoryStatus?.files.find((file) => file.name === name);
}

export function MemoryPanel({ memoryStatus, onMemoryChanged }: MemoryPanelProps) {
  const [drafts, setDrafts] = useState<MemoryDraft[]>([createDraft(0)]);
  const [preview, setPreview] = useState<MemoryPreviewResponse | null>(null);
  const [commitResult, setCommitResult] = useState<MemoryCommitResponse | null>(null);
  const [isPreviewing, setIsPreviewing] = useState(false);
  const [isCommitting, setIsCommitting] = useState(false);
  const [error, setError] = useState("");

  const focus = previewFile(memoryStatus, "current_focus.md");
  const progress = previewFile(memoryStatus, "progress.md");
  const summary = previewFile(memoryStatus, "summary.md");
  const updatePayloads = useMemo(() => buildMemoryUpdatePayloads(drafts), [drafts]);
  const activeDraftCount = drafts.filter((draft) => draft.enabled !== false && draft.content.trim()).length;

  const updateDraft = <K extends keyof MemoryDraft>(id: string | undefined, key: K, value: MemoryDraft[K]) => {
    setDrafts((current) => current.map((draft) => (draft.id === id ? { ...draft, [key]: value } : draft)));
    setError("");
    setCommitResult(null);
    setPreview(null);
  };

  const addDraft = () => {
    setDrafts((current) => [...current, createDraft(current.length)]);
    setError("");
    setPreview(null);
  };

  const removeDraft = (id: string | undefined) => {
    setDrafts((current) => (current.length === 1 ? current : current.filter((draft) => draft.id !== id)));
    setError("");
    setPreview(null);
  };

  const handlePreview = async (event: FormEvent) => {
    event.preventDefault();
    if (!updatePayloads.length) {
      setError("请先填写至少一条启用的记忆候选。");
      return;
    }
    setIsPreviewing(true);
    setError("");
    setCommitResult(null);
    try {
      setPreview(await previewMemoryUpdates(updatePayloads));
    } catch (err) {
      setPreview(null);
      setError(err instanceof Error ? err.message : "记忆预览失败");
    } finally {
      setIsPreviewing(false);
    }
  };

  const handleCommit = async () => {
    if (!preview || !preview.writable || !updatePayloads.length) {
      setError("请先生成可写预览，再确认写入。");
      return;
    }
    setIsCommitting(true);
    setError("");
    try {
      const result = await commitMemoryUpdates(updatePayloads);
      setCommitResult(result);
      setPreview(null);
      setDrafts([createDraft(0)]);
      await onMemoryChanged?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "记忆提交失败");
    } finally {
      setIsCommitting(false);
    }
  };

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
          <form className="memory-workbench" onSubmit={handlePreview}>
            <div className="memory-workbench-heading">
              <strong>写入候选</strong>
              <span>{activeDraftCount} 条将进入预览</span>
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
                          onChange={(event) => updateDraft(draft.id, "enabled", event.target.checked)}
                          type="checkbox"
                        />
                        候选 {index + 1}
                      </label>
                      <button
                        aria-label="删除候选"
                        className="icon-button small"
                        disabled={drafts.length === 1}
                        onClick={() => removeDraft(draft.id)}
                        type="button"
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                    <label className="field-row">
                      <span>目标文件</span>
                      <select value={draft.target} onChange={(event) => updateDraft(draft.id, "target", event.target.value)}>
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
                          onChange={(event) => updateDraft(draft.id, "replaceCurrentFocus", event.target.checked)}
                          type="checkbox"
                        />
                        替换 current_focus，而不是追加
                      </label>
                    ) : null}
                    <label className="memory-check">
                      <input
                        checked={draft.learnerPending}
                        onChange={(event) => updateDraft(draft.id, "learnerPending", event.target.checked)}
                        type="checkbox"
                      />
                      标记为“待确认观察”
                    </label>
                    <textarea
                      onChange={(event) => updateDraft(draft.id, "content", event.target.value)}
                      placeholder="写入一条课后更新、当前关注点或待确认观察..."
                      rows={4}
                      value={draft.content}
                    />
                  </article>
                );
              })}
            </div>
            <button className="ghost-action compact" onClick={addDraft} type="button">
              <Plus size={14} />
              添加候选
            </button>
            <div className="memory-actions">
              <button disabled={isPreviewing || !updatePayloads.length} type="submit">
                {isPreviewing ? "预览中..." : "生成预览"}
              </button>
              <button
                className="secondary"
                disabled={isCommitting || !preview || !preview.writable || !updatePayloads.length}
                onClick={handleCommit}
                type="button"
              >
                {isCommitting ? "提交中..." : "确认写入选中候选"}
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
