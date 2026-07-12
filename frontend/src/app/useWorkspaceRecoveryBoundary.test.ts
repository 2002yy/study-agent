import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const runtimeSource = readFileSync(
  fileURLToPath(new URL("./WorkspaceRuntime.tsx", import.meta.url)),
  "utf8"
);
const recoverySource = readFileSync(
  fileURLToPath(new URL("./useWorkspaceRecovery.ts", import.meta.url)),
  "utf8"
);
const viewSource = readFileSync(
  fileURLToPath(new URL("./WorkspaceView.tsx", import.meta.url)),
  "utf8"
);

describe("workspace recovery and view boundaries", () => {
  it("owns restore, server hydration and persistence outside Runtime", () => {
    for (const token of [
      "useWorkspacePersistence({",
      "hydrateSession(",
      "runtimeSettings?.settings",
      "sessionSettingsRestoredRef",
    ]) {
      expect(recoverySource).toContain(token);
      expect(runtimeSource).not.toContain(token);
    }
  });

  it("owns feature view binding outside Runtime", () => {
    for (const component of [
      "<Sidebar",
      "<ChatPanel",
      "<LearningPanel",
      "<SlideOver",
      "<GlobalNotices",
    ]) {
      expect(viewSource).toContain(component);
      expect(runtimeSource).not.toContain(component);
    }
  });
});
