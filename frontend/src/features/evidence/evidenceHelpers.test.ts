import { describe, expect, it } from "vitest";
import {
  buildCitations,
  evidenceFromResponse,
  evidenceFromSessionTurns,
  summarizeWebCalls,
} from "./evidenceHelpers";
import type { ChatResponse } from "../../types";

const baseRag: ChatResponse["rag"] = {
  status: "ok",
  query: "q",
  retrieval_mode: "hybrid",
  reason: "",
  context: "",
  sources: "",
  result_count: 1,
  results: [],
  debug: {},
  attempts: [],
  rewritten_query: "",
};

describe("evidenceHelpers", () => {
  it("summarizes web_search and web_read calls", () => {
    const calls = summarizeWebCalls([
      { name: "web_search", arguments: { query: "FastAPI" }, result: { results: [{ title: "t", url: "u" }] } },
      { name: "web_read", arguments: { url: "https://x.com" }, result: { ok: "true", content: "page".repeat(200) } },
    ]);
    expect(calls.searches).toEqual([{ query: "FastAPI", results: [{ title: "t", url: "u" }] }]);
    expect(calls.reads[0].url).toBe("https://x.com");
    expect(calls.reads[0].preview.length).toBeLessThanOrEqual(300);
  });
  it("builds citations from rag results", () => {
    const cites = buildCitations({
      ...baseRag,
      results: [{ title: "Doc", source_path: "a.md", score: 0.8 }] as never,
    });
    expect(cites[0]).toMatchObject({ title: "Doc", source: "a.md", score: 0.8 });
  });
  it("builds evidence from a ChatResponse", () => {
    const resp: ChatResponse = {
      reply: "r",
      session_id: "s",
      turn_id: "t1",
      route: { mode: "socratic" },
      rag: baseRag,
      pedagogy: { mode: "socratic", phase: "scaffold", move: "give_hint", disclosure_level: 2 },
    };
    const ev = evidenceFromResponse(resp);
    expect(ev.pedagogy?.move).toBe("give_hint");
    expect(ev.rag).toBe(baseRag);
    expect(ev.route).toEqual({ mode: "socratic" });
  });
  it("maps session turns to evidence by turnId (pedagogy only)", () => {
    const map = evidenceFromSessionTurns([
      {
        turn_id: "t1",
        pedagogy_snapshot: { mode: "socratic", move: "give_hint", phase: "scaffold", disclosure_level: 1 },
      },
    ]);
    expect(map.get("t1")?.pedagogy?.move).toBe("give_hint");
    expect(map.get("t1")?.rag).toBeUndefined();
  });
});
