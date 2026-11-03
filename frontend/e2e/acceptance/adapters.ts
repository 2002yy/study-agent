/**
 * Task adapter for J01: derive the observed object counts from the arrows the
 * page actually drew, not from the numbers it prints.
 */
import type { Phase } from "../../src/acceptance/model";
import type { RawEvidence } from "./observer";

export function j01Phase(evidence: RawEvidence, text: string): Phase {
  const arrows = evidence.svg.filter(shape => shape.kind === "arrow");
  const distinctTargets = (fromNode: string): number =>
    new Set(
      arrows
        .filter(arrow => arrow.fromNode === fromNode)
        .map(arrow => arrow.toNode ?? arrow.id)
    ).size;

  return {
    text,
    declared: evidence.declared,
    observed: {
      objectOfA: distinctTargets("node-a"),
      objectOfB: distinctTargets("node-b"),
    },
    svg: evidence.svg,
  };
}
