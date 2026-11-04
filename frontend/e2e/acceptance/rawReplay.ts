/** Saved HTML is mounted unchanged through the product sandbox; no reference adapters. */
import type { Page } from "@playwright/test";
import { TASK_SPECS, judge, judgeUsability } from "../../src/acceptance/model";
import { capture, type ErrorCapture } from "./observer";
import { mountSandbox } from "./sandboxParity";
import { observeMountedJ01 } from "./semantic";
import { observationOf } from "./taskObservers";

export async function replayRaw(
  page: Page, html: string, taskId: string | null,
  viewport: { width: number; height: number }, errors: ErrorCapture
) {
  const spec = taskId ? TASK_SPECS.find(task => task.id === taskId) : undefined;
  if (taskId && !spec) throw new Error(`Unknown task: ${taskId}`);
  const inner = await mountSandbox(page, html, viewport);
  let observation = observationOf({}, errors, await capture(inner));
  let observerError: string | null = null;
  if (taskId === "J01") {
    try {
      observation = await observeMountedJ01(inner, errors);
    } catch (error) {
      // A locator failure is missing evidence, not a model runtime error.
      observerError = String(error).slice(0, 500);
      observation = observationOf({}, errors, await capture(inner));
    }
  }
  const checks = spec ? judge(spec, observation) : [];
  const usability = judgeUsability(observation);
  const all = [...checks, ...usability];
  const status = !spec ? "unjudged" : all.some(check => check.status === "fail") ? "failed"
    : all.some(check => check.status === "indeterminate") ? "indeterminate" : "passed";
  return {
    task_id: taskId, status, viewport,
    inner_width: await inner.evaluate(() => window.innerWidth),
    observation: structuredClone(observation), checks, usability, observer_error: observerError,
    runtime_errors: [...errors.pageErrors, ...errors.consoleErrors],
    steps: taskId === "J01" ? ["mount raw HTML", "advance to step 2", "advance to step 5", "capture"]
      : ["mount raw HTML", "capture generic evidence; task adapter unavailable"],
    adapter: taskId === "J01" ? "semantic-j01" : "generic-no-task-inference",
  };
}
