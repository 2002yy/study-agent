/** Prove that mobile evidence is measured inside a mobile-sized product frame. */
import { expect, test } from "@playwright/test";

import { judgeUsability } from "../../src/acceptance/model";
import { capture, watchErrors } from "./observer";
import { mountSandbox } from "./sandboxParity";
import { observationOf } from "./taskObservers";

for (const viewport of [{ width: 1280, height: 800 }, { width: 390, height: 844 }]) {
  test(`product sandbox measures actual ${viewport.width}px layout`, async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-chromium", "explicit viewport matrix runs once");
    await page.setViewportSize(viewport);
    await page.goto("/m4c-harness.html");
    const errors = watchErrors(page);
    for (const width of ["100%", "900px"]) {
      const inner = await mountSandbox(page, `
        <style>html,body{margin:0}body{font-size:16px}
        main{width:${width};height:120px;background:#ddd}button{min-width:80px;min-height:44px}</style>
        <main>viewport probe <button>Test</button></main>`, viewport);
      expect(await inner.evaluate(() => window.innerWidth)).toBe(viewport.width);
      const evidence = await capture(inner);
      const results = judgeUsability(observationOf({}, errors, evidence));
      const overflow = results.find(item => item.checkId === "usability-overflow");
      expect(overflow?.status).toBe(width === "900px" && viewport.width < 900 ? "fail" : "pass");
      expect(errors.pageErrors).toEqual([]);
      await page.screenshot({ path: testInfo.outputPath(`${width === "100%" ? "responsive" : "fixed"}.png`) });
    }
  });
}
