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
export function ComposerAttachments({ sessionId }: { sessionId?: string }) {
  const [attachments, setAttachments] = useState<SessionAttachmentInfo[]>([]);
  const [maxFiles, setMaxFiles] = useState(0);
  const [isUploading, setIsUploading] = useState(false);
  const [busyId, setBusyId] = useState("");
  const [error, setError] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    if (!sessionId) {
      setAttachments([]);
      setMaxFiles(0);
      return;
    }
    try {
      const listing = await listSessionAttachments(sessionId);
      setAttachments(listing.attachments);
      setMaxFiles(listing.max_files_per_thread);
      setError("");
    } catch {
      // The sources panel surfaces detailed load errors; the composer stays quiet.
    }
  }, [sessionId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const overLimit = maxFiles > 0 && attachments.length >= maxFiles;
  const disabled = !sessionId || isUploading || overLimit;

  const handleFiles = async (files: FileList | null) => {
    if (!sessionId || !files?.length) return;
    setIsUploading(true);
    setError("");
    try {
      for (const file of Array.from(files)) {
        if (file.size > MAX_FILE_BYTES) {
          setError(`${file.name} 超过 ${formatBytes(MAX_FILE_BYTES)} 上限`);
          continue;
        }
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

  const handleRemove = async (attachmentId: string) => {
    setBusyId(attachmentId);
    try {
      await deleteSessionAttachment(attachmentId);
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
        title={!sessionId ? "开始会话后可添加附件" : overLimit ? "附件数已达上限" : "添加附件"}
        type="button"
      >
        {isUploading ? <Loader2 className="spin" size={16} /> : <Paperclip size={16} />}
        <span className="visually-hidden">添加附件</span>
      </button>
      {attachments.length ? (
        <ul className="composer-attachment-chips">
          {attachments.map((attachment) => (
            <li key={attachment.id}>
              <span className="composer-attachment-name">{attachment.filename}</span>
              <span className={`attachment-status attachment-status-${attachment.status}`}>
                {attachmentStatusLabel(attachment.status)}
              </span>
              <button
                aria-label={`移除附件 ${attachment.filename}`}
                disabled={busyId === attachment.id}
                onClick={() => void handleRemove(attachment.id)}
                type="button"
              >
                <X size={12} />
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      {error ? <span className="composer-attachment-error" role="alert">{error}</span> : null}
    </div>
  );
}
