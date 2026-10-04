// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, within } from "@testing-library/react";
import { useMemo, useState } from "react";
import { describe, expect, it } from "vitest";

import { FireflyDefaultLesson } from "./FireflyDefaultLesson";
import {
  createDefaultFireflyLessonState,
  type FireflyLessonState,
} from "./defaultFireflyLesson";

function Harness() {
  const [state, setState] = useState<FireflyLessonState>(
    createDefaultFireflyLessonState,
  );
  const controller = useMemo(
    () => ({
      state,
      update: (patch: Partial<FireflyLessonState>) =>
        setState((current) => ({ ...current, ...patch })),
      reset: () => setState(createDefaultFireflyLessonState()),
    }),
    [state],
  );
  return <FireflyDefaultLesson controller={controller} />;
}

describe("FireflyDefaultLesson", () => {
  it("renders ten compact content cards and the two independent interactions", () => {
    const { container } = render(<Harness />);
    expect(within(container).getAllByRole("article")).toHaveLength(10);
    expect(within(container).getByText("换一条韧性，再算一次")).toBeInTheDocument();
    expect(within(container).getByText("手里只有一金")).toBeInTheDocument();
    expect(container.textContent).toContain("12次强化战技");
    expect(
      within(container).queryByRole("button", { name: "暂时收起默认示例" }),
    ).toBeNull();
  });

  it("keeps only one large content card expanded", () => {
    const { container } = render(<Harness />);
    const buttons = within(container).getAllByRole("button", { name: "展开" });
    fireEvent.click(buttons[0]);
    expect(container.querySelectorAll('.firefly-card [aria-expanded="true"]')).toHaveLength(1);
    expect(container.textContent).toContain("完全燃烧的行动窗口");

    const nextExpand = within(container).getAllByRole("button", { name: "展开" })[0];
    fireEvent.click(nextExpand);
    expect(container.querySelectorAll('.firefly-card [aria-expanded="true"]')).toHaveLength(1);
  });

  it("keeps character premise and gameplay interpretation distinct", () => {
    const { container } = render(<Harness />);
    const firstCard = within(container).getAllByRole("article")[0];
    fireEvent.click(within(firstCard).getByRole("button", { name: "展开" }));
    const text = firstCard.textContent ?? "";
    expect(text).toContain("角色设定 / 玩法结构");
    expect(text).toContain("玩法设计解读");
    expect(text).toContain("星核猎手与匹诺康尼人物线");
    expect(text).toContain("窗口里能塞进几次强化攻击");
  });

  it("shows why an eidolon changes value across environments without a fixed ranking", () => {
    const { container } = render(<Harness />);
    const eidolonCard = within(container).getAllByRole("article")[3];
    fireEvent.click(within(eidolonCard).getByRole("button", { name: "展开" }));
    const text = eidolonCard.textContent ?? "";
    expect(text).toContain("影响的资源");
    expect(text).toContain("环境差异");
    expect(text).toContain("长时间锁韧");
    expect(text).toContain("收益会明显波动");
  });

  it("keeps Lingsha eidolons and light-cone details available behind expansion", () => {
    const { container } = render(<Harness />);
    const cards = within(container).getAllByRole("article");
    const sustainCard = cards[6];
    fireEvent.click(within(sustainCard).getByRole("button", { name: "展开" }));
    const text = sustainCard.textContent ?? "";
    expect(text).toContain("3魂：终结技+2、天赋+2");
    expect(text).toContain("6魂：浮元在场时全体敌人全属性抗性-20%");
    expect(text).toContain("等价交换·叠影5：给低能量队友恢复能量");
    expect(text).toContain("只比较治疗量会漏掉大半差异");
  });

  it("makes team routes state added capability and remaining tradeoff", () => {
    const { container } = render(<Harness />);
    const teamCard = within(container).getAllByRole("article")[7];
    fireEvent.click(within(teamCard).getByRole("button", { name: "展开" }));
    expect(teamCard.textContent).toContain("新增能力");
    expect(teamCard.textContent).toContain("仍有缺口 / 成本");
    fireEvent.click(within(teamCard).getByRole("button", { name: "高配" }));
    expect(teamCard.textContent).toContain("四个位置把破韧前、第一次击破、第二次击破和生存/副削韧接在一起");
    expect(teamCard.textContent).toContain("低韧性目标可能出现削韧溢出");
  });

  it("keeps the full damage ledger as separate causal tracks", () => {
    const { container } = render(<Harness />);
    const ledgerCard = within(container).getAllByRole("article")[8];
    fireEvent.click(within(ledgerCard).getByRole("button", { name: "展开" }));
    const text = ledgerCard.textContent ?? "";
    expect(text).toContain("削韧：45 → 80 → 95 → 110");
    expect(text).toContain("超击破倍率：310% → 350%");
    expect(text).toContain("防御区");
    expect(text).toContain("抗性区");
    expect(text).toContain("击破易伤");
    expect(text).toContain("循环资源");
    expect(text).toContain("不能直接写成“总提升12.9%”");
  });

  it("shows environment-driven value changes instead of only listing winners", () => {
    const { container } = render(<Harness />);
    const environmentCard = within(container).getAllByRole("article")[9];
    fireEvent.click(within(environmentCard).getByRole("button", { name: "展开" }));
    const text = environmentCard.textContent ?? "";
    expect(text).toContain("环境变化后的价值");
    expect(text).toContain("流萤2魂“击破”分支因此贬值");
    expect(text).toContain("大丽花2魂让新敌自动进入败谢");
    fireEvent.click(within(environmentCard).getByRole("button", { name: "末日幻影" }));
    expect(environmentCard.textContent).toContain("首领机制、韧性与弱点击破事件更重要");
  });

  it("does not fabricate an attack count while toughness is locked", () => {
    const { container } = render(<Harness />);
    fireEvent.click(within(container).getByRole("button", { name: "锁韧" }));
    expect(container.textContent).toContain("锁韧期间不报“需要几次攻击”");
    expect(container.textContent).toContain("大丽花领域允许超击破✓");
  });

  it("exposes the calculation instead of presenting the simplified result as a simulator", () => {
    const { container } = render(<Harness />);
    fireEvent.click(within(container).getByRole("button", { name: "看怎么算的" }));
    expect(container.textContent).toContain("30×2.0 + 20 = 80");
    expect(container.textContent).toContain("min(25%×最大韧性, 300)");
  });
});
