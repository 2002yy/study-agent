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

describe("LearningStrip Doupo default entry", () => {
  it("summarizes the active narrative example instead of leaving the Firefly label behind", () => {
    const { container } = render(<DoupoStripHarness />);
    const toggle = within(container).getByRole("button", {
      name: /《斗破苍穹》认知翻转/,
    });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(container.textContent).toContain("默认示例 · 10张叙事卡");
    expect(container.textContent).toContain("人物知识 · 估值曲线 · 身份合并");
    expect(container.textContent).toContain("重新估值七门");
  });
});
