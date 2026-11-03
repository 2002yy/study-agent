import { expect, test } from "@playwright/test";

import { TASK_SPECS, judge, type Observation } from "../../src/acceptance/model";
import { j01Phase } from "./adapters";
import * as fixtures from "./fixtures";
import { capture, watchErrors, type ErrorCapture, type RawEvidence } from "./observer";

const j01 = TASK_SPECS.find(spec => spec.id === "J01")!;
const m02 = TASK_SPECS.find(spec => spec.id === "M02")!;
const a02 = TASK_SPECS.find(spec => spec.id === "A02")!;

function asObservation(evidence: RawEvidence, errors: ErrorCapture): Observation {
  return {
    phases: { reassigned: j01Phase(evidence, evidence.text) },
    consoleErrors: errors.consoleErrors,
    pageErrors: errors.pageErrors,
    fontSizes: evidence.fontSizes,
    controlSizes: evidence.controlSizes,
    horizontalOverflow: evidence.horizontalOverflow,
  };
}

async function run(page: Parameters<typeof capture>[0], html: string) {
  const errors = watchErrors(page);
  await page.setContent(html, { waitUntil: "load" });
  const evidence = await capture(page);
  return { evidence, observation: asObservation(evidence, errors) };
}

function result(observation: Observation, checkId: string, spec = j01) {
  return judge(spec, observation).find(item => item.checkId === checkId);
}

test("measures a real page and passes the geometry it can verify", async ({ page }) => {
  const { observation } = await run(page, fixtures.J01_CORRECT);

  expect(result(observation, "runtime")?.status).toBe("pass");
  expect(result(observation, "arrow-points-at-its-object")?.status).toBe("pass");
  expect(result(observation, "evidence-consistent")?.status).toBe("pass");
});

test("detects an arrow that does not reach its object", async ({ page }) => {
  const { observation } = await run(page, fixtures.J01_WRONG_ARROW);

  expect(result(observation, "arrow-points-at-its-object")?.status).toBe("fail");
});

test("detects a page whose printed numbers disagree with its picture", async ({ page }) => {
  const { observation } = await run(page, fixtures.J01_PICTURE_LIES);

  // The declared counts are the correct ones, so only the cross-check can catch it.
  expect(result(observation, "reassigned-objects")?.status).toBe("pass");
  expect(result(observation, "evidence-consistent")?.status).toBe("fail");
});

test("reports a runtime error caught from the page", async ({ page }) => {
  const { observation } = await run(page, fixtures.RUNTIME_ERROR);

  expect(result(observation, "runtime")?.status).toBe("fail");
});

test("keeps numeric checks indeterminate when the page offers no evidence", async ({ page }) => {
  const { observation } = await run(page, fixtures.NO_EVIDENCE);

  expect(result(observation, "runtime")?.status).toBe("pass");
  expect(result(observation, "reassigned-objects")?.status).toBe("indeterminate");
  expect(result(observation, "arrow-points-at-its-object")?.status).toBe("indeterminate");
});

test("detects a too-small font measured from the page", async ({ page }) => {
  const { observation } = await run(page, fixtures.TINY_FONT);

  expect(result(observation, "readable", m02)?.status).toBe("fail");
});

test("detects horizontal overflow measured from the page", async ({ page }) => {
  const { observation } = await run(page, fixtures.OVERFLOW);

  expect(result(observation, "no-overflow", a02)?.status).toBe("fail");
});
