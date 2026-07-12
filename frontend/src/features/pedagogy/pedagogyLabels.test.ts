import { describe, expect, it } from "vitest";
import { deriveMastery, moveLabel, phaseTrail, protocolLabel } from "./pedagogyLabels";
import type { LearningState } from "../../types";

describe("pedagogyLabels", () => {
  it("maps known moves to Chinese", () => {
    expect(moveLabel("give_hint")).toBe("给提示");
    expect(moveLabel("elicit_claim")).toBe("引出主张");
    expect(moveLabel("direct_explain")).toBe("直接讲解");
  });
  it("falls back to raw code for unknown moves", () => {
    expect(moveLabel("unknown_move")).toBe("unknown_move");
  });
  it("labels protocols in Chinese", () => {
    expect(protocolLabel("socratic")).toBe("苏格拉底");
    expect(protocolLabel("socratic_rediscovery")).toBe("苏格拉底");
    expect(protocolLabel("feynman")).toBe("费曼");
    expect(protocolLabel("project")).toBe("项目");
    expect(protocolLabel("direct")).toBe("普通");
    expect(protocolLabel("auto")).toBe("自动");
  });
  it("derives mastery in (0,1) from points and phase trail", () => {
    const state: LearningState = {
      protocol: "socratic",
      objective: "x",
      phase: "scaffold",
      unresolved_gap: "gap",
      confirmed_points: ["a", "b"],
      hint_level: 1,
      turn_count: 4,
    };
    const m = deriveMastery(state, ["orientation", "library_fact", "scaffold"]);
    expect(m).toBeGreaterThan(0);
    expect(m).toBeLessThan(1);
  });
  it("dedupes phase trail preserving order", () => {
    expect(phaseTrail(["orientation", "library_fact", "library_fact", "scaffold"]))
      .toEqual(["orientation", "library_fact", "scaffold"]);
  });
});
