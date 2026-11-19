import { describe, expect, it } from "vitest";

import type { SessionAttachmentInfo } from "../../api";
import {
  ACCEPTED_EXTENSIONS,
  attachmentStatusLabel,
  attachmentSelectionHint,
  isAttachmentReadable,
  isImageAttachment,
} from "./attachmentRules";

function attachment(overrides: Partial<SessionAttachmentInfo> = {}): SessionAttachmentInfo {
  return {
    id: "a1", thread_id: "s1", filename: "notes.md", content_hash: "h",
    mime_type: "text/markdown", size_bytes: 12, status: "ready", stage_error: "",
    stage_history: [{ stage: "indexing", status: "completed", retrievable: true }],
    retry_count: 0, promoted_rag_run_id: "", external_calls: [], created_at: "", updated_at: "",
    ...overrides,
  };
}

describe("session attachment accept list", () => {
  it("advertises CSV alongside the other text documents", () => {
    expect(ACCEPTED_EXTENSIONS).toEqual([
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
    ]);
  });

  it("keeps CSV a document rather than an image", () => {
    expect(isImageAttachment("counts.csv")).toBe(false);
    expect(isImageAttachment("scan.png")).toBe(true);
  });

  it("requires affirmative indexed content, not merely a ready storage status", () => {
    const readable = attachment();
    const unrecognizedImage = attachment({
      filename: "photo.png", status: "ready",
      stage_history: [
        { stage: "parsing", status: "completed", detail: "image_stored_without_description" },
        { stage: "indexing", status: "completed", retrievable: false },
      ],
    });
    const emptyText = attachment({stage_history: [{stage: "indexing", status: "completed", retrievable: false}]});
    const unconfirmed = attachment({stage_history: []});
    const inProgress = attachment({status: "indexing"});

    expect(isAttachmentReadable(readable)).toBe(true);
    expect(attachmentStatusLabel(readable)).toBe("已就绪");
    expect(isAttachmentReadable(unrecognizedImage)).toBe(false);
    expect(attachmentStatusLabel(unrecognizedImage)).toBe("已保存·未识别");
    expect(attachmentSelectionHint(unrecognizedImage)).toContain("开启云端图片理解");
    expect(isAttachmentReadable(emptyText)).toBe(false);
    expect(attachmentStatusLabel(emptyText)).toBe("已保存·不可读取");
    expect(isAttachmentReadable(unconfirmed)).toBe(false);
    expect(attachmentStatusLabel(unconfirmed)).toBe("读取状态未知");
    expect(isAttachmentReadable(inProgress)).toBe(false);
  });
});
