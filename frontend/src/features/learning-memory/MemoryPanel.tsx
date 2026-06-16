import { AlertTriangle, CheckCircle2, ShieldCheck } from "lucide-react";
import { FormEvent, useMemo, useState } from "react";
import { commitMemoryUpdates, previewMemoryUpdates } from "../../api";
import { StatusDot } from "../../components/StatusDot";
import type { MemoryCommitResponse, MemoryPreviewResponse, MemoryStatusResponse, MemoryUpdate } from "../../types";
import { basename } from "../../utils/format";

type MemoryDraft = {
  target: string;
  content: string;
  replaceCurrentFocus: boolean;
  learnerPending: boolean;
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

const INITIAL_DRAFT: MemoryDraft = {
  target: "progress",
  content: "",
  replaceCurrentFocus: false,
  learnerPending: false
};

export function buildMemoryUpdatePayload(draft: MemoryDraft): MemoryUpdate | null {
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

export function MemoryPanel({ memoryStatus, onMemoryChanged }: MemoryPanelProps) {
  const [draft, setDraft] = useState<MemoryDraft>(INITIAL_DRAFT);
  const [preview, setPreview] = useState<MemoryPreviewResponse | null>(null);
  const [commitResult, setCommitResult] = useState<MemoryCommitResponse | null>(null);
  const [isPreviewing, setIsPreviewing] = useState(false);
  const [isCommitting, setIsCommitting] = useState(false);
  const [error, setError] = useState("");

  const focus = memoryStatus?.files.find((file) => file.name === "current_focus.md");
  const progress = memoryStatus?.files.find((file) => file.name === "progress.md");
  const summary = memoryStatus?.files.find((file) => file.name === "summary.md");
  const selectedTarget = TARGET_OPTIONS.find((target) => target.value === draft.target);
  const updatePayload = useMemo(() => buildMemoryUpdatePayload(draft), [draft]);

  const setDraftValue = <K extends keyof MemoryDraft>(key: K, value: MemoryDraft[K]) => {
    setDraft((current) => ({ ...current, [key]: value }));
    setError("");
    setCommitResult(null);
    if (key !== "content") {
      setPreview(null);
    }
  };

  const handlePreview = async (event: FormEvent) => {
    event.preventDefault();
    if (!updatePayload) {
      setError("请先填写要写入的记忆内容。");
      return;
    }
    setIsPreviewing(true);
    setError("");
    setCommitResult(null);
    try {
      setPreview(await previewMemoryUpdates([updatePayload]));
    } catch (err) {
      setPreview(null);
      setError(err instanceof Error ? err.message : "记忆预览失败");
    } finally {
      setIsPreviewing(false);
    }
  };

  const handleCommit = async () => {
    if (!updatePayload) {
      setError("请先填写要写入的记忆内容。");
      return;
    }
    setIsCommitting(true);
    setError("");
    try {
      const result = await commitMemoryUpdates([updatePayload]);
      setCommitResult(result);
      setPreview(null);
      setDraft((current) => ({ ...current, content: "" }));
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
              <span>先预览，再确认提交</span>
            </div>
            <label className="field-row">
              <span>目标文件</span>
              <select value={draft.target} onChange={(event) => setDraftValue("target", event.target.value)}>
                {TARGET_OPTIONS.map((target) => (
                  <option key={target.value} value={target.value}>
                    {target.label}
                  </option>
                ))}
              </select>
            </label>
            <small className="field-hint">{selectedTarget?.hint}</small>
            {draft.target === "current_focus" ? (
              <label className="memory-check">
                <input
                  type="checkbox"
                  checked={draft.replaceCurrentFocus}
                  onChange={(event) => setDraftValue("replaceCurrentFocus", event.target.checked)}
                />
                替换 current_focus，而不是追加
              </label>
            ) : null}
            <label className="memory-check">
              <input
                type="checkbox"
                checked={draft.learnerPending}
                onChange={(event) => setDraftValue("learnerPending", event.target.checked)}
              />
              标记为“待确认观察”
            </label>
            <textarea
              rows={5}
              value={draft.content}
              placeholder="写入一条课后更新、当前关注点或待确认观察..."
              onChange={(event) => setDraftValue("content", event.target.value)}
            />
            <div className="memory-actions">
              <button type="submit" disabled={isPreviewing || !updatePayload}>
                {isPreviewing ? "预览中..." : "生成预览"}
              </button>
              <button
                className="secondary"
                type="button"
                disabled={isCommitting || !preview || !preview.writable || !updatePayload}
                onClick={handleCommit}
              >
                {isCommitting ? "提交中..." : "确认写入"}
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
              {preview.updates.map((item) => (
                <div className="memory-preview-item" key={`${item.target}-${item.path}`}>
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
