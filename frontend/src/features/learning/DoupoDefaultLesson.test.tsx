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

function openDoupo(container: HTMLElement) {
  fireEvent.click(within(container).getByRole("tab", { name: "斗破爽点循环" }));
}

function cardByHeading(container: HTMLElement, name: RegExp) {
  const heading = within(container).getByRole("heading", { name });
  const card = heading.closest("article");
  if (!card) throw new Error(`card not found for ${String(name)}`);
  return card;
}

describe("Doupo delight-loop analysis", () => {
  it("switches to ten structure cards and exposes the four-sample loop analyzer", () => {
    const { container } = render(<Harness />);
    openDoupo(container);
    expect(container.querySelectorAll(".firefly-card")).toHaveLength(10);
    expect(container.textContent).toContain("《斗破苍穹》的爽点循环怎么转起来");
    expect(container.textContent).toContain("爽点循环总图 · 看一笔账怎么从欠下滚到下一轮");
    expect(container.textContent).toContain("人物认知差 · 同一事实不会同时到达所有人");
    expect(container.textContent).toContain("估值滞后曲线 · 真实价值先涨，社会价格后追");
    expect(container.textContent).toContain("双账户并账 · 看过去怎么被一起重算");
    expect(container.textContent).not.toContain("先判断，再看证据，再修正模型");
    expect(container.textContent).not.toContain("重新估值七门");
  });

  it("lets the reader move through a selected delight-loop stage without turning it into a quiz", () => {
    const { container } = render(<Harness />);
    openDoupo(container);
    fireEvent.click(
      within(container).getByRole("button", { name: "三年之约：多条价值线一次性并账" }),
    );
    fireEvent.click(
      within(container).getByRole("button", { name: /08.*回溯重构.*展开/ }),
    );
    expect(container.textContent).toContain("过去几百章一起升值");
    expect(container.textContent).toContain("炼药大会、异火、沙漠线索和三年前的选择");
  });

  it("opens the false-ending card as direct structural analysis", () => {
    const { container } = render(<Harness />);
    openDoupo(container);
    const card = cardByHeading(container, /假终局：让错误共识先成立/);
    fireEvent.click(within(card).getByRole("button", { name: "展开" }));
    expect(card.textContent).toContain("三纹青灵丹仍然存在");
    expect(card.textContent).toContain("七名专业人物继续检查");
    expect(card.textContent).toContain("信息遮蔽 → 公共错误共识 → 实物硬证据 → 专业审计");
  });

  it("shows knowledge state directly as plot information rather than asking the user to guess it", () => {
    const { container } = render(<Harness />);
    openDoupo(container);
    const table = container.querySelector(".doupo-knowledge-table");
    expect(table).not.toBeNull();
    expect(table?.textContent).toContain("纳兰嫣然");
    expect(table?.textContent).toContain("还不知道");
    expect(container.textContent).not.toContain("未判断");
    expect(container.textContent).not.toContain("对照证据账本");
  });

  it("renders five valuation series across the seven narrative checkpoints without calling them a teaching scale", () => {
    const { container } = render(<Harness />);
    openDoupo(container);
    expect(container.querySelectorAll(".doupo-valuation-line")).toHaveLength(5);
    const chart = within(container).getByRole("img", {
      name: "五条社会估值随剧情推进变化的结构示意曲线",
    });
    expect(chart.textContent).toContain("退婚");
    expect(chart.textContent).toContain("家族测试");
    expect(chart.textContent).toContain("身份合并");
    expect(chart.textContent).toContain("结算");
    expect(container.textContent).toContain("结构示意差");
    expect(container.textContent).not.toContain("教学估值");
  });

  it("merges the two identity accounts and surfaces retroactive repricing", () => {
    const { container } = render(<Harness />);
    openDoupo(container);
    fireEvent.click(
      within(container).getByRole("button", { name: "合并：萧炎 === 岩枭" }),
    );
    expect(container.textContent).toContain("此前认可的炼药天才");
    expect(container.textContent).toContain("沙漠中此前解释不通的事件重新串起来");
  });
});
