// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ChatResponse } from "../../types";
import { EvidenceTrail } from "./EvidenceTrail";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const rag = {
  status: "found",
  query: "evidence",
  retrieval_mode: "hybrid",
  reason: "",
  context: "",
  sources: "",
  result_count: 1,
  results: [],
  debug: {},
  attempts: [],
  rewritten_query: "",
  evidence_snapshot: {
    schema_version: "evidence-snapshot-v1",
    disclosure_policy: "none",
    refs: [
      {
        id: "selected-1",
        type: "local",
        title: "Selected source",
        source: "selected.md",
        url: "",
        domain: "",
        published_at: "",
        score: 0.82,
        lifecycle_status: "selected",
        citation_status: "cited",
        provider_status: "found",
        selection_reason: "",
        rejection_reason: "",
      },
    ],
    pedagogy_evidence_ids: [],
    claim_links: [],
  },
} as ChatResponse["rag"];

function renderTrail() {
  render(<EvidenceTrail evidence={{ rag }} />);
  fireEvent.click(screen.getByRole("button", { name: /证据轨迹/ }));
}

describe("EvidenceTrail clipboard feedback", () => {
  it("announces successful ordinary evidence copy", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    renderTrail();

    fireEvent.click(screen.getByRole("button", { name: "复制引用" }));

    await waitFor(() => expect(screen.getByRole("button", { name: "已复制" })).toBeTruthy());
    expect(screen.getByRole("status")).toHaveTextContent("已核验引用已复制");
    expect(writeText).toHaveBeenCalledTimes(1);
  });

  it("does not swallow clipboard rejection for diagnostic copy", async () => {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn().mockRejectedValue(new Error("denied")) },
    });
    renderTrail();
    fireEvent.click(screen.getByRole("button", { name: "显示诊断详情" }));

    fireEvent.click(screen.getByRole("button", { name: "复制诊断" }));

    await waitFor(() => expect(screen.getByRole("button", { name: "复制失败" })).toBeTruthy());
    expect(screen.getByRole("status")).toHaveTextContent("复制失败，请检查浏览器剪贴板权限后重试");
  });
});
