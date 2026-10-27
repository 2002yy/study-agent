import { describe, expect, it } from "vitest";

import defaultConfig from "../playwright.config";
import realAcceptanceConfig from "../playwright.real-acceptance.config";
import realStackConfig from "../playwright.real-stack.config";

/**
 * The paid, real-model acceptance runs boot the real backend and the configured
 * provider. They must stay out of the default browser gate: that gate has no
 * backend, and a pull request must never be able to spend money by running the
 * test suite. `playwright.real-acceptance.config.ts` is the only entry point
 * that collects them, and it is run explicitly.
 *
 * The real-stack specs have a smaller version of the same requirement: they
 * need a live backend on 127.0.0.1:8000. The default gate routes its API calls,
 * so collecting one of them there fails on a refused connection, not on the
 * product - which is exactly what happened when `api-token-required.spec.ts`
 * was added without this guard.
 */
const PAID_SPEC = "**/real-acceptance.spec.ts";

function patterns(value: unknown): string[] {
  if (value === undefined || value === null) return [];
  return (Array.isArray(value) ? value : [value]).map(String);
}

function basename(pattern: string): string {
  return pattern.split("/").pop() ?? pattern;
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

  it("keeps every real-stack spec out of the default suite", () => {
    const specs = patterns(realStackConfig.testMatch).map(basename);
    expect(specs.length).toBeGreaterThan(0);
    const defaultIgnores = patterns(defaultConfig.testIgnore).map(basename);
    for (const spec of specs) {
      expect(defaultIgnores, `default suite must ignore ${spec}`).toContain(spec);
      for (const project of defaultConfig.projects ?? []) {
        expect(
          patterns(project.testIgnore).map(basename),
          `project ${project.name} must ignore ${spec}`,
        ).toContain(spec);
      }
    }
  });

  it("still collects the token journey through the real-stack config", () => {
    expect(patterns(realStackConfig.testMatch)).toContain("api-token-required.spec.ts");
  });
});
