// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

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

  it("creates the session on demand so a first multimodal question needs no empty send", async () => {
    const ensureSession = vi.fn().mockResolvedValue("new-session");
    uploadSessionAttachment.mockResolvedValue(attachment());
    listSessionAttachments.mockResolvedValue({ attachments: [attachment()], max_files_per_thread: 5, total_bytes: 2048 });
    render(<ComposerAttachments onEnsureSession={ensureSession} />);
    expect(screen.getByRole("button", { name: "添加附件" })).toBeEnabled();

    const file = new File(["x"], "shot.png", { type: "image/png" });
    selectFiles(document.querySelector('input[type="file"]') as HTMLInputElement, [file]);

    await waitFor(() => expect(ensureSession).toHaveBeenCalled());
    await waitFor(() => expect(uploadSessionAttachment).toHaveBeenCalledWith("new-session", file));
  });

  it("reports when no session could be created for the attachment", async () => {
    const ensureSession = vi.fn().mockResolvedValue(undefined);
    render(<ComposerAttachments onEnsureSession={ensureSession} />);
    const file = new File(["x"], "shot.png", { type: "image/png" });
    selectFiles(document.querySelector('input[type="file"]') as HTMLInputElement, [file]);
    expect(await screen.findByRole("alert")).toHaveTextContent("无法创建会话");
    expect(uploadSessionAttachment).not.toHaveBeenCalled();
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

  it("toggles this message's selection without touching the session list", async () => {
    listSessionAttachments.mockResolvedValue({
      attachments: [attachment()], max_files_per_thread: 5, total_bytes: 2048,
    });
    const onSelectionChange = vi.fn();
    render(<ComposerAttachments sessionId="s1" selectedIds={[]} onSelectionChange={onSelectionChange} />);
    await screen.findByText("notes.pdf");

    fireEvent.click(screen.getByRole("button", { name: "选择附件 notes.pdf" }));
    expect(onSelectionChange).toHaveBeenCalledWith(["a1"]);
    expect(deleteSessionAttachment).not.toHaveBeenCalled();
  });

  it("shows which attachments are selected for the message", async () => {
    listSessionAttachments.mockResolvedValue({
      attachments: [attachment()], max_files_per_thread: 5, total_bytes: 2048,
    });
    render(<ComposerAttachments sessionId="s1" selectedIds={["a1"]} onSelectionChange={vi.fn()} />);
    await screen.findByText("notes.pdf");
    expect(screen.getByText("本次选中 1 个")).toBeVisible();
    expect(screen.getByRole("button", { name: "取消选择附件 notes.pdf" })).toHaveAttribute("aria-pressed", "true");
  });

  it("auto-selects a freshly uploaded attachment and cannot select a not-ready one", async () => {
    uploadSessionAttachment.mockResolvedValue(attachment({ id: "a3", filename: "new.png", status: "ready" }));
    listSessionAttachments
      .mockResolvedValueOnce({ attachments: [], max_files_per_thread: 5, total_bytes: 0 })
      .mockResolvedValue({
        attachments: [
          attachment({ id: "a3", filename: "new.png", status: "ready" }),
          attachment({ id: "a4", filename: "pending.pdf", status: "parsing" }),
        ],
        max_files_per_thread: 5, total_bytes: 4096,
      });
    const onSelectionChange = vi.fn();
    render(<ComposerAttachments sessionId="s1" selectedIds={[]} onSelectionChange={onSelectionChange} />);
    selectFiles(document.querySelector('input[type="file"]') as HTMLInputElement, [
      new File(["x"], "new.png", { type: "image/png" }),
    ]);
    await waitFor(() => expect(onSelectionChange).toHaveBeenCalledWith(["a3"]));
    expect(await screen.findByRole("button", { name: "选择附件 pending.pdf" })).toBeDisabled();
  });

  it("keeps the latest selection when an in-flight upload completes", async () => {
    const old = attachment();
    const another = attachment({ id: "a2", filename: "another.pdf" });
    const uploaded = attachment({ id: "a3", filename: "new.png" });
    listSessionAttachments.mockResolvedValue({
      attachments: [old, another, uploaded], max_files_per_thread: 5, total_bytes: 6144,
    });
    let completeUpload: ((created: SessionAttachmentInfo) => void) | undefined;
    uploadSessionAttachment.mockImplementation(
      () => new Promise<SessionAttachmentInfo>(resolve => { completeUpload = resolve; }),
    );
    const onSelectionChange = vi.fn();
    const { rerender } = render(
      <ComposerAttachments sessionId="s1" selectedIds={["a1"]} onSelectionChange={onSelectionChange} />,
    );
    await screen.findByText("notes.pdf");
    selectFiles(document.querySelector('input[type="file"]') as HTMLInputElement, [
      new File(["x"], "new.png", { type: "image/png" }),
    ]);
    await waitFor(() => expect(completeUpload).toBeDefined());

    // The user selects a2 while the upload is still pending.
    rerender(
      <ComposerAttachments sessionId="s1" selectedIds={["a1", "a2"]} onSelectionChange={onSelectionChange} />,
    );
    await act(async () => { completeUpload?.(uploaded); });
    await waitFor(() => expect(onSelectionChange).toHaveBeenCalledWith(["a1", "a2", "a3"]));
  });

  it("clears only a successfully deleted attachment from selection", async () => {
    const remaining = attachment({ id: "a2", filename: "keep.pdf" });
    listSessionAttachments.mockResolvedValue({
      attachments: [attachment(), remaining], max_files_per_thread: 5, total_bytes: 4096,
    });
    deleteSessionAttachment.mockResolvedValue(undefined);
    const onSelectionChange = vi.fn();
    render(<ComposerAttachments sessionId="s1" selectedIds={["a1", "a2"]} onSelectionChange={onSelectionChange} />);
    await screen.findByText("notes.pdf");
    fireEvent.click(screen.getByRole("button", { name: "移除附件 notes.pdf" }));
    await waitFor(() => expect(onSelectionChange).toHaveBeenCalledWith(["a2"]));
  });

  it("uses the latest selection when a deletion completes after a user change", async () => {
    const remaining = attachment({ id: "a2", filename: "keep.pdf" });
    listSessionAttachments.mockResolvedValue({
      attachments: [attachment(), remaining], max_files_per_thread: 5, total_bytes: 4096,
    });
    let completeDeletion: (() => void) | undefined;
    deleteSessionAttachment.mockImplementation(
      () => new Promise<void>(resolve => { completeDeletion = resolve; }),
    );
    const onSelectionChange = vi.fn();
    const { rerender } = render(
      <ComposerAttachments sessionId="s1" selectedIds={["a1"]} onSelectionChange={onSelectionChange} />,
    );
    await screen.findByText("notes.pdf");
    fireEvent.click(screen.getByRole("button", { name: "移除附件 notes.pdf" }));
    expect(completeDeletion).toBeDefined();

    // The user selected a2 while delete(a1) was still in flight.
    rerender(
      <ComposerAttachments sessionId="s1" selectedIds={["a1", "a2"]} onSelectionChange={onSelectionChange} />,
    );
    await act(async () => { completeDeletion?.(); });
    await waitFor(() => expect(onSelectionChange).toHaveBeenCalledWith(["a2"]));
  });

  it("leaves selection intact on failed deletion", async () => {
    listSessionAttachments.mockResolvedValue({
      attachments: [attachment()], max_files_per_thread: 5, total_bytes: 2048,
    });
    deleteSessionAttachment.mockRejectedValue(new Error("offline"));
    const onSelectionChange = vi.fn();
    render(<ComposerAttachments sessionId="s1" selectedIds={["a1"]} onSelectionChange={onSelectionChange} />);
    await screen.findByText("notes.pdf");
    fireEvent.click(screen.getByRole("button", { name: "移除附件 notes.pdf" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("附件删除失败");
    expect(onSelectionChange).not.toHaveBeenCalled();
  });
});
