import { existsSync, mkdirSync, renameSync } from "node:fs";
import { join } from "node:path";

/** Completed observations are immutable; preserve partial attempts before retry. */
export function prepareReplayOutput(root: string, width: number): string | null {
  const out = join(root, `sandbox-${width}`);
  if (existsSync(join(out, "report.json"))) return null;
  if (existsSync(out)) renameSync(out, `${out}.incomplete-${Date.now()}`);
  mkdirSync(out);
  return out;
}
