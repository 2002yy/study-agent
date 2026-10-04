// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FireflyCoreDataArchive } from "./FireflyCoreDataArchive";
import { FIREFLY_CORE_CHARACTER_DATA, FIREFLY_ROUTE_SUPPORT_SCOPE } from "./fireflyCharacterData";
import { FIREFLY_CORE_LIGHT_CONES } from "./fireflyCoreLightCones";

describe("Firefly core character data depth", () => {
  it("keeps five core characters at complete-data scope", () => {
    expect(Object.keys(FIREFLY_CORE_CHARACTER_DATA)).toEqual([
      "firefly",
      "dahlia",
      "fugue",
      "lingsha",
      "gallagher",
    ]);
    for (const [key, character] of Object.entries(FIREFLY_CORE_CHARACTER_DATA)) {
      expect(character.skills.length).toBeGreaterThanOrEqual(5);
      expect(character.skills.some((skill) => skill.name.includes("秘技"))).toBe(true);
      expect(character.traces).toHaveLength(3);
      expect(character.eidolons).toHaveLength(6);
      expect(FIREFLY_CORE_LIGHT_CONES[key as keyof typeof FIREFLY_CORE_LIGHT_CONES].length).toBeGreaterThanOrEqual(3);
    }
  });

  it("locks the post-4.2 Firefly numeric contract", () => {
    const firefly = FIREFLY_CORE_CHARACTER_DATA.firefly;
    expect(firefly.versionNote).toContain("4.2加强后");
    expect(firefly.skills.find((skill) => skill.name === "战技")?.energy).toContain("144");
    expect(firefly.skills.find((skill) => skill.name === "强化战技")?.toughness).toBe("30 / 相邻15");
    expect(firefly.skills.find((skill) => skill.name === "终结技·完全燃烧")?.extra).toContain("倒计时速度70");
    expect(firefly.traces.join(" ")).toContain("150%/300%");
    expect(firefly.traces.join(" ")).toContain("100%/150%自身超击破");
    expect(firefly.eidolons[1]).toContain("每个萨姆自身回合最多触发1次");
    expect(FIREFLY_CORE_LIGHT_CONES.firefly[0].effect).toContain("击破特攻+60%");
    expect(FIREFLY_CORE_LIGHT_CONES.firefly[0].effect).toContain("击破伤害+24%");
    expect(FIREFLY_CORE_LIGHT_CONES.firefly[0].effect).toContain("速度-20%");
  });

  it("keeps exact follow-up and technique values instead of vague placeholders", () => {
    const dahliaTalent = FIREFLY_CORE_CHARACTER_DATA.dahlia.skills.find((skill) => skill.name === "天赋");
    expect(dahliaTalent?.energy).toContain("追加攻击+2");
    expect(dahliaTalent?.toughness).toContain("每段3");
    expect(FIREFLY_CORE_CHARACTER_DATA.dahlia.skills.find((skill) => skill.name === "秘技")?.value).toContain("20秒");

    const lingshaTalent = FIREFLY_CORE_CHARACTER_DATA.lingsha.skills.find((skill) => skill.name === "天赋·浮元");
    expect(lingshaTalent?.toughness).toBe("群体10；随机追加目标再+10");
    expect(FIREFLY_CORE_CHARACTER_DATA.lingsha.skills.find((skill) => skill.name === "秘技")?.extra).toContain("醺醉2回合");
  });

  it("locks exact core light-cone values used by the lesson", () => {
    expect(FIREFLY_CORE_LIGHT_CONES.dahlia[0].effect).toContain("击破伤害+32%");
    expect(FIREFLY_CORE_LIGHT_CONES.dahlia[0].effect).toContain("恢复1战技点");
    expect(FIREFLY_CORE_LIGHT_CONES.fugue[0].effect).toContain("受到的击破伤害+18%");
    expect(FIREFLY_CORE_LIGHT_CONES.fugue[0].effect).toContain("可叠2层");
    expect(FIREFLY_CORE_LIGHT_CONES.lingsha[0].effect).toContain("受到的伤害+10%");
    expect(FIREFLY_CORE_LIGHT_CONES.lingsha[0].effect).toContain("额外+8%");
    expect(FIREFLY_CORE_LIGHT_CONES.gallagher[0].effect).toContain("击破特攻+48%");
    expect(FIREFLY_CORE_LIGHT_CONES.gallagher[0].effect).toContain("4%生命上限+800");
  });

  it("renders exact skill, eidolon, technique, and light-cone values for every core character", () => {
    const { container } = render(<FireflyCoreDataArchive />);
    const scope = within(container);

    expect(container.textContent).toContain("240上限时=144");
    expect(container.textContent).toContain("空中移动5秒");
    fireEvent.click(scope.getByText("核心光锥精确数值"));
    expect(container.textContent).toContain("梦应归于何处");
    expect(container.textContent).toContain("击破伤害+24%");

    fireEvent.click(scope.getByRole("button", { name: "大丽花" }));
    expect(container.textContent).toContain("防御-18%");
    expect(container.textContent).toContain("每段3；5段随机分配");
    expect(container.textContent).toContain("持续20秒");
    expect(container.textContent).toContain("最低10、最高300");
    fireEvent.click(scope.getByText("核心光锥精确数值"));
    expect(container.textContent).toContain("勿忘她的火焰");
    expect(container.textContent).toContain("击破伤害+32%");

    fireEvent.click(scope.getByRole("button", { name: "忘归人" }));
    expect(container.textContent).toContain("云火昭=原最大韧性40%");
    expect(container.textContent).toContain("全队行动提前24%");
    fireEvent.click(scope.getByText("核心光锥精确数值"));
    expect(container.textContent).toContain("长路终有归途");
    expect(container.textContent).toContain("可叠2层");

    fireEvent.click(scope.getByRole("button", { name: "灵砂" }));
    expect(container.textContent).toContain("14%攻击力+420");
    expect(container.textContent).toContain("随机追加目标再+10");
    expect(container.textContent).toContain("立即召唤浮元");
    expect(container.textContent).toContain("全属性抗性-20%");
    fireEvent.click(scope.getByText("核心光锥精确数值"));
    expect(container.textContent).toContain("唯有香如故");
    expect(container.textContent).toContain("额外+8%");

    fireEvent.click(scope.getByRole("button", { name: "加拉赫" }));
    expect(container.textContent).toContain("固定治疗1600生命");
    expect(container.textContent).toContain("入战50%攻击力群伤");
    expect(container.textContent).toContain("弱点击破效率+20%");
    fireEvent.click(scope.getByText("核心光锥精确数值"));
    expect(container.textContent).toContain("何物为真");
    expect(container.textContent).toContain("4%生命上限+800");
  });

  it("keeps route-only supports explicitly out of complete-data scope", () => {
    expect(Object.keys(FIREFLY_ROUTE_SUPPORT_SCOPE)).toEqual(["同谐主", "艾丝妲", "阮·梅"]);
    expect(FIREFLY_ROUTE_SUPPORT_SCOPE["同谐主"]).toContain("未提供其完整技能/星魂数据库");
    expect(FIREFLY_ROUTE_SUPPORT_SCOPE["艾丝妲"]).toContain("未提供完整技能/星魂数据库");
    expect(FIREFLY_ROUTE_SUPPORT_SCOPE["阮·梅"]).toContain("未提供完整技能/星魂数据库");
  });
});
