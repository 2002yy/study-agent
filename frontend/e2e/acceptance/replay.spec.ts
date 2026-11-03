/**
 * Offline replay of saved real answers (M4-C, no model calls).
 *
 * Reads documents exported by tools/interactive_replay_survey.py, runs each one
 * in Chromium, and reports what the acceptance chain can actually determine.
 * A document is only judged against a frozen task when it is an instance of
 * that task; everything else is measured for the generic layers and reported
 * as unjudged with a reason. Every case keeps its source hash, screenshot,
 * operation steps and observation data so a judgement can be replayed.
 */
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import { expect, test } from "@playwright/test";

import {
  TASK_SPECS,
  judge,
  judgeUsability,
  summarize,
  type Observation,
  type Phase,
} from "../../src/acceptance/model";
import { watchErrors } from "./observer";
import { observeGeneric, observeJ01, observeSpring, type GenericBehavior } from "./semantic";

const REPLAY_DIR = process.env.M4C_REPLAY_DIR ?? "";

/** Only a document that really is an instance of a frozen task is mapped. */
const TASK_BY_COMPONENT: Record<string, string> = {
  "cache-ref-canvas": "J01",
};

/**
 * The spring document shares P01's formula but fixes the amplitude at 40px,
 * while frozen P01 requires the positions 0/2/0. Judging it as P01 would turn
 * a different (valid) instance into a false failure, so it is only related.
 */
const RELATED: Record<string, { task: string; reason: string }> = {
  spring_phase_lab: {
    task: "P01",
    reason: "保存的文档振幅为 40px，冻结 P01 要求相位 π/2 时位置为 2，不是同一实例",
  },
};

const DOMAIN_BY_COMPONENT: Record<string, string> = {
  "cache-ref-canvas": "J01",
  spring_phase_lab: "P01",
  "stock-lock-lab": "inventory",
  stock_locked_demo: "inventory",
  "inventory-lock-panel": "inventory",
};

type Case = {
  case_id: string;
  file: string;
  component_id: string;
  revision: number;
  title: string;
  html_chars: number;
  domain?: string;
  sha256?: string;
  db?: string;
};

function evidenceOf(phases: Record<string, Phase>) {
  return Object.fromEntries(
    Object.entries(phases).map(([name, phase]) => [
      name,
      {
        declared: phase.declared,
        observed: phase.observed,
        marker: phase.canvas?.marker ?? null,
        vertical_marks: phase.canvas?.verticalMarks ?? [],
        text: phase.text.slice(0, 400),
      },
    ])
  );
}

test.describe("offline replay of saved answers", () => {
  test("measures every saved document", async ({ page }, testInfo) => {
    test.skip(!REPLAY_DIR, "set M4C_REPLAY_DIR to an export");
    test.skip(testInfo.project.name !== "desktop-chromium", "replay runs once");
    const indexPath = join(REPLAY_DIR, "index.json");
    test.skip(!existsSync(indexPath), "the export index is missing");
    const index = JSON.parse(readFileSync(indexPath, "utf-8")) as {
      cases: Case[];
    };
    mkdirSync(join(REPLAY_DIR, "screens"), { recursive: true });

    const reports = [];
    for (const item of index.cases) {
      const html = readFileSync(join(REPLAY_DIR, item.file), "utf-8");
      const sourceSha = createHash("sha256").update(html).digest("hex");
      const errors = watchErrors(page);

      let observation: Observation;
      let behavior: GenericBehavior | null = null;
      let evidenceMode = "generic";
      let steps = ["load"];
      if (item.component_id === "cache-ref-canvas") {
        observation = await observeJ01(page, errors, html);
        evidenceMode = "semantic";
        steps = ["load", "advance to step 2", "advance to step 5"];
      } else if (item.component_id === "spring_phase_lab") {
        const spring = await observeSpring(page, errors, html);
        observation = spring.observation;
        behavior = spring.behavior;
        evidenceMode = "controls";
        steps = ["load", "play", "pause"];
      } else {
        observation = await observeGeneric(page, errors, html);
      }

      const taskId = TASK_BY_COMPONENT[item.component_id];
      const related = RELATED[item.component_id];
      const spec = taskId ? TASK_SPECS.find(entry => entry.id === taskId) : undefined;
      const checks = spec ? judge(spec, observation) : [];
      const summary = summarize(checks);
      const usabilityChecks = judgeUsability(observation);
      const usability = summarize(usabilityChecks);
      const screenshot = `screens/${item.case_id}.png`;
      await page.screenshot({ path: join(REPLAY_DIR, screenshot), fullPage: true });

      reports.push({
        case_id: item.case_id,
        component_id: item.component_id,
        revision: item.revision,
        title: item.title,
        domain: item.domain ?? DOMAIN_BY_COMPONENT[item.component_id] ?? "other",
        db: item.db ?? null,
        source_sha256: sourceSha,
        screenshot,
        steps,
        task: taskId ?? null,
        related_task: related?.task ?? null,
        note: taskId ? null : (related?.reason ?? "不是冻结 12 题的实例"),
        evidence_mode: evidenceMode,
        runtime: errors.consoleErrors.length + errors.pageErrors.length === 0 ? "pass" : "fail",
        runtime_errors: [...errors.consoleErrors, ...errors.pageErrors],
        min_font: observation.fontSizes.length ? Math.min(...observation.fontSizes) : null,
        horizontal_overflow: observation.horizontalOverflow,
        behavior,
        evidence: evidenceOf(observation.phases),
        checks: checks.map(check => ({
          id: check.checkId,
          layer: check.layer,
          status: check.status,
          detail: check.detail,
        })),
        checks_total: checks.length,
        determined: summary.passed + summary.failed.length,
        passed: summary.passed,
        failed: summary.failed.map(check => check.checkId),
        indeterminate: summary.indeterminate.map(check => check.checkId),
        usability: {
          passed: usability.passed,
          failed: usability.failed.map(check => ({ id: check.checkId, detail: check.detail })),
          indeterminate: usability.indeterminate.map(check => check.checkId),
          checks: usabilityChecks,
        },
      });
    }

    const judged = reports.filter(item => item.task);
    const taskChecks = judged.reduce((total, item) => total + item.checks_total, 0);
    const determined = judged.reduce((total, item) => total + item.determined, 0);
    const usabilityFailures = reports.flatMap(item =>
      item.usability.failed.map(check => ({ case_id: item.case_id, ...check }))
    );
    const report = {
      schema_version: "m4c-replay-report-v3",
      replay_dir: REPLAY_DIR,
      cases: reports,
      automatic_determination: {
        documents_total: reports.length,
        documents_judged: judged.length,
        task_checks: taskChecks,
        determined,
        ratio: taskChecks ? Number((determined / taskChecks).toFixed(3)) : 0,
        unjudged: reports
          .filter(item => !item.task)
          .map(item => ({
            case_id: item.case_id,
            domain: item.domain,
            related_task: item.related_task,
            reason: item.note,
          })),
      },
      usability: {
        documents: reports.length,
        failures: usabilityFailures,
        documents_with_failures: new Set(usabilityFailures.map(item => item.case_id)).size,
      },
      domains: reports.reduce<Record<string, number>>((counts, item) => {
        counts[item.domain] = (counts[item.domain] ?? 0) + 1;
        return counts;
      }, {}),
    };
    writeFileSync(join(REPLAY_DIR, "report.json"), JSON.stringify(report, null, 2), "utf-8");

    // The replay must run every saved document without a page error, and the
    // semantic locators must determine almost all task checks on real pages.
    expect(reports.length).toBe(index.cases.length);
    expect(reports.filter(item => item.runtime !== "pass").map(item => item.case_id)).toEqual([]);
    expect(report.automatic_determination.documents_judged).toBeGreaterThan(0);
    expect(report.automatic_determination.ratio).toBeGreaterThanOrEqual(0.9);
    // Every case must keep the evidence needed to review its judgement.
    for (const item of reports) {
      expect(item.source_sha256).toMatch(/^[0-9a-f]{64}$/);
      expect(existsSync(join(REPLAY_DIR, item.screenshot))).toBe(true);
      expect(item.steps.length).toBeGreaterThan(0);
      expect(item.usability.checks).toHaveLength(3);
    }
  });
});
