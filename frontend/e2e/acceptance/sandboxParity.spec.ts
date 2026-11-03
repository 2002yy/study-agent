/**
 * Direct rendering vs the real product sandbox.
 *
 * Every reference page and every injected defect is run twice: once with
 * `setContent` and once through `makeInteractiveDocument`, which adds the
 * sanitising pass, CSP, the outer trusted frame and the inner opaque-origin
 * frame. Results are reported side by side; the two environments are never
 * merged into a single score.
 */
import { createHash } from "node:crypto";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import { expect, test } from "@playwright/test";

import { watchErrors } from "./observer";
import {
  applyOps,
  compare,
  environmentOf,
  mountSandbox,
  readMessages,
  runDirect,
  snapshot,
  stripControls,
  type Environment,
  type Op,
} from "./sandboxParity";
import * as fixtures from "./fixtures";
import { HTML_FAULTS } from "./htmlFaults";
import { explorer } from "../fixtures/interactive-document";

type ParityCase = {
  id: string;
  html: string;
  ops: Op[];
  deterministicCanvas: boolean;
  state?: boolean;
};

const REFERENCE_CASES: ParityCase[] = [
  {
    id: "ref-J01",
    html: fixtures.J01_STEPS,
    ops: [{ kind: "click", name: "b = new Object()" }],
    deterministicCanvas: false,
  },
  { id: "ref-J02", html: fixtures.J02_PAGE, ops: [], deterministicCanvas: false },
  { id: "ref-A01", html: fixtures.A01_PAGE, ops: [], deterministicCanvas: false },
  { id: "ref-A02", html: fixtures.A02_PAGE, ops: [], deterministicCanvas: false },
  { id: "ref-D01", html: fixtures.D01_PAGES, ops: [], deterministicCanvas: false },
  { id: "ref-D02", html: fixtures.D02_PAGES, ops: [], deterministicCanvas: false },
  { id: "ref-C01", html: fixtures.C01_PAGE, ops: [], deterministicCanvas: false },
  {
    id: "ref-M01",
    html: fixtures.M01_CANVAS,
    ops: [{ kind: "input", selector: "input[data-x]", value: "-1" }],
    deterministicCanvas: true,
  },
  { id: "ref-M02", html: fixtures.M02_PAGES, ops: [], deterministicCanvas: false },
  {
    id: "ref-P01",
    html: fixtures.P01_STEPPED,
    ops: [{ kind: "input", selector: "[data-phase]", value: String(Math.PI / 2) }],
    deterministicCanvas: true,
  },
  {
    id: "ref-P01-zero",
    html: fixtures.P01_STEPPED,
    ops: [{ kind: "input", selector: "[data-phase]", value: "0" }],
    deterministicCanvas: true,
  },
  {
    id: "ref-P01-pi",
    html: fixtures.P01_STEPPED,
    ops: [{ kind: "input", selector: "[data-phase]", value: String(Math.PI) }],
    deterministicCanvas: true,
  },
  { id: "ref-S01", html: fixtures.S01_PAGE, ops: [], deterministicCanvas: false },
  { id: "ref-N01", html: fixtures.N01_PAGE, ops: [], deterministicCanvas: false },
];

const FAULT_CASES: ParityCase[] = HTML_FAULTS.map(fault => {
  const ops: Op[] =
    fault.id === "HV03"
      ? [{ kind: "input", selector: "input[data-x]", value: "-1" }]
      : fault.id === "HV04"
        ? [{ kind: "click", name: "暂停" }]
        : [];
  return {
    id: `fault-${fault.id}`,
    html: fault.html,
    ops,
    deterministicCanvas: !["HR06", "HV04"].includes(fault.id),
  };
});

const CASES: ParityCase[] = [
  ...REFERENCE_CASES,
  ...FAULT_CASES,
  {
    id: "fixture-explorer",
    html: explorer.html,
    ops: [{ kind: "input", selector: "#locked", value: "12" }],
    deterministicCanvas: false,
    state: true,
  },
];

function lastState(states: unknown[]): unknown {
  return states.length ? stripControls(states[states.length - 1]) : null;
}

test.describe("real product sandbox parity", () => {
  test("runs reference pages and defects through both environments", async ({
    page,
    context,
  }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-chromium", "runs once");
    test.setTimeout(240_000);

    await page.goto("/");
    await page.setContent("<!doctype html><html><body></body></html>");

    const sandboxErrors = watchErrors(page);

    const outDir = process.env.M4C_SANDBOX_DIR ?? join(process.cwd(), "test-results", "m4c-sandbox");
    mkdirSync(join(outDir, "screens"), { recursive: true });

    const reports = [];
    for (const parityCase of CASES) {
      const sourceSha = createHash("sha256").update(parityCase.html).digest("hex");
      const steps = ["load", ...parityCase.ops.map(op => JSON.stringify(op))];

      // A fresh page per case: `setContent` keeps the global lexical
      // environment, so reusing one page would let a previous case's top-level
      // `const` collide with the next case's script.
      const direct = await context.newPage();
      const directErrors = watchErrors(direct);
      const directRun = await runDirect(direct, parityCase.html, parityCase.ops, directErrors);
      const directState = parityCase.state ? lastState(directRun.states) : null;
      const directEnvironment: Environment = environmentOf(
        directRun.after,
        directRun.before.text,
        directRun.errors,
        directState
      );

      sandboxErrors.consoleErrors.length = 0;
      sandboxErrors.pageErrors.length = 0;
      const inner = await mountSandbox(page, parityCase.html);
      const sandboxBefore = await snapshot(inner);
      await applyOps(inner, parityCase.ops);
      await page.waitForTimeout(80);
      const sandboxAfter = await snapshot(inner);
      const messages = await readMessages(page);
      const forwardedErrors = messages
        .filter(message => message.type === "error")
        .map(message => String(message.value ?? "").slice(0, 500));
      const sandboxState = parityCase.state
        ? lastState(messages.filter(message => message.type === "state").map(message => message.value))
        : null;
      const sandboxEnvironment: Environment = environmentOf(
        sandboxAfter,
        sandboxBefore.text,
        [
          ...sandboxErrors.consoleErrors,
          ...sandboxErrors.pageErrors,
          ...forwardedErrors,
        ],
        sandboxState
      );

      await direct.screenshot({
        path: join(outDir, "screens", `${parityCase.id}-direct.png`),
        fullPage: true,
      });
      await direct.close();
      await page.screenshot({
        path: join(outDir, "screens", `${parityCase.id}-sandbox.png`),
        clip: { x: 0, y: 0, width: 900, height: 700 },
      });

      reports.push(
        compare(
          parityCase.id,
          sourceSha,
          steps,
          directEnvironment,
          sandboxEnvironment,
          parityCase.deterministicCanvas
        )
      );
    }

    writeFileSync(join(outDir, "parity.json"), JSON.stringify(reports, null, 2), "utf-8");

    expect(reports.length).toBe(CASES.length);
    const behavioral = reports.filter(report => report.behavioral_differences.length);
    if (behavioral.length) {
      console.log(
        "BEHAVIORAL DIFFERENCES",
        JSON.stringify(
          behavioral.map(report => ({
            case: report.case_id,
            differences: report.behavioral_differences,
          })),
          null,
          2
        )
      );
    }
    expect(behavioral.map(report => report.case_id)).toEqual([]);
  });
});
