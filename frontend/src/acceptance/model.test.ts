import { describe, expect, it } from "vitest";

import { correctObservation } from "./fixtures";
import { FAULTS } from "./faults";
import { TASK_SPECS, judge, summarize } from "./model";

describe("frozen M4-C acceptance model", () => {
  it("freezes twelve tasks across eight domains", () => {
    expect(TASK_SPECS).toHaveLength(12);
    expect(new Set(TASK_SPECS.map(spec => spec.domain)).size).toBeGreaterThanOrEqual(8);
  });

  it.each(TASK_SPECS.map(spec => [spec.id, spec] as const))(
    "passes a correct %s interface without a false alarm",
    (_id, spec) => {
      const summary = summarize(judge(spec, correctObservation(spec.id)));
      expect(summary.failed).toEqual([]);
      expect(summary.indeterminate).toEqual([]);
    }
  );

  it("carries twenty-four known faults: eight runtime, eight state, eight visual", () => {
    expect(FAULTS).toHaveLength(24);
    expect(FAULTS.filter(fault => fault.layer === "runtime")).toHaveLength(8);
    expect(FAULTS.filter(fault => fault.layer === "state")).toHaveLength(8);
    expect(
      FAULTS.filter(fault => fault.layer === "geometry" || fault.layer === "usability")
    ).toHaveLength(8);
  });

  it.each(FAULTS.map(fault => [fault.id, fault] as const))(
    "reports fault %s on its own check and layer",
    (_id, fault) => {
      const spec = TASK_SPECS.find(item => item.id === fault.taskId);
      expect(spec).toBeDefined();
      const results = judge(spec!, fault.apply(correctObservation(fault.taskId)));
      const target = results.find(result => result.checkId === fault.checkId);

      expect(target?.status).toBe("fail");
      expect(target?.layer).toBe(fault.layer);
      // A fault must not drag unrelated checks down with it.
      expect(summarize(results).failed.map(result => result.checkId)).toEqual([fault.checkId]);
    }
  );

  it("reports missing evidence as indeterminate instead of a pass", () => {
    const spec = TASK_SPECS.find(item => item.id === "M01")!;
    const observation = correctObservation("M01");
    delete observation.phases.x3.canvas;

    const result = judge(spec, observation).find(item => item.checkId === "chart-follows-x");

    expect(result?.status).toBe("indeterminate");
  });

  it("does not treat an empty observation as a pass", () => {
    const spec = TASK_SPECS.find(item => item.id === "D01")!;
    const empty = {
      phases: {},
      consoleErrors: [],
      pageErrors: [],
      fontSizes: [],
      controlSizes: [],
      horizontalOverflow: false,
    };

    const summary = summarize(judge(spec, empty));

    expect(summary.passed).toBe(1); // runtime only; nothing else has evidence
    expect(summary.indeterminate).toHaveLength(spec.checks.length - 1);
    expect(summary.failed).toEqual([]);
  });

  it("fails a non-finite declared value instead of passing it", () => {
    const spec = TASK_SPECS.find(item => item.id === "M01")!;
    const observation = correctObservation("M01");
    observation.phases.x3.declared.y = Number.NaN;

    const result = judge(spec, observation).find(item => item.checkId === "value-at-3");

    expect(result?.status).toBe("fail");
  });

  it("fails an infinite observed value in the evidence cross-check", () => {
    const spec = TASK_SPECS.find(item => item.id === "A02")!;
    const observation = correctObservation("A02");
    observation.phases.result.observed.distance = Number.POSITIVE_INFINITY;

    const result = judge(spec, observation).find(item => item.checkId === "evidence-consistent");

    expect(result?.status).toBe("fail");
  });

  it("fails when the page claims one value and the picture shows another", () => {
    const spec = TASK_SPECS.find(item => item.id === "A02")!;
    const observation = correctObservation("A02");
    observation.phases.result.observed.distance = 8;

    const result = judge(spec, observation).find(item => item.checkId === "evidence-consistent");

    expect(result?.status).toBe("fail");
    expect(result?.detail).toContain("不一致");
  });

  it("returns indeterminate when the independent evidence is missing", () => {
    const spec = TASK_SPECS.find(item => item.id === "J01")!;
    const observation = correctObservation("J01");
    delete observation.phases.reassigned.observed.objectOfB;

    const result = judge(spec, observation).find(item => item.checkId === "evidence-consistent");

    expect(result?.status).toBe("indeterminate");
  });

  it("fails an arrow whose coordinates are not finite", () => {
    const spec = TASK_SPECS.find(item => item.id === "J01")!;
    const observation = correctObservation("J01");
    const arrow = observation.phases.reassigned.svg?.find(shape => shape.id === "arrow-b");
    if (arrow?.to) arrow.to.x = Number.NaN;

    const result = judge(spec, observation).find(
      item => item.checkId === "arrow-points-at-its-object"
    );

    expect(result?.status).toBe("fail");
  });
});
