import { describe, expect, it } from "vitest";

import {
  DOUPO_CARD_ORDER,
  DOUPO_KNOWLEDGE_MATRIX,
  DOUPO_LOOP_PROFILES,
  DOUPO_LOOP_STAGE_ORDER,
  buildDoupoConversationContext,
  createDefaultDoupoLessonState,
  doupoValuationGap,
} from "./defaultDoupoLesson";

describe("default Doupo delight-loop model", () => {
  it("keeps ten structural cards while making the loop itself the authority", () => {
    expect(DOUPO_CARD_ORDER).toHaveLength(10);
    expect(DOUPO_LOOP_STAGE_ORDER).toEqual([
      "old-valuation",
      "debt",
      "suppression",
      "hidden-growth",
      "approach-reveal",
      "hard-evidence",
      "repricing",
      "retroactive",
      "new-debt",
    ]);
    expect(DOUPO_LOOP_PROFILES["three-year-settlement"].stages.retroactive).toContain("过去几百章");
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
    expect(doupoValuationGap("identity-merge")).toBeLessThan(doupoValuationGap("duel-open"));
  });

  it("injects the selected loop and stage as transient analysis context", () => {
    const state = createDefaultDoupoLessonState();
    state.activeCardId = "identity-merge";
    state.activeLoopId = "three-year-settlement";
    state.activeLoopStage = "retroactive";
    state.knowledgeMoment = "identity-reveal";
    state.valuationPoint = "identity-merge";
    state.identityMerged = true;
    const context = buildDoupoConversationContext(state);

    expect(context).toContain("当前《斗破苍穹》爽点循环分析状态");
    expect(context).toContain("三年之约：多条价值线一次性并账");
    expect(context).toContain("回溯重构");
    expect(context).toContain("已合并‘萧炎’与‘岩枭’");
    expect(context).toContain("不要把它改写成测验、课程目标或标准答案");
    expect(context).toContain("不写入长期学习状态");
  });
});
