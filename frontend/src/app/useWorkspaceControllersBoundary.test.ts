import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const runtimeSource = readFileSync(
  fileURLToPath(new URL("./WorkspaceRuntime.tsx", import.meta.url)),
  "utf8"
);
const compositionSource = readFileSync(
  fileURLToPath(new URL("./useWorkspaceControllers.ts", import.meta.url)),
  "utf8"
);

const controllerHooks = [
  "useRoleController",
  "useWorkflowController",
  "useSettingsController",
  "useGroupChatController",
  "useNewsController",
  "useWebLookupController",
  "useMemoryController",
  "useRagController",
  "useUploadController",
  "useChatController",
  "useToolController",
];

describe("workspace controller composition boundary", () => {
  it("owns every feature-controller constructor outside WorkspaceRuntime", () => {
    for (const hook of controllerHooks) {
      expect(compositionSource).toContain(`${hook}(`);
      expect(runtimeSource).not.toContain(`${hook}(`);
      expect(runtimeSource).not.toMatch(
        new RegExp(`import .*${hook}`)
      );
    }
  });

  it("owns cross-feature cancellation and artifact cleanup", () => {
    expect(compositionSource).toContain("new WorkspaceCoordinator(");
    expect(compositionSource).toContain("clearChatArtifacts:");
    expect(compositionSource).toContain("onWorkspaceCancelled:");
    expect(runtimeSource).not.toContain("new WorkspaceCoordinator(");
  });
});
