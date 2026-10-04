import { describe, expect, it } from "vitest";

import {
  bossHitCount,
  buildFireflyConversationContext,
  cloudflameToughness,
  createDefaultFireflyLessonState,
  oneGoldRecommendation,
  type FireflyLessonState,
} from "./defaultFireflyLesson";

function withState(patch: Partial<FireflyLessonState>): FireflyLessonState {
  const state = createDefaultFireflyLessonState();
  return {
    ...state,
    ...patch,
    oneGold: patch.oneGold ?? state.oneGold,
  };
}

describe("default Firefly lesson model", () => {
  it("keeps the boss experiment on the frozen 10/20/30 toughness scale", () => {
    expect(bossHitCount(300, "firefly-0")).toBe(7);
    expect(bossHitCount(600, "firefly-0")).toBe(14);
    expect(bossHitCount(1200, "firefly-0")).toBe(27);

    expect(bossHitCount(300, "dahlia-0")).toBe(4);
    expect(bossHitCount(600, "dahlia-0")).toBe(8);
    expect(bossHitCount(1200, "dahlia-0")).toBe(15);

    expect(bossHitCount(300, "dahlia-1")).toBe(3);
    expect(bossHitCount(600, "dahlia-1")).toBe(6);
    expect(bossHitCount(1200, "dahlia-1")).toBe(12);

    expect(bossHitCount(1200, "fugue-1")).toBe(10);
    expect(bossHitCount(1200, "firefly-6")).toBe(9);
    expect(bossHitCount("locked", "firefly-6")).toBeNull();
  });

  it("adds Fugue Cloudflame as a separate 40% toughness bar", () => {
    expect(cloudflameToughness(300)).toBe(120);
    expect(cloudflameToughness(600)).toBe(240);
    expect(cloudflameToughness(1200)).toBe(480);
    expect(cloudflameToughness("locked")).toBeNull();
  });

  it("covers the frozen A-G one-gold states without a fixed pull ranking", () => {
    const base = createDefaultFireflyLessonState();

    expect(oneGoldRecommendation(base).key).toBe("A");
    expect(
      oneGoldRecommendation(
        withState({
          painPoint: "actions",
          oneGold: { ...base.oneGold, fireflyEidolon: 1, dahliaEidolon: 0 },
        }),
      ).key,
    ).toBe("B");
    expect(
      oneGoldRecommendation(
        withState({
          painPoint: "break-slow",
          oneGold: { ...base.oneGold, fireflyEidolon: 2, dahliaEidolon: 0 },
        }),
      ).key,
    ).toBe("C");
    expect(
      oneGoldRecommendation(
        withState({
          painPoint: "single-hit",
          oneGold: { ...base.oneGold, dahliaEidolon: 0 },
        }),
      ).key,
    ).toBe("D");
    expect(
      oneGoldRecommendation(
        withState({
          environment: "high-resistance",
          oneGold: { ...base.oneGold, dahliaEidolon: 0 },
        }),
      ).key,
    ).toBe("E");
    expect(
      oneGoldRecommendation(
        withState({
          painPoint: "actions",
          oneGold: { ...base.oneGold, fugueEidolon: 0 },
        }),
      ).key,
    ).toBe("F");
    expect(
      oneGoldRecommendation(
        withState({
          painPoint: "survival",
          oneGold: { ...base.oneGold, sustain: "lingsha-0" },
        }),
      ).key,
    ).toBe("G");
  });

  it("injects the current card and experiment state only as transient chat context", () => {
    const state = withState({
      activeCardId: "dahlia",
      bossToughness: 1200,
      investment: "dahlia-1",
      painPoint: "break-slow",
    });
    const context = buildFireflyConversationContext(state);

    expect(context).toContain("当前卡片：大丽花");
    expect(context).toContain("1200韧性 / +大丽花1魂");
    expect(context).toContain("需要12次流萤强化战技");
    expect(context).toContain("不得写入 durable learner truth");
  });
});
