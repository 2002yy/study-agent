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
    stage_history: [{stage: "indexing", status: "completed", retrievable: true}], retry_count: 0, promoted_rag_run_id: "", external_calls: [],
    created_at: "", updated_at: "", ...overrides,
  };
}

function selectFiles(input: HTMLInputElement, files: File[]) {
  Object.defineProperty(input, "files", { configurable: true, value: files });
  fireEvent.change(input);
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return {promise, resolve};
}

describe("ComposerAttachments", () => {
  it("does not replace a new session's files with a late listing from the old session", async () => {
    const oldRequest = deferred<Awaited<ReturnType<typeof import("../../api").listSessionAttachments>>>();
    const fromA = attachment({id: "old", thread_id: "s1", filename: "old.md"});
    const fromB = attachment({id: "new", thread_id: "s2", filename: "new.md"});
    listSessionAttachments.mockImplementation((session: string) => session === "s1"
      ? oldRequest.promise
      : Promise.resolve({attachments: [fromB], max_files_per_thread: 5, total_bytes: 2048}));
    const onSelectionChange = vi.fn();
    const {rerender} = render(<ComposerAttachments sessionId="s1" selectedIds={["old"]} onSelectionChange={onSelectionChange} />);
    await waitFor(() => expect(listSessionAttachments).toHaveBeenCalledWith("s1"));

    rerender(<ComposerAttachments sessionId="s2" selectedIds={["new"]} onSelectionChange={onSelectionChange} />);
    expect(await screen.findByText("new.md")).toBeVisible();
    await act(async () => oldRequest.resolve({attachments: [fromA], max_files_per_thread: 5, total_bytes: 2048}));
    expect(screen.getByText("new.md")).toBeVisible();
    expect(screen.queryByText("old.md")).not.toBeInTheDocument();
    expect(onSelectionChange).not.toHaveBeenCalled();
  });

  it("ignores an old session's upload completion and releases the new session's upload control", async () => {
    const pending = deferred<SessionAttachmentInfo>();
    const fromB = attachment({id: "new", thread_id: "s2", filename: "new.md"});
    listSessionAttachments.mockImplementation((session: string) => Promise.resolve({
      attachments: session === "s2" ? [fromB] : [], max_files_per_thread: 5, total_bytes: 2048,
    }));
    uploadSessionAttachment.mockReturnValue(pending.promise);
    const onSelectionChange = vi.fn();
    const {rerender} = render(<ComposerAttachments sessionId="s1" selectedIds={[]} onSelectionChange={onSelectionChange} />);
    selectFiles(document.querySelector('input[type="file"]') as HTMLInputElement, [
      new File(["text"], "old.md", {type: "text/markdown"}),
    ]);
    await waitFor(() => expect(uploadSessionAttachment).toHaveBeenCalledWith("s1", expect.any(File)));

    rerender(<ComposerAttachments sessionId="s2" selectedIds={[]} onSelectionChange={onSelectionChange} />);
    expect(await screen.findByText("new.md")).toBeVisible();
    expect(screen.getByRole("button", {name: "添加附件"})).toBeEnabled();
    await act(async () => pending.resolve(attachment({id: "old", thread_id: "s1", filename: "old.md"})));
    expect(screen.queryByText("old.md")).not.toBeInTheDocument();
    expect(onSelectionChange).not.toHaveBeenCalled();
  });

  it("does not resurrect a first-upload session when its creation returns after navigation", async () => {
    const pendingSession = deferred<string | undefined>();
    const onEnsureSession = vi.fn().mockReturnValue(pendingSession.promise);
    const fromB = attachment({id: "new", thread_id: "s2", filename: "new.md"});
    listSessionAttachments.mockResolvedValue({attachments: [fromB], max_files_per_thread: 5, total_bytes: 2048});
    const {rerender} = render(<ComposerAttachments onEnsureSession={onEnsureSession} />);
    selectFiles(document.querySelector('input[type="file"]') as HTMLInputElement, [
      new File(["text"], "old.md", {type: "text/markdown"}),
    ]);
    await waitFor(() => expect(onEnsureSession).toHaveBeenCalledTimes(1));

    rerender(<ComposerAttachments sessionId="s2" onEnsureSession={onEnsureSession} />);
    expect(await screen.findByText("new.md")).toBeVisible();
    await act(async () => pendingSession.resolve("s1"));
    expect(uploadSessionAttachment).not.toHaveBeenCalled();
    expect(screen.getByText("new.md")).toBeVisible();
  });

  it("keeps a valid first upload when its newly-created session becomes the parent session", async () => {
    const pendingSession = deferred<string | undefined>();
    const onEnsureSession = vi.fn().mockReturnValue(pendingSession.promise);
    const created = attachment({id: "created", thread_id: "s1", filename: "first.md"});
    uploadSessionAttachment.mockResolvedValue(created);
    listSessionAttachments.mockResolvedValue({attachments: [created], max_files_per_thread: 5, total_bytes: 2048});
    const onSelectionChange = vi.fn();
    const {rerender} = render(<ComposerAttachments onEnsureSession={onEnsureSession} onSelectionChange={onSelectionChange} />);
    selectFiles(document.querySelector('input[type="file"]') as HTMLInputElement, [
      new File(["text"], "first.md", {type: "text/markdown"}),
    ]);
    await waitFor(() => expect(onEnsureSession).toHaveBeenCalledTimes(1));
    rerender(<ComposerAttachments sessionId="s1" onEnsureSession={onEnsureSession} onSelectionChange={onSelectionChange} />);
    await act(async () => pendingSession.resolve("s1"));
    await waitFor(() => expect(uploadSessionAttachment).toHaveBeenCalledWith("s1", expect.any(File)));
    await waitFor(() => expect(onSelectionChange).toHaveBeenCalledWith(["created"]));
  });

  it("rejects the first visit's list after navigating away and back to the same id", async () => {
    const oldRequest = deferred<Awaited<ReturnType<typeof import("../../api").listSessionAttachments>>>();
    const fromA = attachment({id: "fresh", thread_id: "s1", filename: "fresh.md"});
    const fromB = attachment({id: "middle", thread_id: "s2", filename: "middle.md"});
    let s1Visits = 0;
    listSessionAttachments.mockImplementation((session: string) => {
      if (session === "s1" && ++s1Visits === 1) return oldRequest.promise;
      return Promise.resolve({attachments: [session === "s1" ? fromA : fromB], max_files_per_thread: 5, total_bytes: 2048});
    });
    const {rerender} = render(<ComposerAttachments sessionId="s1" />);
    await waitFor(() => expect(listSessionAttachments).toHaveBeenCalledWith("s1"));
    rerender(<ComposerAttachments sessionId="s2" />);
    expect(await screen.findByText("middle.md")).toBeVisible();
    rerender(<ComposerAttachments sessionId="s1" />);
    expect(await screen.findByText("fresh.md")).toBeVisible();
    await act(async () => oldRequest.resolve({attachments: [attachment({id: "stale", filename: "stale.md"})], max_files_per_thread: 5, total_bytes: 2048}));
    expect(screen.getByText("fresh.md")).toBeVisible();
    expect(screen.queryByText("stale.md")).not.toBeInTheDocument();
  });

  it("does not remove a new session's selection when an old deletion finishes", async () => {
    const pendingDeletion = deferred<void>();
    const fromA = attachment({id: "old", thread_id: "s1", filename: "old.md"});
    const fromB = attachment({id: "new", thread_id: "s2", filename: "new.md"});
    listSessionAttachments.mockImplementation((session: string) => Promise.resolve({
      attachments: [session === "s1" ? fromA : fromB], max_files_per_thread: 5, total_bytes: 2048,
    }));
    deleteSessionAttachment.mockReturnValue(pendingDeletion.promise);
    const onSelectionChange = vi.fn();
    const {rerender} = render(<ComposerAttachments sessionId="s1" selectedIds={["old"]} onSelectionChange={onSelectionChange} />);
    await screen.findByText("old.md");
    fireEvent.click(screen.getByRole("button", {name: "移除附件 old.md"}));
    await waitFor(() => expect(deleteSessionAttachment).toHaveBeenCalledWith("old"));

    rerender(<ComposerAttachments sessionId="s2" selectedIds={["new"]} onSelectionChange={onSelectionChange} />);
    expect(await screen.findByText("new.md")).toBeVisible();
    await act(async () => pendingDeletion.resolve());
    expect(screen.getByText("new.md")).toBeVisible();
    expect(onSelectionChange).not.toHaveBeenCalled();
  });
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
    await waitFor(() => expect(listSessionAttachments).toHaveBeenCalledTimes(2));
    expect(screen.getByRole("alert")).toHaveTextContent("超过 20.0 MB 上限");
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

  it("does not select a ready but unrecognized image on upload or manual click", async () => {
    const storedImage = attachment({
      id: "photo", filename: "photo.png", mime_type: "image/png",
      stage_history: [
        {stage: "parsing", status: "completed", detail: "image_stored_without_description"},
        {stage: "indexing", status: "completed", retrievable: false},
      ],
    });
    uploadSessionAttachment.mockResolvedValue(storedImage);
    listSessionAttachments.mockResolvedValue({
      attachments: [storedImage], max_files_per_thread: 5, total_bytes: 2048,
    });
    const onSelectionChange = vi.fn();
    render(<ComposerAttachments sessionId="s1" selectedIds={[]} onSelectionChange={onSelectionChange} />);
    await screen.findByText("photo.png");
    const pick = screen.getByRole("button", {name: "选择附件 photo.png"});
    expect(pick).toBeDisabled();
    expect(pick).toHaveAttribute("title", expect.stringContaining("开启云端图片理解"));
    expect(screen.getByText("已保存·未识别")).toBeVisible();
    fireEvent.click(pick);
    expect(onSelectionChange).not.toHaveBeenCalled();

    selectFiles(document.querySelector('input[type="file"]') as HTMLInputElement, [
      new File(["binary"], "photo.png", {type: "image/png"}),
    ]);
    await waitFor(() => expect(uploadSessionAttachment).toHaveBeenCalled());
    expect(await screen.findByRole("alert")).toHaveTextContent("开启云端图片理解");
    expect(onSelectionChange).not.toHaveBeenCalled();
  });

  it("auto-selects only readable files in a mixed upload, preserving existing selection", async () => {
    const storedImage = attachment({
      id: "photo", filename: "photo.png", mime_type: "image/png",
      stage_history: [{stage: "indexing", status: "completed", retrievable: false}],
    });
    const uploadedText = attachment({id: "doc", filename: "new.md"});
    uploadSessionAttachment.mockResolvedValueOnce(storedImage).mockResolvedValueOnce(uploadedText);
    listSessionAttachments.mockResolvedValue({
      attachments: [storedImage, uploadedText], max_files_per_thread: 5, total_bytes: 4096,
    });
    const onSelectionChange = vi.fn();
    render(<ComposerAttachments sessionId="s1" selectedIds={["prior"]} onSelectionChange={onSelectionChange} />);
    await screen.findByText("photo.png");
    selectFiles(document.querySelector('input[type="file"]') as HTMLInputElement, [
      new File(["binary"], "photo.png", {type: "image/png"}),
      new File(["text"], "new.md", {type: "text/markdown"}),
    ]);
    await waitFor(() => expect(onSelectionChange).toHaveBeenCalledWith(["prior", "doc"]));
    expect(onSelectionChange).not.toHaveBeenCalledWith(expect.arrayContaining(["photo"]));
  });

  it("removes a previously selected attachment once refresh proves it unreadable", async () => {
    const unreadable = attachment({
      stage_history: [{stage: "indexing", status: "completed", retrievable: false}],
    });
    listSessionAttachments.mockResolvedValue({
      attachments: [unreadable, attachment({id: "a2", filename: "readable.pdf"})], max_files_per_thread: 5, total_bytes: 4096,
    });
    const onSelectionChange = vi.fn();
    render(<ComposerAttachments sessionId="s1" selectedIds={["a1", "a2"]} onSelectionChange={onSelectionChange} />);
    await waitFor(() => expect(onSelectionChange).toHaveBeenCalledWith(["a2"]));
    expect(screen.getByRole("button", {name: "取消选择附件 notes.pdf"})).toBeDisabled();
  });

  it("does not re-introduce a stale unreadable selection when another upload finishes", async () => {
    const stale = attachment({
      id: "stale", filename: "old.png", mime_type: "image/png",
      stage_history: [{stage: "indexing", status: "completed", retrievable: false}],
    });
    const incoming = attachment({id: "new", filename: "new.md"});
    listSessionAttachments.mockResolvedValue({
      attachments: [stale, incoming], max_files_per_thread: 5, total_bytes: 4096,
    });
    uploadSessionAttachment.mockResolvedValue(incoming);
    const onSelectionChange = vi.fn();
    render(<ComposerAttachments sessionId="s1" selectedIds={["stale"]} onSelectionChange={onSelectionChange} />);
    await screen.findByText("old.png");
    selectFiles(document.querySelector('input[type="file"]') as HTMLInputElement, [
      new File(["text"], "new.md", {type: "text/markdown"}),
    ]);
    await waitFor(() => expect(onSelectionChange).toHaveBeenCalledWith(["new"]));
    expect(onSelectionChange).not.toHaveBeenCalledWith(["stale", "new"]);
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
