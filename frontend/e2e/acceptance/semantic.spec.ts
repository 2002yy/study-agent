import { expect, test } from "@playwright/test";

import { TASK_SPECS, judge, summarize } from "../../src/acceptance/model";
import { watchErrors } from "./observer";
import { observeJ01 } from "./semantic";
import { j01Page } from "./semanticFixtures";

const j01 = TASK_SPECS.find(spec => spec.id === "J01")!;

for (const style of ["display:none", "visibility:hidden", "stroke:none", "stroke-opacity:0", "opacity:0"]) {
  test(`excludes invisible arrow evidence: ${style}`, async ({ page }) => {
    const errors = watchErrors(page);
    const observation = await observeJ01(page, errors, j01Page("html").replace("</head>", `<style>line{${style}}</style></head>`));
    expect(judge(j01, observation).find(check => check.checkId === "evidence-consistent")?.status).toBe("indeterminate");
    expect(summarize(judge(j01, observation)).indeterminate.length).toBeGreaterThan(0);
  });
}

function check(observation: Awaited<ReturnType<typeof observeJ01>>, id: string) {
  return judge(j01, observation).find(result => result.checkId === id);
}

for (const layout of ["svg", "html"] as const) {
  test(`locates variables, objects and arrows in a ${layout} diagram`, async ({ page }) => {
    const errors = watchErrors(page);
    const observation = await observeJ01(page, errors, j01Page(layout));
    const summary = summarize(judge(j01, observation));

    expect(summary.failed).toEqual([]);
    expect(check(observation, "arrow-points-at-its-object")?.status).toBe("pass");
    expect(check(observation, "evidence-consistent")?.status).toBe("pass");
    expect(check(observation, "shared-object")?.status).toBe("pass");
    expect(check(observation, "reassigned-objects")?.status).toBe("pass");
  });
}

test("refuses to place objects whose boxes were never laid out", async ({ page }) => {
  const errors = watchErrors(page);
  const observation = await observeJ01(page, errors, j01Page("broken"));

  // The arrow still reaches the coordinates in the page, but no object is
  // there; that is a real geometric defect, not missing evidence.
  expect(check(observation, "arrow-points-at-its-object")?.status).toBe("fail");
  // The printed claim still exists, so the independent check must stay open.
  expect(check(observation, "evidence-consistent")?.status).toBe("indeterminate");
});

test("keeps task checks open when the page cannot be advanced", async ({ page }) => {
  const errors = watchErrors(page);
  const observation = await observeJ01(
    page,
    errors,
    '<!doctype html><html><body><p>a 指向对象1，b 指向对象2</p></body></html>'
  );

  expect(check(observation, "runtime")?.status).toBe("pass");
  expect(check(observation, "reassigned-objects")?.status).toBe("indeterminate");
  expect(check(observation, "arrow-points-at-its-object")?.status).toBe("indeterminate");
});
