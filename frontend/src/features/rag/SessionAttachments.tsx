import { AlertTriangle, FilePlus2, Loader2, RefreshCw, Trash2, Upload } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useReadingWorkspace } from "../reading/ReadingContext";

import {
  deleteSessionAttachment,
  listSessionAttachments,
  promoteSessionAttachment,
  retrySessionAttachment,
  uploadSessionAttachment,
  type SessionAttachmentInfo,
  type SessionAttachmentListResponse,
} from "../../api";

const ACCEPTED_EXTENSIONS = [
  ".md",
  ".markdown",
  ".txt",
  ".pdf",
  ".docx",
  ".jpg",
  ".jpeg",
  ".png",
  ".gif",
  ".webp",
];

const MAX_FILE_BYTES = 20 * 1024 * 1024;

function formatBytes(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  if (bytes >= 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${bytes} B`;
}

function statusLabel(status: SessionAttachmentInfo["status"]): string {
  if (status === "parsing") return "解析中";
  if (status === "chunking") return "分块中";
  if (status === "indexing") return "索引中";
  if (status === "ready") return "已就绪";
  return "失败";
}

function stageLine(entry: SessionAttachmentInfo["stage_history"][number]): string {
  const parts = [entry.stage, entry.status];
  if (typeof entry.chunks === "number") parts.push(`${entry.chunks} 片段`);
  if (entry.vector_status) parts.push(`向量:${entry.vector_status}`);
  if (entry.detail) parts.push(entry.detail);
  if (entry.error) parts.push(entry.error);
  return parts.join(" · ");
}

export function SessionAttachments({ sessionId }: { sessionId?: string | null }) {
  const reading = useReadingWorkspace();
  const [listing, setListing] = useState<SessionAttachmentListResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [busyId, setBusyId] = useState("");
  const [error, setError] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    if (!sessionId) return;
    setIsLoading(true);
    try {
      setListing(await listSessionAttachments(sessionId));
      setError("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "附件列表加载失败");
    } finally {
      setIsLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  if (!sessionId) {
    return (
      <div className="empty-state">
        开始一个会话后，这里可以上传仅当前会话可见的临时附件。
      </div>
    );
  }

  const handleUpload = async (files: FileList | null) => {
    if (!files?.length || !sessionId) return;
    setIsUploading(true);
    setError("");
    try {
      for (const file of Array.from(files)) {
        await uploadSessionAttachment(sessionId, file);
      }
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "附件上传失败");
    } finally {
      setIsUploading(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  const handleRetry = async (attachmentId: string) => {
    setBusyId(attachmentId);
    try {
      await retrySessionAttachment(attachmentId);
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "重试失败");
    } finally {
      setBusyId("");
    }
  };

  const handlePromote = async (attachmentId: string) => {
    setBusyId(attachmentId);
    try {
      await promoteSessionAttachment(attachmentId);
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "转正失败");
    } finally {
      setBusyId("");
    }
  };

  const handleDelete = async (attachmentId: string) => {
    setBusyId(attachmentId);
    try {
      await deleteSessionAttachment(attachmentId);
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "删除失败");
    } finally {
      setBusyId("");
    }
  };

  const attachments = listing?.attachments ?? [];
  const overLimit = listing ? attachments.length >= listing.max_files_per_thread : false;

  return (
    <section aria-label="本会话临时附件" className="session-attachments">
      <div className="sources-library-summary">
        <strong>本会话临时附件 {attachments.length} 个</strong>
        <span>
          {listing
            ? `上限 ${listing.max_files_per_thread} 个 · 共 ${formatBytes(listing.total_bytes)}`
            : ""}
        </span>
      </div>
      <small className="field-hint">
        临时附件只在当前会话内参与回答，优先于长期资料；会话归档或删除后自动清理。
        图片默认只保存，需在设置里开启云端图片理解才会解析。
      </small>
      <div className="inline-actions">
        <input
          accept={ACCEPTED_EXTENSIONS.join(",")}
          hidden
          multiple
          onChange={(event) => void handleUpload(event.target.files)}
          ref={inputRef}
          type="file"
        />
        <button
          className="ghost-action compact"
          disabled={isUploading || overLimit}
          onClick={() => inputRef.current?.click()}
          type="button"
        >
          {isUploading ? <Loader2 className="spin" size={14} /> : <FilePlus2 size={14} />}
          {overLimit ? "附件数已达上限" : "添加临时附件"}
        </button>
        <button
          className="ghost-action compact"
          disabled={isLoading}
          onClick={() => void refresh()}
          type="button"
        >
          <RefreshCw size={14} />
          刷新
        </button>
      </div>
      {error ? (
        <div className="inline-error" role="alert">
          <AlertTriangle size={14} /> {error}
        </div>
      ) : null}
      {attachments.length ? (
        <div className="session-list">
          {attachments.map((attachment) => (
            <div className="session-row" key={attachment.id}>
              <strong>{attachment.filename}</strong>
              <span>
                {formatBytes(attachment.size_bytes)} ·{" "}
                <em className={`attachment-status attachment-status-${attachment.status}`}>
                  {statusLabel(attachment.status)}
                </em>
                {attachment.retry_count > 0 ? ` · 已重试 ${attachment.retry_count} 次` : ""}
                {attachment.promoted_rag_run_id ? " · 已转正" : ""}
              </span>
              <details>
                <summary>处理步骤</summary>
                <ul className="attachment-stage-log">
                  {attachment.stage_history.map((entry, index) => (
                    <li key={`${entry.stage}-${index}`}>{stageLine(entry)}</li>
                  ))}
                </ul>
              </details>
              <div className="inline-actions">
                {reading && attachment.status === "ready" && !/\.(png|jpe?g|gif|webp)$/i.test(attachment.filename) ? (
                  <button className="ghost-action compact" type="button"
                    onClick={() => reading.open({scope:"session",threadId:sessionId ?? undefined,attachmentId:attachment.id})}>
                    阅读正文
                  </button>
                ) : null}
                {attachment.status === "failed" ? (
                  <button
                    className="ghost-action compact"
                    disabled={busyId === attachment.id}
                    onClick={() => void handleRetry(attachment.id)}
                    type="button"
                  >
                    {busyId === attachment.id ? (
                      <Loader2 className="spin" size={14} />
                    ) : (
                      <RefreshCw size={14} />
                    )}
                    重试
                  </button>
                ) : null}
                {attachment.status === "ready" && !attachment.promoted_rag_run_id ? (
                  <button
                    className="ghost-action compact"
                    disabled={busyId === attachment.id}
                    onClick={() => void handlePromote(attachment.id)}
                    type="button"
                  >
                    <Upload size={14} />
                    转为长期资料
                  </button>
                ) : null}
                <button
                  className="ghost-action compact danger"
                  disabled={busyId === attachment.id}
                  onClick={() => void handleDelete(attachment.id)}
                  type="button"
                >
                  <Trash2 size={14} />
                  删除
                </button>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="empty-state">还没有临时附件。上传后只对当前会话的问题生效。</div>
      )}
    </section>
  );
}
