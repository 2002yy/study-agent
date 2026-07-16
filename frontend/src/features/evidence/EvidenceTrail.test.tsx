import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { describe, expect, it } from "vitest";

import { EvidenceTrail } from "./EvidenceTrail";

describe("EvidenceTrail", () => {
  it("keeps recovered ResearchRun provenance without exposing the id in the label", () => {
    let renderer!: ReactTestRenderer;
    act(() => {
      renderer = create(
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
    });

    expect(JSON.stringify(renderer.toJSON())).toContain("恢复研究来源");
    expect(JSON.stringify(renderer.toJSON())).not.toContain("research-recovered-1");

    act(() => renderer.root.findByType("button").props.onClick());

    expect(
      renderer.root.findByProps({
        "data-research-run-id": "research-recovered-1",
      }),
    ).toBeTruthy();
  });
});
