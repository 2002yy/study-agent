import { describe, expect, it } from "vitest";
import { buildMemoryUpdatePayload } from "./MemoryPanel";

describe("buildMemoryUpdatePayload", () => {
  it("builds append updates for normal memory targets", () => {
    expect(
      buildMemoryUpdatePayload({
        target: "progress",
        content: "  finished RAG wiring  ",
        replaceCurrentFocus: true,
        learnerPending: true
      })
    ).toEqual({
      target: "progress",
      content: "finished RAG wiring",
      append: true,
      learner_pending: true
    });
  });

  it("allows current_focus replacement when explicitly selected", () => {
    expect(
      buildMemoryUpdatePayload({
        target: "current_focus",
        content: "Only finish memory UI",
        replaceCurrentFocus: true,
        learnerPending: false
      })
    ).toEqual({
      target: "current_focus",
      content: "Only finish memory UI",
      append: false,
      learner_pending: false
    });
  });

  it("rejects blank memory content", () => {
    expect(
      buildMemoryUpdatePayload({
        target: "summary",
        content: "   ",
        replaceCurrentFocus: false,
        learnerPending: false
      })
    ).toBeNull();
  });
});
