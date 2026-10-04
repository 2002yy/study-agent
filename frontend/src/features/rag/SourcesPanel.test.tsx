// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ChatResponse } from "../../types";
import { SourcesPanel } from "./SourcesPanel";
import type { EvidenceKnowledgeDocumentListResponse } from "./evidenceEligibilityApi";

afterEach(cleanup);

const baseRag: ChatResponse["rag"] = {
  status: "ready",
  query: "FastAPI dependency injection",
  retrieval_mode: "hybrid",
  reason: "",
  context: "candidate context must stay diagnostic",
  sources: "candidate source block",
  result_count: 2,
  results: [
    {
      chunk: {
        chunk_id: "selected-local",
        source_path: "src/fastapi/dependencies/utils.py",
        title: "dependency resolver",
        start_line: 10,
        end_line: 30,
      },
      score: 0.91,
      matched_terms: ["dependency", "resolver"],
    },
    {
      chunk: {
        chunk_id: "candidate-local",
        source_path: "docs/dependency-guide.md",
        title: "candidate guide",
        start_line: 2,
        end_line: 8,
      },
      score: 0.42,
      matched_terms: ["dependency"],
    },
  ],
  debug: {
    results: [
      {
        rank: 1,
        score: 0.91,
        source_path: "src/fastapi/dependencies/utils.py",
        title: "dependency resolver",
        line_range: "L10-L30",
        matched_terms: ["dependency", "resolver"],
        score_breakdown: { lexical: 0.8, vector: 0.95 },
      },
      {
        rank: 2,
        score: 0.42,
        source_path: "docs/dependency-guide.md",
        title: "candidate guide",
        line_range: "L2-L8",
        matched_terms: ["dependency"],
        score_breakdown: { lexical: 0.4, vector: 0.44 },
      },
    ],
  },
  attempts: [],
  rewritten_query: "FastAPI dependency resolver",
};

const lastChat = {
  reply: "FastAPI resolves dependencies before invoking the route handler.",
  session_id: "sources-layer-session",
  route: {
    task_contract: {
      task_intent: "learn",
      source_policy: "local_only",
      closure_eligibility: "learning_summary",
      learning_state_enabled: true,
    },
  },
  rag: {
    ...baseRag,
    evidence_snapshot: {
      schema_version: "evidence-snapshot-v1",
      refs: [
        {
          id: "selected-local",
          type: "local",
          title: "dependency resolver",
          source: "src/fastapi/dependencies/utils.py",
          lifecycle_status: "selected",
          score: 0.91,
          selection_reason: "supports the answer",
        },
        {
          id: "candidate-local",
          type: "local",
          title: "candidate guide",
          source: "docs/dependency-guide.md",
          lifecycle_status: "candidate",
          score: 0.42,
        },
      ],
    },
  } as unknown as ChatResponse["rag"],
  pedagogy: {
    mode: "socratic",
    phase: "verify",
    move: "probe",
    disclosure_level: 1,
    evidence_ids: ["selected-local"],
  },
} satisfies ChatResponse;

const knowledgeBase: EvidenceKnowledgeDocumentListResponse = {
  index_path: "fixture",
  index_exists: true,
  index_version: 3,
  chunks: 5,
  retrievable_documents: 1,
  retrievable_chunks: 3,
  documents: [
    {
      document_id: "doc-current",
      revision_id: "rev-current",
      title: "FastAPI source notes",
      source_path: "notes/fastapi-source.md",
      file_type: "md",
      content_hash: "fixture-current",
      chunks: 3,
      metadata: {},
      evidence_status: "active",
    },
    {
      document_id: "doc-old",
      revision_id: "rev-old",
      title: "Old FastAPI notes",
      source_path: "notes/fastapi-old.md",
      file_type: "md",
      content_hash: "fixture-old",
      chunks: 2,
      metadata: {},
      evidence_status: "superseded",
    },
  ],
};

function renderPanel() {
  return render(
    <SourcesPanel
      lastChat={lastChat}
      ragSearch={null}
      isSearching={false}
      knowledgeBase={knowledgeBase}
      onDeleteDocument={vi.fn()}
      onSetEvidenceStatus={vi.fn()}
      onRebuildKnowledge={vi.fn()}
    />,
  );
}

describe("SourcesPanel three-layer ownership", () => {
  it("defaults to adopted answer evidence without candidates, scores, or document management", () => {
    renderPanel();

    expect(screen.getByRole("tab", { name: "本次回答依据" })).toHaveAttribute("aria-selected", "true");
    const answerRegion = screen.getByRole("tabpanel");
    expect(within(answerRegion).getByText("dependency resolver")).toBeVisible();
    expect(within(answerRegion).getByText("教学明确引用")).toBeVisible();
    expect(screen.queryByText("candidate guide")).not.toBeInTheDocument();
    expect(screen.queryByText("FastAPI source notes")).not.toBeInTheDocument();
    expect(screen.queryByText(/分数：/)).not.toBeInTheDocument();
    expect(screen.queryByText("candidate context must stay diagnostic")).not.toBeInTheDocument();
  });

  it("shows lifecycle, candidates, scores, and context only in diagnostics", () => {
    renderPanel();
    fireEvent.click(screen.getByRole("tab", { name: "检索诊断" }));

    const diagnostics = screen.getByRole("tabpanel");
    expect(within(diagnostics).getByRole("heading", { name: "证据生命周期" })).toBeVisible();
    expect(within(diagnostics).getAllByText("candidate guide").length).toBeGreaterThan(0);
    expect(within(diagnostics).getByText("相关度：0.420")).toBeVisible();
    expect(within(diagnostics).getByText("生命周期：候选")).toBeVisible();
    expect(within(diagnostics).getByText("candidate context must stay diagnostic")).toBeInTheDocument();
    expect(screen.queryByText("FastAPI source notes")).not.toBeInTheDocument();
  });

  it("keeps document management in the library layer", () => {
    renderPanel();
    fireEvent.click(screen.getByRole("tab", { name: "我的资料" }));

    const library = screen.getByRole("tabpanel");
    expect(within(library).getByText("FastAPI source notes")).toBeVisible();
    expect(within(library).getByText("Old FastAPI notes")).toBeVisible();
    expect(within(library).getByText("当前资料 · 会参与回答")).toBeVisible();
    expect(within(library).getByText("旧版本 · 不参与回答")).toBeVisible();
    expect(within(library).getAllByRole("button", { name: "删除资料" })).toHaveLength(2);
    expect(screen.queryByText("candidate guide")).not.toBeInTheDocument();
    expect(screen.queryByText(/分数：/)).not.toBeInTheDocument();
  });
});
