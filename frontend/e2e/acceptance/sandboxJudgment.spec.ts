/**
 * Full task judgement inside the real product sandbox.
 *
 * The parity spec compares observer evidence. This spec asks the stronger
 * question: does the judge still pass the twelve correct pages and still catch
 * all twenty-four injected defects when the page runs through the product's
 * sanitising pass, CSP and nested opaque-origin frames?
 */
import { createHash } from "node:crypto";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import { expect, test } from "@playwright/test";

import {
  TASK_SPECS,
  judge,
  judgeUsability,
  summarize,
  type Observation,
} from "../../src/acceptance/model";
import { HTML_FAULTS } from "./htmlFaults";
import { watchErrors } from "./observer";
import { mountSandbox } from "./sandboxParity";
import { observeFault, observeReference } from "./taskObservers";
import * as fixtures from "./fixtures";

const REFERENCE_PAGES: Array<{ id: string; html: string }> = [
  { id: "J01", html: fixtures.J01_STEPS },
  { id: "J02", html: fixtures.J02_PAGE },
  { id: "A01", html: fixtures.A01_PAGE },
  { id: "A02", html: fixtures.A02_PAGE },
  { id: "D01", html: fixtures.D01_PAGES },
  { id: "D02", html: fixtures.D02_PAGES },
  { id: "C01", html: fixtures.C01_PAGE },
  { id: "M01", html: fixtures.M01_CANVAS },
  { id: "M02", html: fixtures.M02_PAGES },
  { id: "P01", html: fixtures.P01_STEPPED },
  { id: "S01", html: fixtures.S01_PAGE },
  { id: "N01", html: fixtures.N01_PAGE },
];

const NEGATIVE_CONTROLS: Array<{ id: string; html: string }> = [
  { id: "P01-ambiguous-marks", html: fixtures.P01_AMBIGUOUS_MARKS },
  { id: "P01-big-block", html: fixtures.P01_BIG_BLOCK },
  { id: "no-evidence", html: fixtures.NO_EVIDENCE },
];

function sourceSha(html: string): string {
  return createHash("sha256").update(html).digest("hex");
}

function stepsForReference(id: string): string[] {
  if (id === "J01") return ["load", "capture shared", "click re-point", "capture reassigned"];
  if (id === "M01") return ["load", "capture x=3", "set x=-1", "capture x=-1"];
  if (id === "P01") return ["load", "capture phase 0", "set phase pi/2", "capture", "set phase pi", "capture", "play", "pause"];
  return ["load", "capture every data-phase section"];
}

function stepsForFault(taskId: string): string[] {
  if (taskId === "J01") return ["load", "capture"];
  if (taskId === "M01") return ["load", "capture x=3", "set x=-1", "capture"];
  if (taskId === "P01") return ["load", "capture", "pause", "capture twice"];
  return ["load", "capture every data-phase section"];
}

test.describe("sandbox task judgement", () => {
  test("passes all references, detects all defects and keeps missing evidence open", async ({
    page,
  }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-chromium", "runs once");
    test.setTimeout(300_000);

    await page.goto("/m4c-harness.html");
    await page.setContent("<!doctype html><html><body></body></html>");
    const errors = watchErrors(page);
    const outDir =
      process.env.M4C_SANDBOX_JUDGMENT_DIR ??
      join(process.cwd(), "test-results", "m4c-sandbox-judgment");
    mkdirSync(join(outDir, "screens"), { recursive: true });

    const referenceReports = [];
    for (const entry of REFERENCE_PAGES) {
      errors.consoleErrors.length = 0;
      errors.pageErrors.length = 0;
      const inner = await mountSandbox(page, entry.html);
      const observation = await observeReference(entry.id, inner, errors);
      const spec = TASK_SPECS.find(item => item.id === entry.id)!;
      const summary = summarize(judge(spec, observation));
      const usability = summarize(judgeUsability(observation));
      await page.screenshot({
        path: join(outDir, "screens", `reference-${entry.id}.png`),
        clip: { x: 0, y: 0, width: 900, height: 700 },
      });

      referenceReports.push({
        id: entry.id,
        task: entry.id,
        source_sha256: sourceSha(entry.html),
        steps: stepsForReference(entry.id),
        passed: summary.passed,
        failed: summary.failed.map(check => check.checkId),
        indeterminate: summary.indeterminate.map(check => check.checkId),
        usability_failed: usability.failed.map(check => check.checkId),
        runtime_errors: [...errors.consoleErrors, ...errors.pageErrors],
        checks: judge(spec, observation),
      });

      expect(summary.failed, `${entry.id} failed`).toEqual([]);
      expect(summary.indeterminate, `${entry.id} indeterminate`).toEqual([]);
      expect(summary.passed, `${entry.id} passed`).toBeGreaterThan(0);
      expect(usability.failed, `${entry.id} usability`).toEqual([]);
    }

    const faultReports = [];
    for (const fault of HTML_FAULTS) {
      errors.consoleErrors.length = 0;
      errors.pageErrors.length = 0;
      const inner = await mountSandbox(page, fault.html);
      const observation = await observeFault(inner, fault, errors);
      const spec = TASK_SPECS.find(item => item.id === fault.taskId)!;
      const results = judge(spec, observation);
      const target = results.find(check => check.checkId === fault.checkId);
      await page.screenshot({
        path: join(outDir, "screens", `fault-${fault.id}.png`),
        clip: { x: 0, y: 0, width: 900, height: 700 },
      });

      faultReports.push({
        id: fault.id,
        task: fault.taskId,
        target: fault.checkId,
        status: target?.status ?? "missing",
        detail: target?.detail ?? "",
        source_sha256: sourceSha(fault.html),
        steps: stepsForFault(fault.taskId),
        runtime_errors: [...errors.consoleErrors, ...errors.pageErrors],
        checks: results,
      });

      expect(target?.status, `${fault.id} ${fault.checkId}`).toBe("fail");
    }

    const negativeReports = [];
    for (const control of NEGATIVE_CONTROLS) {
      errors.consoleErrors.length = 0;
      errors.pageErrors.length = 0;
      const inner = await mountSandbox(page, control.html);
      const observation: Observation =
        control.id.startsWith("P01")
          ? await observeReference("P01", inner, errors)
          : await observeFault(inner, {
              id: control.id,
              taskId: "J01",
              layer: "state",
              checkId: "reassigned-objects",
              description: control.id,
              html: control.html,
            }, errors);
      const spec = TASK_SPECS.find(item => item.id === (control.id.startsWith("P01") ? "P01" : "J01"))!;
      const summary = summarize(judge(spec, observation));
      await page.screenshot({
        path: join(outDir, "screens", `negative-${control.id}.png`),
        clip: { x: 0, y: 0, width: 900, height: 700 },
      });

      negativeReports.push({
        id: control.id,
        source_sha256: sourceSha(control.html),
        passed: summary.passed,
        failed: summary.failed.map(check => check.checkId),
        indeterminate: summary.indeterminate.map(check => check.checkId),
        runtime_errors: [...errors.consoleErrors, ...errors.pageErrors],
      });

      expect(summary.failed, `${control.id} must not fail`).toEqual([]);
      expect(summary.indeterminate.length, `${control.id} must stay open`).toBeGreaterThan(0);
    }

    const report = {
      schema_version: "m4c-sandbox-judgment-v1",
      reference: referenceReports,
      faults: faultReports,
      negative_controls: negativeReports,
      summary: {
        references_passed: referenceReports.filter(item => item.failed.length === 0 && item.indeterminate.length === 0).length,
        references_total: referenceReports.length,
        faults_detected: faultReports.filter(item => item.status === "fail").length,
        faults_total: faultReports.length,
        negative_controls_open: negativeReports.filter(item => item.indeterminate.length > 0).length,
      },
    };
    writeFileSync(join(outDir, "judgment.json"), JSON.stringify(report, null, 2), "utf-8");

    expect(report.summary.references_passed).toBe(REFERENCE_PAGES.length);
    expect(report.summary.faults_detected).toBe(HTML_FAULTS.length);
    expect(report.summary.negative_controls_open).toBe(NEGATIVE_CONTROLS.length);
  });
});
