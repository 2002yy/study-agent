/**
 * Offline replay of saved real answers (M4-C, no model calls).
 *
 * Reads documents exported by tools/interactive_replay_export.py, runs each one
 * in Chromium, and reports what the acceptance chain can actually determine.
 * It deliberately does not invent a task mapping: only ids that clearly belong
 * to a frozen task are judged against that task, and the rest are measured for
 * the generic layers (runtime, font size, overflow).
 */
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import { expect, test } from "@playwright/test";

import { TASK_SPECS, judge, summarize, type Observation } from "../../src/acceptance/model";
import { capture, watchErrors } from "./observer";

const REPLAY_DIR = process.env.M4C_REPLAY_DIR ?? "";

/** Only a clear identity match is mapped; everything else stays unmapped. */
const TASK_BY_COMPONENT: Record<string, string> = {
  "cache-ref-canvas": "J01",
  spring_phase_lab: "P01",
};

type Case = {
  case_id: string;
  file: string;
  component_id: string;
  revision: number;
  title: string;
  html_chars: number;
};

test.describe("offline replay of saved answers", () => {
  test.skip(!REPLAY_DIR || !existsSync(join(REPLAY_DIR, "index.json")), "set M4C_REPLAY_DIR to an export");

  const index = JSON.parse(readFileSync(join(REPLAY_DIR, "index.json"), "utf-8")) as {
    cases: Case[];
  };

  test(`measures ${index.cases.length} saved documents`, async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-chromium", "replay runs once");

    const reports = [];
    let determined = 0;
    let totalChecks = 0;

    for (const item of index.cases) {
      const html = readFileSync(join(REPLAY_DIR, item.file), "utf-8");
      const errors = watchErrors(page);
      await page.setContent(html, { waitUntil: "load" });
      await page.waitForTimeout(150);
      const evidence = await capture(page);
      const observation: Observation = {
        phases: {},
        consoleErrors: errors.consoleErrors,
        pageErrors: errors.pageErrors,
        fontSizes: evidence.fontSizes,
        controlSizes: evidence.controlSizes,
        horizontalOverflow: evidence.horizontalOverflow,
      };

      const taskId = TASK_BY_COMPONENT[item.component_id];
      const spec = taskId ? TASK_SPECS.find(entry => entry.id === taskId) : undefined;
      const checks = spec ? judge(spec, observation) : [];
      const summary = summarize(checks);
      totalChecks += checks.length;
      determined += summary.passed + summary.failed.length;

      reports.push({
        case_id: item.case_id,
        component_id: item.component_id,
        revision: item.revision,
        title: item.title,
        task: taskId ?? null,
        runtime: errors.consoleErrors.length + errors.pageErrors.length === 0 ? "pass" : "fail",
        min_font: evidence.fontSizes.length ? Math.min(...evidence.fontSizes) : null,
        horizontal_overflow: evidence.horizontalOverflow,
        checks: checks.map(check => ({ id: check.checkId, layer: check.layer, status: check.status })),
        passed: summary.passed,
        failed: summary.failed.map(check => check.checkId),
        indeterminate: summary.indeterminate.map(check => check.checkId),
      });
    }

    const report = {
      schema_version: "m4c-replay-report-v1",
      replay_dir: REPLAY_DIR,
      cases: reports,
      automatic_determination: {
        determined,
        total_task_checks: totalChecks,
        ratio: totalChecks ? Number((determined / totalChecks).toFixed(3)) : 0,
      },
    };
    writeFileSync(join(REPLAY_DIR, "report.json"), JSON.stringify(report, null, 2), "utf-8");

    // The replay must not crash and must export a report; correctness of the
    // model's documents is reported, not asserted here.
    expect(reports.length).toBe(index.cases.length);
  });
});
