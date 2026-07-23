// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EvidenceTrail } from "./EvidenceTrail";

describe("EvidenceTrail", () => {
  it("keeps recovered ResearchRun provenance without exposing the id in the label", () => {
    const { container } = render(
      <EvidenceTrail
        evidence={{
          rag: {
            status: "found",
            query: "recovered",
            retrieval_mode: "hybrid",
            reason: "",
            context: "",
            sources: "",
            result_count: 0,
            results: [],
            debug: {},
            attempts: [],
            rewritten_query: "",
            web_context: {
              used: true,
              run_id: "research-recovered-1",
              source: "research_run",
            },
          },
        }}
      />,
    );

    expect(container).toHaveTextContent("恢复研究来源");
    expect(container).not.toHaveTextContent("research-recovered-1");

    fireEvent.click(screen.getByRole("button", { name: /证据轨迹/ }));

    expect(
      container.querySelector('[data-research-run-id="research-recovered-1"]'),
    ).toBeTruthy();
  });
});
