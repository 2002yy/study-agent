import type { SessionAttachmentInfo } from "../../api";

/** Shared rules for session attachments, so the composer and sources panel agree. */

export const ACCEPTED_EXTENSIONS = [
  ".md",
  ".markdown",
  ".txt",
  ".csv",
  ".pdf",
  ".docx",
  ".jpg",
  ".jpeg",
  ".png",
  ".gif",
  ".webp",
];

export const MAX_FILE_BYTES = 20 * 1024 * 1024;

function lastIndexingStage(attachment: SessionAttachmentInfo) {
  for (let i = attachment.stage_history.length - 1; i >= 0; i -= 1) {
    const entry = attachment.stage_history[i];
    if (entry.stage === "indexing") return entry;
  }
  return undefined;
}

export function formatBytes(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  if (bytes >= 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${bytes} B`;
}

/** Storage completion is not enough: the index must confirm readable content. */
export function isAttachmentReadable(attachment: SessionAttachmentInfo): boolean {
  if (attachment.status !== "ready") return false;
  const indexed = lastIndexingStage(attachment);
  return indexed?.status === "completed" && indexed.retrievable === true;
}

export function attachmentStatusLabel(attachment: SessionAttachmentInfo): string {
  if (attachment.status === "parsing") return "解析中";
  if (attachment.status === "chunking") return "分块中";
  if (attachment.status === "indexing") return "索引中";
  if (attachment.status === "ready") {
    if (isAttachmentReadable(attachment)) return "已就绪";
    const indexed = lastIndexingStage(attachment);
    if (indexed?.retrievable !== false) return "读取状态未知";
    return isImageAttachment(attachment.filename) ? "已保存·未识别" : "已保存·不可读取";
  }
  return "失败";
}

export function attachmentSelectionHint(attachment: SessionAttachmentInfo): string {
  if (attachment.status !== "ready") return "附件尚未处理完成，请稍后重试";
  if (isAttachmentReadable(attachment)) return "加入本条消息";
  const indexed = lastIndexingStage(attachment);
  if (indexed?.retrievable !== false) return "缺少可读取状态记录，请重新上传附件";
  if (isImageAttachment(attachment.filename)) {
    return "图片已保存但未识别；请在设置中开启云端图片理解后重新上传";
  }
  return "附件已保存但未生成可读取正文；请确认文件内容后重新上传";
}

export function isImageAttachment(filename: string): boolean {
  return /\.(png|jpe?g|gif|webp)$/i.test(filename);
}
