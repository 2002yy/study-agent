import { describe, expect, it } from "vitest";

import {
  buildFireflyConversationContext,
  createDefaultFireflyLessonState,
} from "./defaultFireflyLesson";

describe("default lesson selection context", () => {
  it("routes transient chat context through the currently selected example", () => {
    const state = createDefaultFireflyLessonState();
    const fireflyContext = buildFireflyConversationContext(state);
    expect(fireflyContext).toContain("主题：流萤超击破体系");

    state.lessonKind = "doupo";
    state.doupo.activeCardId = "identity-merge";
    state.doupo.activeLoopId = "three-year-settlement";
    state.doupo.activeLoopStage = "retroactive";
    state.doupo.identityMerged = true;
    const doupoContext = buildFireflyConversationContext(state);
    expect(doupoContext).toContain("《斗破苍穹》爽点循环分析状态");
    expect(doupoContext).toContain("当前分析卡：身份合并：两份价值账户一次性并账");
    expect(doupoContext).toContain("回溯重构");
    expect(doupoContext).not.toContain("首领实验");
  });
});
