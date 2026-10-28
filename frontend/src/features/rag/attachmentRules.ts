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

export function formatBytes(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  if (bytes >= 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${bytes} B`;
}

export function attachmentStatusLabel(status: SessionAttachmentInfo["status"]): string {
  if (status === "parsing") return "解析中";
  if (status === "chunking") return "分块中";
  if (status === "indexing") return "索引中";
  if (status === "ready") return "已就绪";
  return "失败";
}

export function isImageAttachment(filename: string): boolean {
  return /\.(png|jpe?g|gif|webp)$/i.test(filename);
}
