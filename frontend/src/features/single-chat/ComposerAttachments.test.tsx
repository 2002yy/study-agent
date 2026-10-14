// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

const listSessionAttachments = vi.fn();
const uploadSessionAttachment = vi.fn();
const deleteSessionAttachment = vi.fn();

vi.mock("../../api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../api")>()),
  listSessionAttachments: (...args: unknown[]) => listSessionAttachments(...args),
  uploadSessionAttachment: (...args: unknown[]) => uploadSessionAttachment(...args),
  deleteSessionAttachment: (...args: unknown[]) => deleteSessionAttachment(...args),
}));

import type { SessionAttachmentInfo } from "../../api";
import { ComposerAttachments } from "./ComposerAttachments";

afterEach(cleanup);
beforeEach(() => {
  vi.clearAllMocks();
  listSessionAttachments.mockResolvedValue({ attachments: [], max_files_per_thread: 5, total_bytes: 0 });
});

function attachment(overrides: Partial<SessionAttachmentInfo> = {}): SessionAttachmentInfo {
  return {
    id: "a1", thread_id: "s1", filename: "notes.pdf", content_hash: "h",
    mime_type: "application/pdf", size_bytes: 2048, status: "ready", stage_error: "",
    stage_history: [], retry_count: 0, promoted_rag_run_id: "", external_calls: [],
    created_at: "", updated_at: "", ...overrides,
  };
}

function selectFiles(input: HTMLInputElement, files: File[]) {
  Object.defineProperty(input, "files", { configurable: true, value: files });
  fireEvent.change(input);
}

describe("ComposerAttachments", () => {
  it("stays unavailable until a session exists", () => {
    render(<ComposerAttachments />);
    expect(screen.getByRole("button", { name: "添加附件" })).toBeDisabled();
    expect(listSessionAttachments).not.toHaveBeenCalled();
  });

  it("uploads a selected file to the current session and shows a chip", async () => {
    uploadSessionAttachment.mockResolvedValue(attachment());
    listSessionAttachments
      .mockResolvedValueOnce({ attachments: [], max_files_per_thread: 5, total_bytes: 0 })
      .mockResolvedValue({ attachments: [attachment()], max_files_per_thread: 5, total_bytes: 2048 });
    render(<ComposerAttachments sessionId="s1" />);
    const file = new File(["hello"], "notes.pdf", { type: "application/pdf" });
    selectFiles(document.querySelector('input[type="file"]') as HTMLInputElement, [file]);

    await waitFor(() => expect(uploadSessionAttachment).toHaveBeenCalledWith("s1", file));
    expect(await screen.findByText("notes.pdf")).toBeVisible();
    expect(screen.getByText("已就绪")).toBeVisible();
  });

  it("removes an attachment", async () => {
    listSessionAttachments.mockResolvedValue({ attachments: [attachment()], max_files_per_thread: 5, total_bytes: 2048 });
    deleteSessionAttachment.mockResolvedValue(undefined);
    render(<ComposerAttachments sessionId="s1" />);
    await screen.findByText("notes.pdf");
    fireEvent.click(screen.getByRole("button", { name: "移除附件 notes.pdf" }));
    await waitFor(() => expect(deleteSessionAttachment).toHaveBeenCalledWith("a1"));
  });

  it("refuses a file over the size limit without uploading it", async () => {
    render(<ComposerAttachments sessionId="s1" />);
    const big = new File(["x"], "big.pdf", { type: "application/pdf" });
    Object.defineProperty(big, "size", { configurable: true, value: 21 * 1024 * 1024 });
    selectFiles(document.querySelector('input[type="file"]') as HTMLInputElement, [big]);

    expect(await screen.findByRole("alert")).toHaveTextContent("超过 20.0 MB 上限");
    expect(uploadSessionAttachment).not.toHaveBeenCalled();
  });

  it("disables attaching once the per-session limit is reached", async () => {
    listSessionAttachments.mockResolvedValue({
      attachments: [attachment(), attachment({ id: "a2", filename: "two.pdf" })],
      max_files_per_thread: 2, total_bytes: 4096,
    });
    render(<ComposerAttachments sessionId="s1" />);
    await screen.findByText("notes.pdf");
    expect(screen.getByRole("button", { name: "添加附件" })).toBeDisabled();
  });
});
