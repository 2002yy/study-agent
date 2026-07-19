import { act, create, type ReactTestInstance } from "react-test-renderer";
import { describe, expect, it, vi } from "vitest";

import { SourcesPanel } from "./SourcesPanel";

function textContent(node: ReactTestInstance): string {
  return node.children
    .map((child) => (typeof child === "string" ? child : textContent(child)))
    .join("");
}

describe("SourcesPanel evidence eligibility", () => {
  it("explains which materials may support answers and exposes recovery actions", async () => {
    const onSetEvidenceStatus = vi.fn().mockResolvedValue(undefined);
    let renderer!: ReturnType<typeof create>;

    await act(async () => {
      renderer = create(
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
    });

    const rendered = JSON.stringify(renderer.toJSON());
    expect(rendered).toContain("当前可用于回答 1 个");
    expect(rendered).toContain("当前资料 · 会参与回答");
    expect(rendered).toContain("旧版本 · 不参与回答");
    expect(rendered).toContain("标记为旧版本");
    expect(rendered).toContain("不参与回答");
    expect(rendered).toContain("恢复为当前资料");

    const buttons = renderer.root.findAllByType("button");
    const exclude = buttons.find((button) => textContent(button).includes("不参与回答"));
    const restore = buttons.find((button) => textContent(button).includes("恢复为当前资料"));

    await act(async () => {
      await exclude?.props.onClick();
    });
    await act(async () => {
      await restore?.props.onClick();
    });

    expect(onSetEvidenceStatus).toHaveBeenCalledWith("current", "excluded");
    expect(onSetEvidenceStatus).toHaveBeenCalledWith("legacy", "active");

    act(() => renderer.unmount());
  });

  it("treats pre-K1b document payloads as active for upgrade compatibility", () => {
    let renderer!: ReturnType<typeof create>;
    act(() => {
      renderer = create(
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
    });

    expect(JSON.stringify(renderer.toJSON())).toContain("当前资料 · 会参与回答");
    expect(JSON.stringify(renderer.toJSON())).toContain("当前可用于回答 1 个");

    act(() => renderer.unmount());
  });
});
