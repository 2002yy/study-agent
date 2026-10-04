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

function DefaultLessonStripHarness() {
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

describe("LearningStrip Firefly default entry", () => {
  it("opens the researched Firefly example by default on an empty workspace", () => {
    const { container } = render(<DefaultLessonStripHarness />);
    const toggle = within(container).getByRole("button", {
      name: /流萤超击破体系/,
    });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(container.textContent).toContain("默认示例 · 10张机制卡");
    expect(container.textContent).toContain("换一条韧性，再算一次");
    expect(container.textContent).toContain("手里只有一金");
  });
});
