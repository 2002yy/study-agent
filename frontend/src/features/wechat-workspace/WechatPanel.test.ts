import { describe, expect, it } from "vitest";
import { parseWechatMessages } from "./WechatPanel";

describe("parseWechatMessages", () => {
  it("splits role blocks and maps speakers to avatar roles", () => {
    expect(parseWechatMessages("【三月七】\n先拆状态。\n\n【用户】\n收到。\n\n【纳西妲】\n再整理记忆闭环。")).toEqual([
      { speaker: "三月七", roleId: "march7", text: "先拆状态。" },
      { speaker: "用户", roleId: "user", text: "收到。" },
      { speaker: "纳西妲", roleId: "nahida", text: "再整理记忆闭环。" }
    ]);
  });
});
