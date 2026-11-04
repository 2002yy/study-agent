/**
 * Task adapters derive `observed` values from what the page really drew.
 *
 * J01 reads object identity from arrows. P01 reads the canvas marker position
 * and converts it to task units using the amplitude reference the page drew,
 * so the number printed by the page is never used as its own evidence.
 */
import type { Phase } from "../../src/acceptance/model";
import type { RawEvidence } from "./observer";

export function j01Phase(evidence: RawEvidence, text: string): Phase {
  const arrows = evidence.svg.filter(shape => shape.kind === "arrow");
  const targetIndex = (shape: (typeof arrows)[number] | undefined): number | undefined => {
    const target = shape?.toNode;
    if (!target) return undefined;
    if (target === "node-a") return 1;
    if (target === "node-new-object") return 2;
    const numbered = /^node-object-(\d+)$/.exec(target);
    return numbered ? Number(numbered[1]) : undefined;
  };
  const fromNode = (node: string, preferred: string) =>
    arrows.find(arrow => arrow.id === preferred && arrow.fromNode === node) ??
    arrows.find(arrow => arrow.fromNode === node);

  const observed: Record<string, number> = {};
  const aTarget = targetIndex(fromNode("node-a", "arrow-a"));
  const bTarget = targetIndex(fromNode("node-b", "arrow-b"));
  if (aTarget !== undefined) observed.objectOfA = aTarget;
  if (bTarget !== undefined) observed.objectOfB = bTarget;

  return {
    text,
    declared: evidence.declared,
    observed,
    svg: evidence.svg,
  };
}

function canvasFields(evidence: RawEvidence) {
  const pixels = evidence.canvases
    .map(canvas => canvas.pixels)
    .filter((value): value is number[] => Array.isArray(value));
  const marker = evidence.canvases.find(canvas => canvas.marker)?.marker;
  const verticalMarks = evidence.canvases.flatMap(canvas => canvas.verticalMarks);
  return {
    ...(pixels.length ? { pixels } : {}),
    ...(marker ? { marker: { x: marker.x, y: marker.y } } : {}),
    ...(verticalMarks.length ? { verticalMarks } : {}),
  };
}

/** Canvas phase: pixels, marker position and amplitude marks are the evidence. */
export function evidencePhase(evidence: RawEvidence, text: string): Phase {
  const canvas = canvasFields(evidence);
  return {
    text,
    declared: evidence.declared,
    observed: evidence.observed,
    svg: evidence.svg,
    ...(canvas.pixels ? { canvas } : {}),
  };
}

export const canvasPhase = evidencePhase;

/** The amplitude the page states, used only to turn pixels into task units. */
export function declaredAmplitude(text: string): number | null {
  const match = /振幅\s*A?\s*[=:：]?\s*(-?\d+(?:\.\d+)?)/.exec(text.replace(/\s+/g, " "));
  return match ? Number(match[1]) : null;
}

/**
 * Find the pair of amplitude marks that is symmetric around the marker's rest
 * position. The pair with the widest span wins, which rejects a fixed support
 * or other single vertical stroke far from the centre.
 */
function amplitudeScale(
  centreX: number,
  marks: number[]
): { centre: number; half: number } | null {
  const sorted = Array.from(new Set(marks)).sort((a, b) => a - b);
  const pairs: Array<{ centre: number; half: number }> = [];
  for (let left = 0; left < sorted.length; left++) {
    for (let right = left + 1; right < sorted.length; right++) {
      const half = (sorted[right] - sorted[left]) / 2;
      if (half < 8) continue;
      const centre = (sorted[left] + sorted[right]) / 2;
      if (Math.abs(centre - centreX) > Math.max(6, half * 0.15)) continue;
      pairs.push({ centre, half });
    }
  }
  if (!pairs.length) return null;
  const widest = pairs.reduce((best, pair) => (pair.half > best.half ? pair : best));
  // Two symmetric pairs of different spans mean the page has several
  // plausible scales; choosing one would be a guess.
  if (pairs.some(pair => Math.abs(pair.half - widest.half) > 2)) return null;
  return widest;
}

/**
 * Convert the marker's displacement into task units. `zero` is the resting
 * phase; `target` is the phase to read. Returns null when the page gives no
 * amplitude reference, so the judge keeps the check indeterminate.
 */
export function positionFromCanvas(
  zero: Phase,
  target: Phase,
  amplitude: number | null
): Phase | null {
  const marker = target.canvas?.marker;
  const rest = zero.canvas?.marker;
  const marks = zero.canvas?.verticalMarks ?? [];
  if (!marker || !rest || amplitude == null) return null;
  if (!Number.isFinite(amplitude) || amplitude <= 0) return null;
  const scale = amplitudeScale(rest.x, marks);
  if (!scale) return null;
  const position = ((marker.x - scale.centre) / scale.half) * amplitude;
  return {
    ...target,
    observed: { ...target.observed, position: Number(position.toFixed(3)) },
  };
}
