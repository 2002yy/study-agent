import { Loader2, Paperclip, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  deleteSessionAttachment,
  listSessionAttachments,
  uploadSessionAttachment,
  type SessionAttachmentInfo,
} from "../../api";
import { ACCEPTED_EXTENSIONS, MAX_FILE_BYTES, attachmentStatusLabel, formatBytes } from "../rag/attachmentRules";

/**
 * Unified multimodal input: the chat composer owns attaching files to the
 * current session instead of sending the learner to a separate panel.
 *
 * Attachments reuse the existing session-attachment API (`sessions/{id}/
 * attachments`); nothing about parsing, indexing or promotion changes here.
 */
export function ComposerAttachments({
  sessionId,
  onEnsureSession,
  selectedIds = [],
  onSelectionChange,
}: {
  sessionId?: string;
  /** Create the session on demand so a first multimodal question needs no empty send. */
  onEnsureSession?: () => Promise<string | undefined>;
  /** Ids selected for *this* message (distinct from attachments the session keeps). */
  selectedIds?: string[];
  onSelectionChange?: (ids: string[]) => void;
}) {
  const [attachments, setAttachments] = useState<SessionAttachmentInfo[]>([]);
  const [maxFiles, setMaxFiles] = useState(0);
  const [resolvedSession, setResolvedSession] = useState(sessionId ?? "");
  const [isUploading, setIsUploading] = useState(false);
  const [busyId, setBusyId] = useState("");
  const [error, setError] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setResolvedSession(sessionId ?? "");
  }, [sessionId]);

  const activeSession = resolvedSession || sessionId || "";

  const refresh = useCallback(async () => {
    if (!activeSession) {
      setAttachments([]);
      setMaxFiles(0);
      return;
    }
    try {
      const listing = await listSessionAttachments(activeSession);
      setAttachments(listing.attachments);
      setMaxFiles(listing.max_files_per_thread);
      setError("");
    } catch {
      // The sources panel surfaces detailed load errors; the composer stays quiet.
    }
  }, [activeSession]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const overLimit = maxFiles > 0 && attachments.length >= maxFiles;
  const canAttach = Boolean(activeSession) || Boolean(onEnsureSession);
  const disabled = !canAttach || isUploading || overLimit;

  const handleFiles = async (files: FileList | null) => {
    if (!files?.length) return;
    let session = activeSession;
    if (!session && onEnsureSession) {
      session = (await onEnsureSession()) ?? "";
      if (session) setResolvedSession(session);
    }
    if (!session) {
      setError("无法创建会话，附件未上传");
      return;
    }
    setIsUploading(true);
    setError("");
    try {
      const uploaded: string[] = [];
      for (const file of Array.from(files)) {
        if (file.size > MAX_FILE_BYTES) {
          setError(`${file.name} 超过 ${formatBytes(MAX_FILE_BYTES)} 上限`);
          continue;
        }
        const created = await uploadSessionAttachment(session, file);
        uploaded.push(created.id);
      }
      await refresh();
      // A freshly uploaded file is part of this message by default.
      if (uploaded.length && onSelectionChange) {
        onSelectionChange(Array.from(new Set([...selectedIds, ...uploaded])));
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "附件上传失败");
    } finally {
      setIsUploading(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  const toggleSelection = (attachmentId: string) => {
    if (!onSelectionChange) return;
    onSelectionChange(
      selectedIds.includes(attachmentId)
        ? selectedIds.filter(item => item !== attachmentId)
        : [...selectedIds, attachmentId],
    );
  };

  const handleRemove = async (attachmentId: string) => {
    setBusyId(attachmentId);
    try {
      await deleteSessionAttachment(attachmentId);
      // A deleted attachment must not remain in this message's selection.
      if (onSelectionChange && selectedIds.includes(attachmentId)) {
        onSelectionChange(selectedIds.filter(id => id !== attachmentId));
      }
      await refresh();
    } catch {
      setError("附件删除失败");
    } finally {
      setBusyId("");
    }
  };

  return (
    <div className="composer-attachments" aria-label="本会话附件">
      <input
        accept={ACCEPTED_EXTENSIONS.join(",")}
        hidden
        multiple
        onChange={(event) => void handleFiles(event.target.files)}
        ref={inputRef}
        type="file"
      />
      <button
        aria-label="添加附件"
        className="composer-attach-button"
        disabled={disabled}
        onClick={() => inputRef.current?.click()}
        title={!canAttach ? "开始会话后可添加附件" : overLimit ? "附件数已达上限" : "添加附件"}
        type="button"
      >
        {isUploading ? <Loader2 className="spin" size={16} /> : <Paperclip size={16} />}
        <span className="visually-hidden">添加附件</span>
      </button>
      {attachments.length ? (
        <ul className="composer-attachment-chips">
          {attachments.map((attachment) => {
            const selected = selectedIds.includes(attachment.id);
            return (
              <li key={attachment.id} className={selected ? "is-selected" : undefined}>
                <button
                  aria-label={`${selected ? "取消选择" : "选择"}附件 ${attachment.filename}`}
                  aria-pressed={selected}
                  className="composer-attachment-pick"
                  disabled={attachment.status !== "ready" || !onSelectionChange}
                  onClick={() => toggleSelection(attachment.id)}
                  title={attachment.status !== "ready" ? "附件尚未就绪" : selected ? "取消本次选择" : "加入本条消息"}
                  type="button"
                >
                  <span className="composer-attachment-name">{attachment.filename}</span>
                  <span className={`attachment-status attachment-status-${attachment.status}`}>
                    {attachmentStatusLabel(attachment.status)}
                  </span>
                </button>
                <button
                  aria-label={`移除附件 ${attachment.filename}`}
                  disabled={busyId === attachment.id}
                  onClick={() => void handleRemove(attachment.id)}
                  type="button"
                >
                  <X size={12} />
                </button>
              </li>
            );
          })}
        </ul>
      ) : null}
      {selectedIds.length ? (
        <span className="composer-attachment-count visually-hidden" role="status">本次选中 {selectedIds.length} 个</span>
      ) : null}
      {error ? <span className="composer-attachment-error" role="alert">{error}</span> : null}
    </div>
  );
}
