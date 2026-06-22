import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const appSource = readFileSync(
  fileURLToPath(new URL("../../App.tsx", import.meta.url)),
  "utf8"
);
const controllerSource = readFileSync(
  fileURLToPath(new URL("./toolController.ts", import.meta.url)),
  "utf8"
);

describe("tool controller boundary", () => {
  it("keeps ToolRun API orchestration and stage state out of App", () => {
    for (const command of ["createToolRun", "callToolRun", "getToolRun"]) {
      expect(appSource).not.toMatch(new RegExp(`\\b${command}\\s*\\(`));
      expect(controllerSource).toMatch(new RegExp(`\\b${command}\\s*\\(`));
    }
    for (const stateName of ["toolPreview", "toolCall", "previewedInvocation"]) {
      expect(appSource).not.toContain(`useState(${stateName}`);
    }
  });
});
