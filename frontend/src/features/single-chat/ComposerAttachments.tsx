import { Loader2, Paperclip, X } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

import {
  deleteSessionAttachment,
  listSessionAttachments,
  uploadSessionAttachment,
  type SessionAttachmentInfo,
} from "../../api";
import {
  ACCEPTED_EXTENSIONS, MAX_FILE_BYTES, attachmentSelectionHint, attachmentStatusLabel,
  formatBytes, isAttachmentReadable,
} from "../rag/attachmentRules";

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
  const [listing, setListing] = useState<{session: string; generation: number; attachments: SessionAttachmentInfo[]; maxFiles: number}>({
    session: "", generation: 0, attachments: [], maxFiles: 0,
  });
  const [resolvedSession, setResolvedSession] = useState(sessionId ?? "");
  const [uploadingSessions, setUploadingSessions] = useState<Set<string>>(() => new Set());
  const [busyId, setBusyId] = useState("");
  const [errorState, setErrorState] = useState({session: sessionId ?? "", message: ""});
  const inputRef = useRef<HTMLInputElement>(null);
  // Async uploads/deletions must consult the latest parent-controlled selection.
  const selectedIdsRef = useRef(selectedIds);
  selectedIdsRef.current = selectedIds;

  useEffect(() => {
    setResolvedSession(sessionId ?? "");
  }, [sessionId]);

  // Explicit navigation wins over the session created by an earlier upload.
  const activeSession = sessionId || resolvedSession || "";
  const sessionRef = useRef({id: activeSession, generation: 0});
  useLayoutEffect(() => {
    if (sessionRef.current.id !== activeSession) {
      sessionRef.current = {id: activeSession, generation: sessionRef.current.generation + 1};
    }
  }, [activeSession]);
  const isCurrent = (session: string, generation: number) =>
    sessionRef.current.id === session && sessionRef.current.generation === generation;
  const listingIsCurrent = listing.session === activeSession && listing.generation === sessionRef.current.generation;
  const attachments = listingIsCurrent ? listing.attachments : [];
  const maxFiles = listingIsCurrent ? listing.maxFiles : 0;
  const isUploading = uploadingSessions.has(activeSession);
  const error = errorState.session === activeSession ? errorState.message : "";
  const setError = (message: string, session = activeSession) => setErrorState({session, message});

  const refresh = useCallback(async (session = activeSession) => {
    const generation = sessionRef.current.generation;
    if (!isCurrent(session, generation)) return;
    if (!session) {
      setListing({session: "", generation, attachments: [], maxFiles: 0});
      return;
    }
    try {
      const result = await listSessionAttachments(session);
      // A late response from another session (or an earlier visit to this
      // session) cannot replace the current list or prune its selection.
      if (!isCurrent(session, generation)) return;
      setListing({session, generation, attachments: result.attachments, maxFiles: result.max_files_per_thread});
      setErrorState({session, message: ""});
      // A previous selection can outlive a refresh or session navigation.
      // Never let a known-unreadable file reach the next chat request.
      const unreadable = new Set(result.attachments.filter(item => !isAttachmentReadable(item)).map(item => item.id));
      const current = selectedIdsRef.current;
      const next = current.filter(id => !unreadable.has(id));
      if (next.length !== current.length && onSelectionChange) onSelectionChange(next);
      return result.attachments;
    } catch {
      // The sources panel surfaces detailed load errors; the composer stays quiet.
    }
  }, [activeSession, onSelectionChange]);

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
      const originGeneration = sessionRef.current.generation;
      const ensured = (await onEnsureSession()) ?? "";
      // Creating the new session may update the parent before this promise
      // settles. That is safe only when it is the same session id.
      if (!isCurrent(activeSession, originGeneration) && sessionRef.current.id !== ensured) return;
      session = ensured;
      if (session && sessionRef.current.id !== session) {
        sessionRef.current = {id: session, generation: sessionRef.current.generation + 1};
        setResolvedSession(session);
      }
    }
    if (!session) {
      setError("无法创建会话，附件未上传");
      return;
    }
    const generation = sessionRef.current.generation;
    setUploadingSessions(current => new Set(current).add(session));
    setError("", session);
    try {
      const uploaded: string[] = [];
      const notReadable: SessionAttachmentInfo[] = [];
      const warnings: string[] = [];
      for (const file of Array.from(files)) {
        if (!isCurrent(session, generation)) return;
        if (file.size > MAX_FILE_BYTES) {
          warnings.push(`${file.name} 超过 ${formatBytes(MAX_FILE_BYTES)} 上限`);
          continue;
        }
        const created = await uploadSessionAttachment(session, file);
        if (!isCurrent(session, generation)) return;
        if (isAttachmentReadable(created)) uploaded.push(created.id);
        else notReadable.push(created);
      }
      const currentAttachments = await refresh(session);
      if (!isCurrent(session, generation)) return;
      // Only confirmed-readable uploads join this message automatically.
      const nowUnreadable = new Set([
        ...notReadable.map(item => item.id),
        ...(currentAttachments ?? []).filter(item => !isAttachmentReadable(item)).map(item => item.id),
      ]);
      const readyUploads = uploaded.filter(id => !nowUnreadable.has(id));
      if (readyUploads.length && onSelectionChange) {
        onSelectionChange(Array.from(new Set([
          ...selectedIdsRef.current.filter(id => !nowUnreadable.has(id)),
          ...readyUploads,
        ])));
      }
      if (notReadable.length) warnings.push(attachmentSelectionHint(notReadable[0]));
      if (warnings.length) setError(warnings.join("；"), session);
    } catch (cause) {
      if (isCurrent(session, generation)) setError(cause instanceof Error ? cause.message : "附件上传失败", session);
    } finally {
      setUploadingSessions(current => {
        const remaining = new Set(current);
        remaining.delete(session);
        return remaining;
      });
      if (isCurrent(session, generation) && inputRef.current) inputRef.current.value = "";
    }
  };

  const toggleSelection = (attachmentId: string) => {
    if (!onSelectionChange || !attachments.some(item => item.id === attachmentId && isAttachmentReadable(item))) return;
    onSelectionChange(
      selectedIds.includes(attachmentId)
        ? selectedIds.filter(item => item !== attachmentId)
        : [...selectedIds, attachmentId],
    );
  };

  const handleRemove = async (attachmentId: string) => {
    const session = activeSession;
    const generation = sessionRef.current.generation;
    setBusyId(attachmentId);
    try {
      await deleteSessionAttachment(attachmentId);
      if (!isCurrent(session, generation)) return;
      // A deleted attachment must not remain in this message's selection.
      const currentSelection = selectedIdsRef.current;
      if (onSelectionChange && currentSelection.includes(attachmentId)) {
        onSelectionChange(currentSelection.filter(id => id !== attachmentId));
      }
      await refresh();
    } catch {
      if (isCurrent(session, generation)) setError("附件删除失败", session);
    } finally {
      if (isCurrent(session, generation)) setBusyId("");
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
            const readable = isAttachmentReadable(attachment);
            return (
              <li key={attachment.id} className={selected ? "is-selected" : undefined}>
                <button
                  aria-label={`${selected ? "取消选择" : "选择"}附件 ${attachment.filename}`}
                  aria-describedby={!readable ? `attachment-hint-${attachment.id}` : undefined}
                  aria-pressed={selected}
                  className="composer-attachment-pick"
                  disabled={!readable || !onSelectionChange}
                  onClick={() => toggleSelection(attachment.id)}
                  title={readable && selected ? "取消本次选择" : attachmentSelectionHint(attachment)}
                  type="button"
                >
                  <span className="composer-attachment-name">{attachment.filename}</span>
                  <span className={`attachment-status attachment-status-${attachment.status === "ready" && !readable ? "unreadable" : attachment.status}`}>
                    {attachmentStatusLabel(attachment)}
                  </span>
                </button>
                {!readable ? <span className="visually-hidden" id={`attachment-hint-${attachment.id}`}>
                  {attachmentSelectionHint(attachment)}
                </span> : null}
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
