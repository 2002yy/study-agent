import { describe, expect, it } from "vitest";

import {
  DOUPO_CARD_ORDER,
  DOUPO_KNOWLEDGE_MATRIX,
  buildDoupoConversationContext,
  createDefaultDoupoLessonState,
  doupoGateDiagnosis,
  doupoValuationGap,
} from "./defaultDoupoLesson";

describe("default Doupo lesson model", () => {
  it("freezes the evidence-backed course as ten narrative cards", () => {
    expect(DOUPO_CARD_ORDER).toHaveLength(10);
    expect(DOUPO_CARD_ORDER[0]).toBe("debt");
    expect(DOUPO_CARD_ORDER[7]).toBe("identity-merge");
    expect(DOUPO_CARD_ORDER[9]).toBe("reader-pay");
  });

  it("keeps reader knowledge ahead of key in-world observers before the identity reveal", () => {
    const before = DOUPO_KNOWLEDGE_MATRIX["duel-open"];
    expect(before.reader["same-person"]).toBe("yes");
    expect(before["nalan-yanran"]["same-person"]).toBe("no");
    expect(before["liu-ling"]["same-person"]).toBe("no");

    const after = DOUPO_KNOWLEDGE_MATRIX["identity-reveal"];
    expect(after["nalan-yanran"]["same-person"]).toBe("yes");
    expect(after["liu-ling"]["same-person"]).toBe("yes");
  });

  it("models the social valuation lag and collapse at the identity merge", () => {
    expect(doupoValuationGap("retirement")).toBeGreaterThan(20);
    expect(doupoValuationGap("identity-merge")).toBeLessThan(
      doupoValuationGap("duel-open"),
    );
  });

  it("treats moral symmetry as a hard gate rather than another multiplier", () => {
    const state = createDefaultDoupoLessonState();
    expect(doupoGateDiagnosis(state)).toContain("七门完整");
    state.gates.G7 = false;
    expect(doupoGateDiagnosis(state)).toContain("道德反转");
  });

  it("injects current card and experiment state as transient chat context", () => {
    const state = createDefaultDoupoLessonState();
    state.activeCardId = "identity-merge";
    state.knowledgeMoment = "identity-reveal";
    state.valuationPoint = "identity-merge";
    state.identityMerged = true;
    state.gates.G6 = false;
    const context = buildDoupoConversationContext(state);

    expect(context).toContain("当前卡片：“岩枭=萧炎”为什么会炸？");
    expect(context).toContain("异火暴露后");
    expect(context).toContain("已执行‘岩枭=萧炎’");
    expect(context).toContain("G6 状态能够持久");
    expect(context).toContain("不得写入 durable learner truth");
  });
});
