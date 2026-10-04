// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { render } from "@testing-library/react";
import { useMemo, useState } from "react";
import { describe, expect, it } from "vitest";

import { FireflyLessonProvider } from "./FireflyLessonContext";
import { LearningPanel } from "./LearningPanel";
import {
  createDefaultFireflyLessonState,
  type FireflyLessonState,
} from "./defaultFireflyLesson";
import type { LearningResumeResponse } from "./learningResumeApi";

function BoundaryHarness({ resume }: { resume: LearningResumeResponse | null }) {
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
      <LearningPanel
        resume={resume}
        resumeError=""
        lastChat={null}
        visitedPhases={[]}
        memoryStatus={null}
      />
    </FireflyLessonProvider>
  );
}

function durableResume(): LearningResumeResponse {
  return {
    source: "durable",
    status: "active",
    topic: { topic_id: "topic-durable", title: "真实学习主题" },
    goal: {
      goal_id: "goal-durable",
      topic_id: "topic-durable",
      objective: "真实 durable Goal 必须优先",
      status: "active",
    },
    claims: [
      {
        claim_id: "claim-durable",
        revision_id: "rev-durable",
        text: "真实 durable Claim 不得被默认示例覆盖",
        claim_kind: "invariant",
        scope: "default lesson authority boundary",
        understanding_status: "confirmed",
        validation_result: "pass",
        latest_validation: { method: "explain", result: "pass" },
        primary_evidence: {},
        supporting_evidence: [],
      },
    ],
    claim_count: 1,
    unresolved: [],
    next_step: { text: "继续真实学习", status: "active", is_primary: true },
    optional_next_steps: [],
  };
}

describe("Firefly default lesson authority boundary", () => {
  it("shows the default lesson when no durable active Goal owns the learning surface", () => {
    const { container } = render(<BoundaryHarness resume={null} />);
    expect(container.textContent).toContain("流萤超击破体系");
    expect(container.textContent).toContain("手里只有一金");
  });

  it("never overrides an active durable Goal or Claim", () => {
    const { container } = render(<BoundaryHarness resume={durableResume()} />);
    const text = container.textContent ?? "";
    expect(text).toContain("真实 durable Goal 必须优先");
    expect(text).toContain("真实 durable Claim 不得被默认示例覆盖");
    expect(text).not.toContain("手里只有一金");
  });
});