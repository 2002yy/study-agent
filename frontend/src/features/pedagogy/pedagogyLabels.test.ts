import { describe, expect, it } from "vitest";
import { moveLabel, phaseLabel, phaseTrail, protocolLabel } from "./pedagogyLabels";

describe("pedagogyLabels", () => {
  it("maps known moves to Chinese", () => {
    expect(moveLabel("give_hint")).toBe("给提示");
    expect(moveLabel("elicit_claim")).toBe("引出主张");
    expect(moveLabel("direct_explain")).toBe("直接讲解");
  });
  it("falls back to raw code for unknown moves", () => {
    expect(moveLabel("unknown_move")).toBe("unknown_move");
  });
  it("labels all backend protocol codes in Chinese", () => {
    expect(protocolLabel("socratic")).toBe("苏格拉底");
    expect(protocolLabel("socratic_rediscovery")).toBe("苏格拉底");
    expect(protocolLabel("feynman")).toBe("费曼");
    expect(protocolLabel("feynman_diagnosis")).toBe("费曼");
    expect(protocolLabel("project")).toBe("项目");
    expect(protocolLabel("project_execution")).toBe("项目");
    expect(protocolLabel("direct")).toBe("普通");
    expect(protocolLabel("direct_answer")).toBe("普通");
    expect(protocolLabel("auto")).toBe("自动");
  });
  it("labels internal phase codes in Chinese", () => {
    expect(phaseLabel("orientation")).toBe("建立目标");
    expect(phaseLabel("scaffold")).toBe("提供线索");
    expect(phaseLabel("test_assumption")).toBe("例子验证");
    expect(phaseLabel("re_explain")).toBe("重新解释");
  });
  it("falls back to raw code for unknown phases", () => {
    expect(phaseLabel("unknown_phase")).toBe("unknown_phase");
  });
  it("dedupes phase trail preserving order", () => {
    expect(phaseTrail(["orientation", "library_fact", "library_fact", "scaffold"]))
      .toEqual(["orientation", "library_fact", "scaffold"]);
  });
});
