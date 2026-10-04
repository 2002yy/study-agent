import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

function readLocal(path: string) {
  return readFileSync(fileURLToPath(new URL(path, import.meta.url)), "utf8");
}

const lessonSource = readLocal("./FireflyMechanicsLesson.tsx");
const dataSource = readLocal("./fireflyCharacterData.ts");
const archiveSource = readLocal("./FireflyCoreDataArchive.tsx");
const panelSource = readLocal("./FireflyCharacterDataPanel.tsx");

describe("Firefly content completeness contract", () => {
  it("keeps the expanded lesson causal rather than summary-only", () => {
    expect(lessonSource).toContain("角色设定 / 玩法结构");
    expect(lessonSource).toContain("充能段 / 完全燃烧");
    expect(lessonSource).toContain("影响的资源");
    expect(lessonSource).toContain("环境差异");
    expect(lessonSource).toContain("新增能力");
    expect(lessonSource).toContain("仍有缺口 / 成本");
  });

  it("keeps all six damage-ledger tracks visible", () => {
    for (const heading of [
      "削韧：45 → 80 → 95 → 110",
      "超击破倍率：310% → 350%",
      "防御区",
      "抗性区",
      "击破易伤",
      "循环资源",
    ]) {
      expect(lessonSource).toContain(heading);
    }
  });

  it("includes explicit value-loss cases instead of only upgrade claims", () => {
    expect(lessonSource).toContain("收益会明显波动");
    expect(lessonSource).toContain("流萤2魂“击破”分支因此贬值");
    expect(lessonSource).toContain("低韧性目标可能出现削韧溢出");
  });

  it("keeps five core characters at complete numeric depth", () => {
    for (const name of ["流萤", "大丽花", "忘归人", "灵砂", "加拉赫"]) {
      expect(dataSource).toContain(`name: "${name}"`);
    }
    expect(dataSource).toContain("240上限时=144");
    expect(dataSource).toContain("防御-18%");
    expect(dataSource).toContain("云火昭=原最大韧性40%");
    expect(dataSource).toContain("14%攻击力+420");
    expect(dataSource).toContain("固定治疗1600生命");
    expect(archiveSource).toContain("核心角色数值档案");
    expect(panelSource).toContain("1～6魂精确效果");
  });

  it("keeps route supports explicitly scoped as partial data", () => {
    expect(dataSource).toContain('"同谐主"');
    expect(dataSource).toContain('"艾丝妲"');
    expect(dataSource).toContain('"阮·梅"');
    expect(dataSource).toContain("未提供其完整技能/星魂数据库");
  });
});
