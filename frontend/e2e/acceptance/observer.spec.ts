import { expect, test } from "@playwright/test";

import { TASK_SPECS, judge, type Observation, type Phase } from "../../src/acceptance/model";
import { canvasPhase, j01Phase } from "./adapters";
import * as fixtures from "./fixtures";
import { capture, watchErrors, type ErrorCapture, type RawEvidence } from "./observer";

const j01 = TASK_SPECS.find(spec => spec.id === "J01")!;
const m02 = TASK_SPECS.find(spec => spec.id === "M02")!;
const a02 = TASK_SPECS.find(spec => spec.id === "A02")!;
const m01 = TASK_SPECS.find(spec => spec.id === "M01")!;
const p01 = TASK_SPECS.find(spec => spec.id === "P01")!;

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

async function canvasObservation(
  page: Parameters<typeof capture>[0],
  phases: Record<string, Phase>,
  errors: ErrorCapture,
  basis: RawEvidence
): Promise<Observation> {
  return {
    phases,
    consoleErrors: errors.consoleErrors,
    pageErrors: errors.pageErrors,
    fontSizes: basis.fontSizes,
    controlSizes: basis.controlSizes,
    horizontalOverflow: basis.horizontalOverflow,
  };
}

test("sees a canvas animate and then hold still when paused", async ({ page }) => {
  const errors = watchErrors(page);
  await page.setContent(fixtures.P01_ANIMATED, { waitUntil: "load" });
  await page.waitForTimeout(150);

  const phases: Record<string, Phase> = {};
  phases["phase-zero"] = canvasPhase(await capture(page), "");
  await page.waitForTimeout(250);
  phases["pi-half"] = canvasPhase(await capture(page), "");

  await page.getByRole("button", { name: "暂停" }).click();
  await page.waitForTimeout(120);
  const basis = await capture(page);
  phases["paused-a"] = canvasPhase(basis, basis.text);
  await page.waitForTimeout(400);
  phases["paused-b"] = canvasPhase(await capture(page), "");

  const observation = await canvasObservation(page, phases, errors, basis);

  expect(result(observation, "motion-visible", p01)?.status).toBe("pass");
  expect(result(observation, "paused", p01)?.status).toBe("pass");
});

test("reports a canvas that keeps moving after pause", async ({ page }) => {
  const errors = watchErrors(page);
  await page.setContent(fixtures.P01_IGNORES_PAUSE, { waitUntil: "load" });
  await page.waitForTimeout(150);

  const phases: Record<string, Phase> = {};
  await page.getByRole("button", { name: "暂停" }).click();
  const basis = await capture(page);
  phases["paused-a"] = canvasPhase(basis, basis.text);
  await page.waitForTimeout(400);
  phases["paused-b"] = canvasPhase(await capture(page), "");

  const observation = await canvasObservation(page, phases, errors, basis);

  expect(result(observation, "paused", p01)?.status).toBe("fail");
});

test("sees a canvas follow the input", async ({ page }) => {
  const errors = watchErrors(page);
  await page.setContent(fixtures.M01_CANVAS, { waitUntil: "load" });

  const phases: Record<string, Phase> = {};
  const basis = await capture(page);
  phases["x3"] = canvasPhase(basis, basis.text);
  await page.locator("input[data-x]").evaluate(element => {
    const input = element as HTMLInputElement;
    input.value = "-1";
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await page.waitForTimeout(60);
  phases["xminus1"] = canvasPhase(await capture(page), "");

  const observation = await canvasObservation(page, phases, errors, basis);

  expect(result(observation, "chart-follows-x", m01)?.status).toBe("pass");
});

test("reports a canvas that never redraws", async ({ page }) => {
  const errors = watchErrors(page);
  await page.setContent(fixtures.M01_FROZEN_CANVAS, { waitUntil: "load" });

  const phases: Record<string, Phase> = {};
  const basis = await capture(page);
  phases["x3"] = canvasPhase(basis, basis.text);
  await page.locator("input[data-x]").evaluate(element => {
    const input = element as HTMLInputElement;
    input.value = "-1";
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await page.waitForTimeout(60);
  phases["xminus1"] = canvasPhase(await capture(page), "");

  const observation = await canvasObservation(page, phases, errors, basis);

  expect(result(observation, "chart-follows-x", m01)?.status).toBe("fail");
});
