import { describe, expect, it } from "vitest";

import defaultConfig from "../playwright.config";
import realAcceptanceConfig from "../playwright.real-acceptance.config";

/**
 * The paid, real-model acceptance runs boot the real backend and the configured
 * provider. They must stay out of the default browser gate: that gate has no
 * backend, and a pull request must never be able to spend money by running the
 * test suite. `playwright.real-acceptance.config.ts` is the only entry point
 * that collects them, and it is run explicitly.
 */
const PAID_SPEC = "**/real-acceptance.spec.ts";

function patterns(value: unknown): string[] {
  if (value === undefined || value === null) return [];
  return (Array.isArray(value) ? value : [value]).map(String);
}

describe("playwright suite isolation", () => {
  it("keeps the paid acceptance spec out of the default suite", () => {
    expect(patterns(defaultConfig.testIgnore)).toContain(PAID_SPEC);
  });

  it("keeps every default project out of it too", () => {
    // A project-level testIgnore replaces the top-level one, so one project left
    // on the smaller list would silently collect the paid spec again.
    expect(defaultConfig.projects?.length ?? 0).toBeGreaterThan(0);
    for (const project of defaultConfig.projects ?? []) {
      expect(
        patterns(project.testIgnore),
        `project ${project.name} must ignore ${PAID_SPEC}`,
      ).toContain(PAID_SPEC);
    }
  });

  it("still collects the paid spec through its own config", () => {
    expect(patterns(realAcceptanceConfig.testMatch)).toContain("real-acceptance.spec.ts");
  });
});
