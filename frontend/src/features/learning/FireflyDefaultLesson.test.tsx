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
    expect(container.textContent).toContain("粗略裸轴");

    const nextExpand = within(container).getAllByRole("button", { name: "展开" })[0];
    fireEvent.click(nextExpand);
    expect(container.querySelectorAll('.firefly-card [aria-expanded="true"]')).toHaveLength(1);
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
