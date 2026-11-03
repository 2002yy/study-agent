/**
 * Task-level observations that work on either a direct page or the inner frame
 * of the real product sandbox.
 *
 * The same functions are used by the direct reference matrix, the direct fault
 * catalogue and the sandbox judgement, so a verdict cannot drift between the
 * two environments because of a different observation path.
 */
import type { Observation, Phase } from "../../src/acceptance/model";
import {
  canvasPhase,
  declaredAmplitude,
  evidencePhase,
  j01Phase,
  positionFromCanvas,
} from "./adapters";
import type { HtmlFault } from "./htmlFaults";
import { capture, type ErrorCapture, type EvidenceHost, type RawEvidence } from "./observer";

export function observationOf(
  phases: Record<string, Phase>,
  errors: ErrorCapture,
  basis: RawEvidence
): Observation {
  return {
    phases,
    consoleErrors: errors.consoleErrors,
    pageErrors: errors.pageErrors,
    fontSizes: basis.fontSizes,
    controlSizes: basis.controlSizes,
    horizontalOverflow: basis.horizontalOverflow,
  };
}

async function wait(host: EvidenceHost, milliseconds: number): Promise<void> {
  await host.evaluate(delay => new Promise(resolve => setTimeout(resolve, delay)), milliseconds);
}

/** Read every named phase section from a static reference page. */
export async function observePhases(
  host: EvidenceHost,
  phases: Array<{ name: string; selector: string }>,
  errors: ErrorCapture
): Promise<Observation> {
  const result: Record<string, Phase> = {};
  let basis = await capture(host);
  for (const phase of phases) {
    const evidence = await capture(host, phase.selector);
    result[phase.name] = evidencePhase(evidence, evidence.text);
    basis = evidence;
  }
  return observationOf(result, errors, basis);
}

/** J01 reference: read the shared step, click re-point, read the final step. */
export async function observeJ01Steps(
  host: EvidenceHost,
  errors: ErrorCapture
): Promise<Observation> {
  const phases: Record<string, Phase> = {};
  const shared = await capture(host);
  phases.shared = j01Phase(shared, shared.text);
  await host.getByRole("button", { name: "b = new Object()" }).first().click();
  await wait(host, 50);
  const reassigned = await capture(host);
  phases.reassigned = j01Phase(reassigned, reassigned.text);
  return observationOf(phases, errors, reassigned);
}

/** M01 reference: read x=3, move the input to -1, read again. */
export async function observeM01(
  host: EvidenceHost,
  errors: ErrorCapture
): Promise<Observation> {
  const phases: Record<string, Phase> = {};
  const first = await capture(host);
  phases.x3 = canvasPhase(first, first.text);
  await host.locator("input[data-x]").evaluate((element, value) => {
    const input = element as HTMLInputElement;
    input.value = value;
    input.dispatchEvent(new Event("input", { bubbles: true }));
  }, "-1");
  await wait(host, 60);
  const second = await capture(host);
  phases.xminus1 = canvasPhase(second, second.text);
  return observationOf(phases, errors, second);
}

/**
 * P01 reference: read the resting marker, move to pi/2 and pi, then verify the
 * pause. Each position is derived from the canvas, never from the printed text.
 */
export async function observeP01(
  host: EvidenceHost,
  errors: ErrorCapture
): Promise<Observation> {
  const phases: Record<string, Phase> = {};
  const zero = await capture(host);
  const amplitude = declaredAmplitude(zero.text);
  const zeroPhase = canvasPhase(zero, zero.text);
  phases["phase-zero"] = positionFromCanvas(zeroPhase, zeroPhase, amplitude) ?? zeroPhase;

  const at = async (value: number) => {
    await host.locator("[data-phase]").evaluate((element, next) => {
      const input = element as HTMLInputElement;
      input.value = String(next);
      input.dispatchEvent(new Event("input", { bubbles: true }));
    }, value);
    await wait(host, 60);
    return capture(host);
  };

  const half = await at(Math.PI / 2);
  const measuredHalf = positionFromCanvas(
    phases["phase-zero"],
    canvasPhase(half, half.text),
    amplitude
  );
  if (measuredHalf) phases["pi-half"] = measuredHalf;

  const pi = await at(Math.PI);
  const measuredPi = positionFromCanvas(
    phases["phase-zero"],
    canvasPhase(pi, pi.text),
    amplitude
  );
  if (measuredPi) phases.pi = measuredPi;

  await host.getByRole("button", { name: "播放" }).click();
  await wait(host, 200);
  await host.getByRole("button", { name: "暂停" }).click();
  await wait(host, 120);
  const basis = await capture(host);
  phases["paused-a"] = canvasPhase(basis, basis.text);
  await wait(host, 300);
  phases["paused-b"] = canvasPhase(await capture(host), "");

  return observationOf(phases, errors, basis);
}

/** P01 fault: the free-running animation only needs motion and pause evidence. */
export async function observeP01Fault(
  host: EvidenceHost,
  errors: ErrorCapture
): Promise<Observation> {
  const phases: Record<string, Phase> = {};
  phases["phase-zero"] = canvasPhase(await capture(host), "");
  await wait(host, 220);
  phases["pi-half"] = canvasPhase(await capture(host), "");
  await host.getByRole("button", { name: "暂停" }).click();
  await wait(host, 120);
  const basis = await capture(host);
  phases["paused-a"] = canvasPhase(basis, basis.text);
  await wait(host, 320);
  phases["paused-b"] = canvasPhase(await capture(host), "");
  return observationOf(phases, errors, basis);
}

export const REFERENCE_PHASES: Record<string, Array<{ name: string; selector: string }>> = {
  J02: [{ name: "call", selector: '[data-phase="call"]' }],
  A01: [{ name: "found", selector: '[data-phase="found"]' }],
  A02: [{ name: "result", selector: '[data-phase="result"]' }],
  D01: [
    { name: "committed", selector: '[data-phase="committed"]' },
    { name: "rolled_back", selector: '[data-phase="rolled_back"]' },
  ],
  D02: [
    { name: "interleaved", selector: '[data-phase="interleaved"]' },
    { name: "serialized", selector: '[data-phase="serialized"]' },
  ],
  C01: [{ name: "running", selector: '[data-phase="running"]' }],
  M02: [
    { name: "base", selector: '[data-phase="base"]' },
    { name: "adjusted", selector: '[data-phase="adjusted"]' },
  ],
  S01: [{ name: "metrics", selector: '[data-phase="metrics"]' }],
  N01: [{ name: "complete", selector: '[data-phase="complete"]' }],
};

/** Choose the task-appropriate observation for a reference page. */
export async function observeReference(
  id: string,
  host: EvidenceHost,
  errors: ErrorCapture
): Promise<Observation> {
  if (id === "J01") return observeJ01Steps(host, errors);
  if (id === "M01") return observeM01(host, errors);
  if (id === "P01") return observeP01(host, errors);
  return observePhases(host, REFERENCE_PHASES[id] ?? [], errors);
}

/** Mirror the direct fault observation, but on an already-loaded host. */
export async function observeFault(
  host: EvidenceHost,
  fault: HtmlFault,
  errors: ErrorCapture
): Promise<Observation> {
  if (fault.taskId === "J01") {
    const evidence = await capture(host);
    return observationOf({ reassigned: j01Phase(evidence, evidence.text) }, errors, evidence);
  }
  if (fault.taskId === "M01") return observeM01(host, errors);
  if (fault.taskId === "P01") return observeP01Fault(host, errors);
  if (fault.phases?.length) return observePhases(host, fault.phases, errors);
  const evidence = await capture(host);
  return observationOf({}, errors, evidence);
}
