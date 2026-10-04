// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { render, within } from "@testing-library/react";
import { useMemo, useState } from "react";
import { describe, expect, it } from "vitest";

import { FireflyLessonProvider } from "./FireflyLessonContext";
import { LearningStrip } from "./LearningStrip";
import {
  createDefaultFireflyLessonState,
  type FireflyLessonState,
} from "./defaultFireflyLesson";

function DoupoStripHarness() {
  const [state, setState] = useState<FireflyLessonState>(() => ({
    ...createDefaultFireflyLessonState(),
    lessonKind: "doupo",
  }));
  const controller = useMemo(
    () => ({
      state,
      update: (patch: Partial<FireflyLessonState>) =>
        setState((current) => ({ ...current, ...patch })),
      reset: () => setState(createDefaultFireflyLessonState()),
    }),
    [state],
  );
  return (
    <FireflyLessonProvider controller={controller}>
      <LearningStrip
        resume={null}
        resumeError=""
        lastChat={null}
        visitedPhases={[]}
        memoryStatus={null}
      />
    </FireflyLessonProvider>
  );
}

describe("LearningStrip Doupo delight-loop entry", () => {
  it("summarizes the active analysis instead of presenting it as a course or gate audit", () => {
    const { container } = render(<DoupoStripHarness />);
    const toggle = within(container).getByRole("button", {
      name: /《斗破苍穹》爽点循环/,
    });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(container.textContent).toContain("4组样本 · 10张结构卡");
    expect(container.textContent).toContain("认知债 · 估值滞后 · 身份并账");
    expect(container.textContent).toContain("旧账 → 兑现 → 新债");
    expect(container.textContent).not.toContain("重新估值七门");
  });
});
