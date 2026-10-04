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

function OneGoldHarness() {
  const base = createDefaultFireflyLessonState();
  const [state, setState] = useState<FireflyLessonState>({
    ...base,
    bossToughness: 300,
    investment: "dahlia-1",
    painPoint: "break-slow",
    oneGold: {
      ...base.oneGold,
      fireflyEidolon: 2,
      dahliaEidolon: 0,
    },
  });
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

describe("Firefly one-gold boss integration", () => {
  it("reuses the current boss experiment instead of a frozen 1200-toughness example", () => {
    const { container } = render(<OneGoldHarness />);

    expect(container.textContent).toContain("300韧性简化模型从4发缩到3发");
    expect(container.textContent).not.toContain("1200韧性简化模型从15发缩到12发");

    fireEvent.click(within(container).getByRole("button", { name: "600韧性" }));
    expect(container.textContent).toContain("600韧性简化模型从8发缩到6发");
  });

  it("stops comparing attack counts when the current boss is toughness-locked", () => {
    const { container } = render(<OneGoldHarness />);

    fireEvent.click(within(container).getByRole("button", { name: "锁韧" }));
    expect(container.textContent).toContain("当前首领处于锁韧状态，不用攻击次数评价1魂");
    expect(container.textContent).toContain("当前首领实验：锁韧 / +大丽花1魂 / 不比较攻击次数");
  });
});
