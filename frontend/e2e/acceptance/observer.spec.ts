import { expect, test } from "@playwright/test";

import { TASK_SPECS, judge, judgeUsability, summarize, type Observation, type Phase } from "../../src/acceptance/model";
import { canvasPhase, declaredAmplitude, j01Phase, positionFromCanvas } from "./adapters";
import * as fixtures from "./fixtures";
import { HTML_FAULTS, type HtmlFault } from "./htmlFaults";
import { capture, watchErrors, type ErrorCapture, type RawEvidence } from "./observer";
import {
  observeFault,
  observeJ01Steps,
  observeM01,
  observeP01,
  observeP01Fault,
  observePhases,
  observationOf,
} from "./taskObservers";

const j01 = TASK_SPECS.find(spec => spec.id === "J01")!;
const m02 = TASK_SPECS.find(spec => spec.id === "M02")!;
const a02 = TASK_SPECS.find(spec => spec.id === "A02")!;
const m01 = TASK_SPECS.find(spec => spec.id === "M01")!;
const p01 = TASK_SPECS.find(spec => spec.id === "P01")!;

for (const label of ["<svg width='150' height='60'><text x='5' y='25' style='font-size:10px'>small</text></svg>",
  "<small style='font-size:10px'>small</small>", "<pre style='font-size:10px'>small</pre>",
  "<code style='font-size:10px'>small</code>"]) {
  test(`measures small visible text: ${label.slice(0, 6)}`, async ({ page }) => {
    const errors = watchErrors(page);
    await page.setContent(`<body style='font-size:16px'><div>${label}</div><button style='font-size:16px'>ok</button></body>`);
    const evidence = await capture(page);
    expect(judgeUsability(observationOf({}, errors, evidence)).find(check => check.checkId === "usability-font")?.status).toBe("fail");
  });
}

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

/** Read both J01 steps from one document: shared first, then re-pointed. */
async function runJ01Steps(
  page: Parameters<typeof capture>[0],
  html: string
): Promise<Observation> {
  const errors = watchErrors(page);
  await page.setContent(html, { waitUntil: "load" });
  return observeJ01Steps(page, errors);
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

  // Correct printed claims cannot override the independently drawn identities.
  expect(result(observation, "reassigned-objects")?.status).toBe("fail");
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

test("applies the universal usability gate to every document", async ({ page }) => {
  const errors = watchErrors(page);
  const cases = [
    [fixtures.TINY_FONT, "usability-font"],
    [fixtures.SMALL_CONTROL, "usability-control"],
    [fixtures.OVERFLOW, "usability-overflow"],
  ] as const;

  for (const [html, checkId] of cases) {
    await page.setContent(html, { waitUntil: "load" });
    const observation = observationOf({}, errors, await capture(page));
    const check = judgeUsability(observation).find(item => item.checkId === checkId);
    expect(check?.status, checkId).toBe("fail");
  }
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

  const observation = await observationOf(phases, errors, basis);

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

  const observation = await observationOf(phases, errors, basis);

  expect(result(observation, "paused", p01)?.status).toBe("fail");
});

test("maps a canvas marker to task units and confirms the declared position", async ({ page }) => {
  const observation = await runP01Calibrated(page, fixtures.P01_STEPPED);

  expect(summarize(judge(p01, observation)).indeterminate).toEqual([]);
  expect(result(observation, "position-at-zero", p01)?.status).toBe("pass");
  expect(result(observation, "position-at-phases", p01)?.status).toBe("pass");
  expect(result(observation, "position-at-pi", p01)?.status).toBe("pass");
  expect(result(observation, "evidence-consistent-zero", p01)?.status).toBe("pass");
  expect(result(observation, "evidence-consistent", p01)?.status).toBe("pass");
  expect(result(observation, "evidence-consistent-pi", p01)?.status).toBe("pass");
  expect(result(observation, "motion-visible", p01)?.status).toBe("pass");
  expect(result(observation, "paused", p01)?.status).toBe("pass");
});

test("catches a marker that only reaches half of the declared position", async ({ page }) => {
  const observation = await runP01Calibrated(page, fixtures.P01_STEPPED_LIES);

  expect(result(observation, "position-at-zero", p01)?.status).toBe("pass");
  expect(result(observation, "position-at-phases", p01)?.status).toBe("fail");
  expect(result(observation, "evidence-consistent", p01)?.status).toBe("fail");
});

test("checks the pi phase independently instead of only pi/2", async ({ page }) => {
  const observation = await runP01Calibrated(page, fixtures.P01_STEPPED_PI_LIES);

  expect(result(observation, "position-at-zero", p01)?.status).toBe("pass");
  expect(result(observation, "position-at-phases", p01)?.status).toBe("pass");
  expect(result(observation, "position-at-pi", p01)?.status).toBe("fail");
  expect(result(observation, "evidence-consistent-pi", p01)?.status).toBe("fail");
});

for (const [name, html] of [
  ["two competing amplitude scales", fixtures.P01_AMBIGUOUS_MARKS],
  ["a dominant colour that is not the moving marker", fixtures.P01_BIG_BLOCK],
] as const) {
  test(`keeps position indeterminate with ${name}`, async ({ page }) => {
    const observation = await runP01Calibrated(page, html);

    expect(result(observation, "position-at-zero", p01)?.status).toBe("indeterminate");
    expect(result(observation, "position-at-phases", p01)?.status).toBe("indeterminate");
    expect(result(observation, "position-at-pi", p01)?.status).toBe("indeterminate");
    expect(result(observation, "evidence-consistent", p01)?.status).toBe("indeterminate");
  });
}

test("keeps the position open when the page draws no amplitude marks", async ({ page }) => {
  const errors = watchErrors(page);
  await page.setContent(fixtures.P01_ANIMATED, { waitUntil: "load" });
  await page.waitForTimeout(120);

  const phases: Record<string, Phase> = {};
  const zero = await capture(page);
  phases["phase-zero"] = canvasPhase(zero, zero.text);
  await page.waitForTimeout(220);
  const half = await capture(page);
  const measured = positionFromCanvas(
    phases["phase-zero"],
    canvasPhase(half, half.text),
    declaredAmplitude(half.text)
  );
  if (measured) phases["pi-half"] = measured;

  const observation = await observationOf(phases, errors, half);

  expect(result(observation, "position-at-phases", p01)?.status).toBe("indeterminate");
  expect(result(observation, "evidence-consistent", p01)?.status).toBe("indeterminate");
});

test("sees a canvas follow the input", async ({ page }) => {
  const errors = watchErrors(page);
  await page.setContent(fixtures.M01_CANVAS, { waitUntil: "load" });

  const phases: Record<string, Phase> = {};
  const basis = await capture(page);
  phases.x3 = canvasPhase(basis, basis.text);
  await page.locator("input[data-x]").evaluate(element => {
    const input = element as HTMLInputElement;
    input.value = "-1";
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await page.waitForTimeout(60);
  phases["xminus1"] = canvasPhase(await capture(page), "");

  const observation = await observationOf(phases, errors, basis);

  expect(result(observation, "chart-follows-x", m01)?.status).toBe("pass");
  expect(result(observation, "value-at-3", m01)?.status).toBe("pass");
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

  const observation = await observationOf(phases, errors, basis);

  expect(result(observation, "chart-follows-x", m01)?.status).toBe("fail");
});

async function runM01(page: Parameters<typeof capture>[0], html: string): Promise<Observation> {
  const errors = watchErrors(page);
  await page.setContent(html, { waitUntil: "load" });
  return observeM01(page, errors);
}

async function runP01(page: Parameters<typeof capture>[0], html: string): Promise<Observation> {
  const errors = watchErrors(page);
  await page.setContent(html, { waitUntil: "load" });
  await page.waitForTimeout(120);
  return observeP01Fault(page, errors);
}

async function runP01Calibrated(
  page: Parameters<typeof capture>[0],
  html: string
): Promise<Observation> {
  const errors = watchErrors(page);
  await page.setContent(html, { waitUntil: "load" });
  return observeP01(page, errors);
}

async function runFault(
  page: Parameters<typeof capture>[0],
  fault: HtmlFault
): Promise<Observation> {
  const errors = watchErrors(page);
  await page.setContent(fault.html, { waitUntil: "load" });
  await page.waitForTimeout(120);
  return observeFault(page, fault, errors);
}

test.describe("HTML-level faults", () => {
  for (const fault of HTML_FAULTS) {
    test(`${fault.id} ${fault.description}`, async ({ page }, testInfo) => {
      test.skip(
        testInfo.project.name !== "desktop-chromium",
        "the HTML fault catalogue runs once, not per viewport"
      );
      const observation = await runFault(page, fault);
      const spec = TASK_SPECS.find(item => item.id === fault.taskId)!;

      expect(result(observation, fault.checkId, spec)?.status).toBe("fail");
    });
  }
});

type MatrixEntry = {
  id: string;
  html?: string;
  phases?: Array<{ name: string; selector: string }>;
};

const MATRIX: MatrixEntry[] = [
  { id: "J01" },
  { id: "J02", html: fixtures.J02_PAGE, phases: [{ name: "call", selector: '[data-phase="call"]' }] },
  { id: "A01", html: fixtures.A01_PAGE, phases: [{ name: "found", selector: '[data-phase="found"]' }] },
  { id: "A02", html: fixtures.A02_PAGE, phases: [{ name: "result", selector: '[data-phase="result"]' }] },
  {
    id: "D01",
    html: fixtures.D01_PAGES,
    phases: [
      { name: "committed", selector: '[data-phase="committed"]' },
      { name: "rolled_back", selector: '[data-phase="rolled_back"]' },
    ],
  },
  {
    id: "D02",
    html: fixtures.D02_PAGES,
    phases: [
      { name: "interleaved", selector: '[data-phase="interleaved"]' },
      { name: "serialized", selector: '[data-phase="serialized"]' },
    ],
  },
  { id: "C01", html: fixtures.C01_PAGE, phases: [{ name: "running", selector: '[data-phase="running"]' }] },
  { id: "M01" },
  {
    id: "M02",
    html: fixtures.M02_PAGES,
    phases: [
      { name: "base", selector: '[data-phase="base"]' },
      { name: "adjusted", selector: '[data-phase="adjusted"]' },
    ],
  },
  { id: "P01" },
  { id: "S01", html: fixtures.S01_PAGE, phases: [{ name: "metrics", selector: '[data-phase="metrics"]' }] },
  { id: "N01", html: fixtures.N01_PAGE, phases: [{ name: "complete", selector: '[data-phase="complete"]' }] },
];

test.describe("reference matrix", () => {
  for (const entry of MATRIX) {
    test(`judges ${entry.id} from a reference page`, async ({ page }) => {
      let observation: Observation;
      if (entry.id === "J01") {
        observation = await runJ01Steps(page, fixtures.J01_STEPS);
      } else if (entry.id === "M01") {
        observation = await runM01(page, fixtures.M01_CANVAS);
      } else if (entry.id === "P01") {
        observation = await runP01Calibrated(page, fixtures.P01_STEPPED);
      } else {
        const errors = watchErrors(page);
        await page.setContent(entry.html!, { waitUntil: "load" });
        observation = await observePhases(page, entry.phases!, errors);
      }

      const spec = TASK_SPECS.find(item => item.id === entry.id)!;
      const summary = summarize(judge(spec, observation));
      const usability = summarize(judgeUsability(observation));

      expect(summary.failed).toEqual([]);
      expect(summary.indeterminate).toEqual([]);
      expect(summary.passed).toBeGreaterThan(0);
      expect(usability.failed).toEqual([]);
    });
  }
});
