// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SourcesPanel } from "./SourcesPanel";

describe("SourcesPanel evidence eligibility", () => {
  it("explains which materials may support answers and exposes recovery actions", async () => {
    const onSetEvidenceStatus = vi.fn().mockResolvedValue(undefined);
    const { container } = render(
      <SourcesPanel
        lastChat={null}
        ragSearch={null}
        isSearching={false}
        knowledgeBase={{
          index_path: "rag.json",
          index_exists: true,
          index_version: 3,
          chunks: 6,
          retrievable_documents: 1,
          retrievable_chunks: 3,
          documents: [
            {
              document_id: "current",
              revision_id: "current-r1",
              title: "Current notes",
              source_path: "current.md",
              file_type: "md",
              content_hash: "hash-current",
              chunks: 3,
              metadata: {},
              evidence_status: "active",
              superseded_by_document_id: "",
            },
            {
              document_id: "legacy",
              revision_id: "legacy-r1",
              title: "Legacy notes",
              source_path: "legacy.md",
              file_type: "md",
              content_hash: "hash-legacy",
              chunks: 3,
              metadata: {},
              evidence_status: "superseded",
              superseded_by_document_id: "current",
            },
          ],
        }}
        onSetEvidenceStatus={onSetEvidenceStatus}
      />,
    );

    const renderedText = container.textContent ?? "";
    expect(renderedText).toContain("当前可用于回答 1 个");
    expect(renderedText).toContain("当前资料 · 会参与回答");
    expect(renderedText).toContain("旧版本 · 不参与回答");
    expect(renderedText).toContain("标记为旧版本");
    expect(renderedText).toContain("不参与回答");
    expect(renderedText).toContain("恢复为当前资料");

    const buttons = screen.getAllByRole("button");
    const exclude = buttons.find((button) => (button.textContent ?? "").includes("不参与回答"));
    const restore = buttons.find((button) => (button.textContent ?? "").includes("恢复为当前资料"));

    await act(async () => {
      fireEvent.click(exclude as HTMLButtonElement);
    });
    await act(async () => {
      fireEvent.click(restore as HTMLButtonElement);
    });

    expect(onSetEvidenceStatus).toHaveBeenCalledWith("current", "excluded");
    expect(onSetEvidenceStatus).toHaveBeenCalledWith("legacy", "active");
  });

  it("treats pre-K1b document payloads as active for upgrade compatibility", () => {
    const { container } = render(
      <SourcesPanel
        lastChat={null}
        ragSearch={null}
        isSearching={false}
        knowledgeBase={{
          index_path: "rag.json",
          index_exists: true,
          index_version: 1,
          chunks: 1,
          documents: [
            {
              document_id: "legacy-payload",
              revision_id: "r1",
              title: "Existing material",
              source_path: "existing.md",
              file_type: "md",
              content_hash: "hash",
              chunks: 1,
              metadata: {},
            },
          ],
        }}
      />,
    );

    const renderedText = container.textContent ?? "";
    expect(renderedText).toContain("当前资料 · 会参与回答");
    expect(renderedText).toContain("当前可用于回答 1 个");
  });
});
