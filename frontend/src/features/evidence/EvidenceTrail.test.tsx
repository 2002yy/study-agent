// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ChatResponse } from "../../types";
import {
  EvidenceTrail,
  formatEvidencePlainText,
} from "./EvidenceTrail";
import type { EvidenceRef } from "./evidenceHelpers";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const baseRag: ChatResponse["rag"] = {
  status: "found",
  query: "evidence",
  retrieval_mode: "hybrid",
  reason: "",
  context: "",
  sources: "",
  result_count: 0,
  results: [],
  debug: {},
  attempts: [],
  rewritten_query: "",
};

function ragWithServerRefs(refs: Array<Record<string, unknown>>): ChatResponse["rag"] {
  return {
    ...baseRag,
    evidence_snapshot: {
      schema_version: "evidence-snapshot-v1",
      disclosure_policy: "none",
      refs,
      pedagogy_evidence_ids: [],
      claim_links: [],
    },
  } as ChatResponse["rag"];
}

function serverRef(
  id: string,
  title: string,
  lifecycleStatus: "candidate" | "read" | "selected" | "rejected",
  overrides: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    id,
    type: "local",
    title,
    source: `${id}.md`,
    url: "",
    domain: "",
    published_at: "",
    score: 0.82,
    lifecycle_status: lifecycleStatus,
    provider_status: "found",
    selection_reason: "",
    rejection_reason: "",
    ...overrides,
  };
}

describe("EvidenceTrail display layering", () => {
  it("keeps recovered ResearchRun provenance inside explicit diagnostics", () => {
    const { container } = render(
      <EvidenceTrail
        evidence={{
          rag: {
            ...baseRag,
            web_context: {
              used: true,
              run_id: "research-recovered-1",
              source: "research_run",
            },
          },
        }}
      />,
    );

    expect(container).not.toHaveTextContent("已恢复的联网研究来源");
    expect(container).not.toHaveTextContent("research-recovered-1");

    fireEvent.click(screen.getByRole("button", { name: /证据轨迹/ }));
    expect(container).not.toHaveTextContent("已恢复的联网研究来源");
    expect(
      container.querySelector('[data-research-run-id="research-recovered-1"]'),
    ).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "显示诊断详情" }));

    expect(container).toHaveTextContent("本轮使用了已恢复的联网研究来源");
    expect(
      container.querySelector('[data-research-run-id="research-recovered-1"]'),
    ).toBeTruthy();
    expect(container).not.toHaveTextContent("research-recovered-1");
  });

  it("does not turn a selected source into a citation", () => {
    const { container } = render(
      <EvidenceTrail
        evidence={{
          rag: ragWithServerRefs([
            serverRef("selected-1", "Selected source", "selected", {
              selection_reason: "research_run:research-1",
            }),
          ]),
        }}
      />,
    );

    expect(container).not.toHaveTextContent("已核验引用");
    fireEvent.click(screen.getByRole("button", { name: /证据轨迹/ }));

    expect(container).toHaveTextContent("本轮没有通过发布校验的引用");
    expect(container).toHaveTextContent("已读取或已选中但未引用（1 条）");
    expect(container).toHaveTextContent("Selected source");
    expect(container).not.toHaveTextContent("0.82");

    fireEvent.click(screen.getByRole("button", { name: "显示诊断详情" }));

    expect(container).toHaveTextContent("已选中");
    expect(container).toHaveTextContent("0.82");
    expect(container).toHaveTextContent("采用原因：原因待确认");
  });

  it("does not present unverified sources as citations", () => {
    const { container } = render(
      <EvidenceTrail
        evidence={{
          rag: ragWithServerRefs([
            serverRef("candidate-1", "Candidate source", "candidate"),
            serverRef("read-1", "Read source", "read", {
              type: "web_read",
              url: "https://example.com/read",
            }),
            serverRef("rejected-1", "Rejected source", "rejected", {
              type: "research",
              rejection_reason: "duplicate",
            }),
          ]),
        }}
      />,
    );

    expect(container).not.toHaveTextContent("已核验引用");
    fireEvent.click(screen.getByRole("button", { name: /证据轨迹/ }));

    expect(container).toHaveTextContent("本轮没有通过发布校验的引用");
    expect(container).toHaveTextContent("Read source");
    expect(container).not.toHaveTextContent("Candidate source");
    expect(container).not.toHaveTextContent("Rejected source");

    fireEvent.click(screen.getByRole("button", { name: "显示诊断详情" }));

    expect(container).toHaveTextContent("Candidate source");
    expect(container).toHaveTextContent("Rejected source");
    expect(container).toHaveTextContent("候选");
    expect(container).toHaveTextContent("已读取");
    expect(container).toHaveTextContent("已排除");
    expect(container).toHaveTextContent("重复来源");
  });

  it("labels legacy sources without read truth as unknown candidates", () => {
    const { container } = render(
      <EvidenceTrail
        evidence={{
          rag: ragWithServerRefs([
            serverRef("legacy-1", "Legacy source", "candidate", {
              type: "research",
              url: "https://example.com/legacy",
              provider_status: "legacy_unknown",
            }),
          ]),
        }}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /证据轨迹/ }));
    fireEvent.click(screen.getByRole("button", { name: "显示诊断详情" }));

    expect(container).toHaveTextContent("Legacy source");
    expect(container).toHaveTextContent("旧版候选 · 验证状态未知");
    expect(container.querySelector(".evidence-summary-flag")).toBeNull();
  });

  it("shows search candidates as an explicit 3/N expandable preview", () => {
    const results = Array.from({ length: 5 }, (_, index) => ({
      title: `Candidate ${index + 1}`,
      url: `https://example.com/${index + 1}`,
    }));
    const { container } = render(
      <EvidenceTrail
        evidence={{
          rag: {
            ...baseRag,
            web_tools: {
              enabled: true,
              used: false,
              calls: [
                {
                  name: "web_search",
                  arguments: { query: "opus5" },
                  result: { status: "ok", results },
                },
              ],
              evidence_status: "candidate_only",
              candidate_count: 5,
            },
          },
        }}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /证据轨迹/ }));
    fireEvent.click(screen.getByRole("button", { name: "显示诊断详情" }));

    expect(container).toHaveTextContent("候选（预览 3/5）");
    const overflow = screen.getByText("查看其余 2 条候选").closest("details");
    expect(overflow).not.toHaveAttribute("open");
    fireEvent.click(screen.getByText("查看其余 2 条候选"));
    expect(overflow).toHaveAttribute("open");
  });

  it("does not treat a pedagogy evidence id as citation authority", () => {
    const { container } = render(
      <EvidenceTrail
        evidence={{
          pedagogy: {
            mode: "socratic",
            phase: "scaffold",
            move: "give_hint",
            disclosure_level: 1,
            evidence_ids: ["chunk-1"],
          },
          rag: ragWithServerRefs([
            serverRef("chunk-1", "TaskContract", "candidate", {
              source: "docs/task_contract.md",
            }),
          ]),
        }}
      />,
    );

    expect(container).not.toHaveTextContent("已核验引用");
    fireEvent.click(screen.getByRole("button", { name: /证据轨迹/ }));

    expect(container).toHaveTextContent("本轮没有通过发布校验的引用");
    expect(container).not.toHaveTextContent("TaskContract");

    fireEvent.click(screen.getByRole("button", { name: "显示诊断详情" }));

    expect(container).toHaveTextContent("TaskContract");
    expect(container).toHaveTextContent("引");
    expect(container).toHaveTextContent("候选");
  });
});

describe("formatEvidencePlainText", () => {
  const ref: EvidenceRef = {
    id: "source-1",
    type: "research",
    title: "Official source",
    source: "web_source_1",
    domain: "example.com",
    url: "https://example.com/guide",
    score: 0.95,
    status: "selected",
    providerStatus: "partial",
    selectionReason: "research_run:research-1",
  };

  it("keeps ordinary copy free of lifecycle, scores, and provider diagnostics", () => {
    const text = formatEvidencePlainText(undefined, [ref]);

    expect(text).toContain("已核验引用");
    expect(text).toContain("Official source");
    expect(text).not.toContain("[已选中]");
    expect(text).not.toContain("score=");
    expect(text).not.toContain("provider=");
    expect(text).not.toContain("research_run:research-1");
  });

  it("includes lifecycle and technical fields only in diagnostic copy", () => {
    const text = formatEvidencePlainText(undefined, [ref], true);

    expect(text).toContain("证据诊断");
    expect(text).toContain("[已选中]");
    expect(text).toContain("相关度：0.95");
    expect(text).toContain("来源状态：部分通过");
    expect(text).toContain("采用原因：原因待确认");
  });
});

describe("verified citations", () => {
  it("shows a cited source in the verified section only", () => {
    const { container } = render(
      <EvidenceTrail
        evidence={{
          rag: ragWithServerRefs([
            serverRef("tool_read_1", "Official release notes", "selected", {
              type: "research",
              url: "https://official.example/release",
              citation_status: "cited",
            }),
          ]),
        }}
      />,
    );

    expect(container).toHaveTextContent("已核验引用 1");
    fireEvent.click(screen.getByRole("button", { name: /证据轨迹/ }));

    expect(container).toHaveTextContent("已核验引用（1 条）");
    expect(container).toHaveTextContent("Official release notes");
    expect(container).not.toHaveTextContent("已读取或已选中但未引用");
    expect(container).not.toHaveTextContent("本轮没有通过发布校验的引用");
  });

  it("renders one row per page when a source carries two server ids", () => {
    const { container } = render(
      <EvidenceTrail
        evidence={{
          rag: ragWithServerRefs([
            serverRef("tool_read_1", "Official release notes", "selected", {
              type: "research",
              url: "https://official.example/release",
              citation_status: "cited",
            }),
            serverRef("https://official.example/release", "Official release notes", "read", {
              type: "web_read",
              url: "https://official.example/release/",
              citation_status: "unverified",
            }),
          ]),
        }}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /证据轨迹/ }));

    expect(container).toHaveTextContent("已核验引用（1 条）");
    expect(container).not.toHaveTextContent("已读取或已选中但未引用");
    expect(
      container.querySelectorAll('[aria-label="已核验引用"] .evidence-ref-row'),
    ).toHaveLength(1);
  });

  it("preserves case-sensitive path and query values when grouping pages", () => {
    const { container } = render(
      <EvidenceTrail
        evidence={{
          rag: ragWithServerRefs([
            serverRef("cited-release", "Upper-case Release", "selected", {
              type: "research",
              url: "https://EXAMPLE.org/Release",
              citation_status: "cited",
            }),
            serverRef("cited-lower", "Lower-case release", "selected", {
              type: "research",
              url: "https://example.org/release",
              citation_status: "cited",
            }),
            serverRef("unverified-query", "Different query value", "read", {
              type: "web_read",
              url: "https://example.org/Release?file=abc",
              citation_status: "unverified",
            }),
            serverRef("cited-query", "Upper-case query value", "selected", {
              type: "research",
              url: "https://example.org/Release?file=ABC",
              citation_status: "cited",
            }),
          ]),
        }}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /证据轨迹/ }));
    expect(container).toHaveTextContent("已核验引用（3 条）");
    expect(
      container.querySelectorAll('[aria-label="已核验引用"] .evidence-ref-row'),
    ).toHaveLength(3);
    expect(container).toHaveTextContent("已读取或已选中但未引用（1 条）");
    expect(container).toHaveTextContent("Different query value");
  });

  it("treats a missing citation status as none", () => {
    const { container } = render(
      <EvidenceTrail
        evidence={{
          rag: ragWithServerRefs([
            serverRef("legacy-1", "Legacy selected source", "selected"),
          ]),
        }}
      />,
    );

    expect(container).not.toHaveTextContent("已核验引用");
    fireEvent.click(screen.getByRole("button", { name: /证据轨迹/ }));
    expect(container).toHaveTextContent("已读取或已选中但未引用（1 条）");
  });

  it("does not invent a citation when the server sent no cited ref", () => {
    const { container } = render(
      <EvidenceTrail
        evidence={{
          rag: {
            ...ragWithServerRefs([
              serverRef("read-1", "Read source", "read", {
                type: "web_read",
                url: "https://example.com/read",
              }),
            ]),
            citation_links: [
              { claim_id: "claim_x", evidence_id: "missing_source", confidence: 0.9 },
            ],
          } as ChatResponse["rag"],
        }}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /证据轨迹/ }));
    expect(container).not.toHaveTextContent("已核验引用（");
    expect(container).toHaveTextContent("已读取或已选中但未引用（1 条）");
  });
});
