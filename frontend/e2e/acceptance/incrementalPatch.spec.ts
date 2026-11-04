import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { expect, test } from "@playwright/test";
import { mountSandbox } from "./sandboxParity";
import { watchErrors } from "./observer";

test("bounded patch retains old behavior and rejects a broken calculation", async ({ page }, testInfo) => {
  const directory = process.env.M4D_PATCH_DEMO_DIR;
  test.skip(!directory, "run python -m tools.interactive_patch_demo --out <new directory>");
  test.skip(testInfo.project.name !== "desktop-chromium", "explicit two-viewport matrix");
  const manifest = JSON.parse(readFileSync(join(directory!, "manifest.json"), "utf-8"));
  const reports = [];
  await page.goto("/m4c-harness.html");
  const errors = watchErrors(page);
  for (const viewport of [{ width: 1280, height: 800 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport);
    for (const item of manifest) {
      errors.pageErrors.length = 0;
      errors.consoleErrors.length = 0;
      const html = readFileSync(join(directory!, item.file), "utf-8");
      expect(createHash("sha256").update(html).digest("hex")).toBe(item.sha256);
      const inner = await mountSandbox(page, html, viewport);
      const checks = [];
      for (const [input, expected] of [[3, 7], [-1, -1]]) {
        await inner.locator("#x").fill(String(input));
        await inner.locator("#x").dispatchEvent("input");
        const actual = await inner.locator("#y").textContent();
        checks.push({ id: `linear-x-${input}`, actual, expected: String(expected), passed: actual === String(expected) });
      }
      await inner.getByRole("button", { name: "Reset", exact: true }).click();
      checks.push({ id: "reset", passed: await inner.locator("#x").inputValue() === "1" && await inner.locator("#y").textContent() === "3" });
      if (item.revision >= 2) {
        await inner.locator("#x").fill("3");
        await inner.getByRole("button", { name: "Double x", exact: true }).click();
        checks.push({ id: "new-double-control", passed: await inner.locator("#x").inputValue() === "6" && await inner.locator("#y").textContent() === "13" });
      }
      checks.push({ id: "runtime", passed: !errors.pageErrors.length && !errors.consoleErrors.length });
      const passed = checks.every(check => check.passed);
      const screenshot = `${item.name}-${viewport.width}.png`;
      await page.screenshot({ path: join(directory!, screenshot), fullPage: true });
      reports.push({ ...item, viewport, passed, checks, screenshot, runtime_errors: [...errors.pageErrors, ...errors.consoleErrors] });
      expect(passed).toBe(item.name !== "broken-calculation");
    }
  }
  writeFileSync(join(directory!, "browser-results.json"), JSON.stringify(reports, null, 2));
});
