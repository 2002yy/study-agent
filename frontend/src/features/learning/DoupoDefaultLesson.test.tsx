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
  fireEvent.click(within(container).getByRole("tab", { name: "斗破叙事" }));
}

function cardByHeading(container: HTMLElement, name: RegExp) {
  const heading = within(container).getByRole("heading", { name });
  const card = heading.closest("article");
  if (!card) {
    throw new Error(`card not found for ${String(name)}`);
  }
  return card;
}

describe("Doupo default lesson", () => {
  it("switches from the Firefly example to ten Doupo narrative cards", () => {
    const { container } = render(<Harness />);
    openDoupo(container);
    expect(container.querySelectorAll(".firefly-card")).toHaveLength(10);
    expect(container.textContent).toContain("长篇小说为什么会让你爽");
    expect(container.textContent).toContain("先判断，再看证据，再修正模型");
    expect(container.textContent).toContain("人物知识状态 · 先预测再对照");
    expect(container.textContent).toContain("社会估值曲线 · 看见“价值领先、认知滞后”");
    expect(container.textContent).toContain("身份合并");
    expect(container.textContent).toContain("重新估值七门");
  });

  it("does not spoil the false-ending evidence before the learner predicts and reveals", () => {
    const { container } = render(<Harness />);
    openDoupo(container);
    const card = cardByHeading(container, /炸炉.*为什么不是再来一次失败/);
    fireEvent.click(within(card).getByRole("button", { name: "展开" }));

    expect(card.textContent).not.toContain("三纹青灵丹仍然存在");
    expect(card.textContent).not.toContain("七名专业人物继续检查");

    fireEvent.click(
      within(card).getByRole("button", { name: /按现有公开证据.*炎利几乎锁定冠军/ }),
    );
    expect(card.textContent).not.toContain("三纹青灵丹仍然存在");

    fireEvent.click(
      within(card).getByRole("button", { name: "查看证据链，再修正判断" }),
    );
    expect(card.textContent).toContain("三纹青灵丹仍然存在");
    expect(card.textContent).toContain("七名专业人物继续检查");
    expect(card.textContent).toContain("信息遮蔽 → 公共错误共识 → 实物证据 → 专家审计");
  });

  it("turns the moral-settlement card into a judgment before revealing the model", () => {
    const { container } = render(<Harness />);
    openDoupo(container);
    const card = cardByHeading(container, /三年之约到底在结什么账/);
    fireEvent.click(within(card).getByRole("button", { name: "展开" }));

    expect(card.textContent).not.toContain("三年之约偿还的是公开处理方式与尊严债");
    fireEvent.click(
      within(card).getByRole("button", { name: /借宗门权力公开处理婚约.*萧家尊严/ }),
    );
    fireEvent.click(
      within(card).getByRole("button", { name: "查看证据链，再修正判断" }),
    );
    expect(card.textContent).toContain("三年之约偿还的是公开处理方式与尊严债");
    expect(card.textContent).toContain("拒绝把旧债升级成新支配");
  });

  it("lets the learner predict a knowledge cell before comparing with the evidence ledger", () => {
    const { container } = render(<Harness />);
    openDoupo(container);
    const guess = within(container).getByRole("button", {
      name: "纳兰嫣然：岩枭就是萧炎",
    });
    expect(guess).toHaveTextContent("未判断");
    fireEvent.click(guess);
    expect(guess).toHaveTextContent("不知道");
    fireEvent.click(
      within(container).getByRole("button", { name: "对照证据账本" }),
    );
    expect(guess).toHaveTextContent("证据账本：不知道");
    expect(guess).toHaveClass("is-match");
  });

  it("renders five full valuation series across the seven narrative checkpoints", () => {
    const { container } = render(<Harness />);
    openDoupo(container);
    expect(container.querySelectorAll(".doupo-valuation-line")).toHaveLength(5);
    const chart = within(container).getByRole("img", {
      name: "五条社会估值随时间变化的教学曲线",
    });
    expect(chart.textContent).toContain("退婚");
    expect(chart.textContent).toContain("家族测试");
    expect(chart.textContent).toContain("身份合并");
    expect(chart.textContent).toContain("结算");

    fireEvent.click(
      within(container).getByRole("button", { name: "第337章·身份合并" }),
    );
    expect(container.textContent).toContain("当前教学估值差");
    expect(container.textContent).toContain("不是原文提供的数值");
  });

  it("executes the identity merge instead of showing a static explanation", () => {
    const { container } = render(<Harness />);
    openDoupo(container);
    fireEvent.click(
      within(container).getByRole("button", { name: "执行：萧炎 === 岩枭" }),
    );
    expect(container.textContent).toContain("此前认可的炼药天才");
    expect(container.textContent).toContain("沙漠中此前解释不通的事件重新串起来");
  });

  it("lets the learner break a repricing gate and see the diagnosis change", () => {
    const { container } = render(<Harness />);
    openDoupo(container);
    const moralGate = within(container).getByRole("button", {
      name: /G7.*结算保持对称.*通过/,
    });
    fireEvent.click(moralGate);
    expect(container.textContent).toContain("道德反转");
  });
});
