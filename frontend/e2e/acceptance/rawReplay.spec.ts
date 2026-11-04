import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, realpathSync, writeFileSync } from "node:fs";
import { join, relative, resolve, isAbsolute } from "node:path";
import { expect, test } from "@playwright/test";
import { watchErrors } from "./observer";
import { replayRaw } from "./rawReplay";
import { j01Page } from "./semanticFixtures";

const VIEWPORTS = [{ width: 1280, height: 800 }, { width: 390, height: 844 }];

for (const viewport of VIEWPORTS) {
  test(`raw sandbox semantic controls at ${viewport.width}px`, async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-chromium", "explicit viewport matrix");
    await page.setViewportSize(viewport);
    await page.goto("/m4c-harness.html");
    const errors = watchErrors(page);
    const good = await replayRaw(page, j01Page("html"), "J01", viewport, errors);
    expect(good.inner_width).toBe(viewport.width);
    expect(good.checks.every(check => check.status === "pass")).toBe(true);
    const broken = await replayRaw(page, j01Page("broken"), "J01", viewport, errors);
    expect(broken.checks.find(check => check.checkId === "arrow-points-at-its-object")?.status).toBe("fail");
    const unknown = await replayRaw(page, "<p>距离6，路径A-B-C-D</p>", "A02", viewport, errors);
    expect(unknown.status).toBe("indeterminate");
    expect(unknown.checks.some(check => check.status === "indeterminate")).toBe(true);
    const runtime = await replayRaw(page, "<script>throw Error('negative control')</script>", "A02", viewport, errors);
    expect(runtime.checks.find(check => check.checkId === "runtime")?.status).toBe("fail");
  });

  test(`raw corpus at ${viewport.width}px`, async ({ page }, testInfo) => {
    const directory = process.env.M4C3_RAW_DIR;
    test.skip(!directory, "set M4C3_RAW_DIR to an explicit raw export");
    test.skip(testInfo.project.name !== "desktop-chromium", "explicit viewport matrix");
    test.setTimeout(180_000);
    page.setDefaultTimeout(1500);
    const root = realpathSync(directory!);
    const index = JSON.parse(readFileSync(join(root, "index.json"), "utf-8"));
    expect(index.schema_version).toBe("m4c3-raw-v1");
    await page.setViewportSize(viewport);
    await page.goto("/m4c-harness.html");
    const errors = watchErrors(page);
    const out = join(root, `sandbox-${viewport.width}`);
    mkdirSync(out); // Fresh evidence only, never overwrite a previous replay.
    const reports = [];
    for (const [number, item] of index.cases.entries()) {
      expect(item.source_kind).toBe(index.generation_mode === "fake_http" ? "fake_transport" : "saved_model");
      const file = realpathSync(resolve(root, item.file));
      const local = relative(root, file);
      if (isAbsolute(local) || local === ".." || local.startsWith("..\\") || local.startsWith("../")) {
        throw new Error("Raw HTML path escapes export directory");
      }
      const raw = readFileSync(file);
      const sha256 = createHash("sha256").update(raw).digest("hex");
      expect(sha256).toBe(item.sha256);
      errors.pageErrors.length = 0;
      errors.consoleErrors.length = 0;
      const result = await replayRaw(page, raw.toString("utf-8"), item.task_id, viewport, errors);
      const screenshot = `document-${number}.png`;
      await page.screenshot({ path: join(out, screenshot), fullPage: true });
      reports.push({ ...item, sha256, ...result, screenshot });
    }
    writeFileSync(join(out, "report.json"), JSON.stringify({
      schema_version: "m4c3-raw-sandbox-v1",
      historical_replay_only: index.purpose !== "m4c3_first_generation",
      source_generation_mode: index.generation_mode ?? "historical",
      model_calls: 0, cases: reports,
    }, null, 2));
    expect(reports.length).toBe(index.cases.length);
  });
}
