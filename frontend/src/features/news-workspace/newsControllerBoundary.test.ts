import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const appSource = readFileSync(
  fileURLToPath(new URL("../../App.tsx", import.meta.url)),
  "utf8"
);
const workspaceSource = readFileSync(
  fileURLToPath(new URL("./NewsWorkspace.tsx", import.meta.url)),
  "utf8"
);
const controllerSource = readFileSync(
  fileURLToPath(new URL("./newsController.ts", import.meta.url)),
  "utf8"
);

describe("news controller boundary", () => {
  it("keeps News API orchestration and stage state out of App and NewsWorkspace", () => {
    for (const command of [
      "createNewsRun",
      "searchNewsRun",
      "enrichNewsRun",
      "digestNewsRun",
      "discussNewsRun",
    ]) {
      expect(appSource).not.toMatch(new RegExp(`\\b${command}\\s*\\(`));
      expect(workspaceSource).not.toMatch(new RegExp(`\\b${command}\\s*\\(`));
      expect(controllerSource).toMatch(new RegExp(`\\b${command}\\s*\\(`));
    }
    for (const stateName of ["searchedItems", "enrichedItems", "digestState", "busyStage"]) {
      expect(workspaceSource).not.toContain(`useState(${stateName}`);
    }
  });
});
