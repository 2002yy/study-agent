import { existsSync, readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");

describe("frontend state consolidation boundary", () => {
  it("keeps only production session transitions in the reducer", () => {
    const reducer = read("./workspaceReducer.ts");

    expect(reducer).not.toContain("selectedPanel");
    expect(reducer).not.toContain("SELECT_PANEL");
    expect(reducer).not.toContain("START_NEW_CHAT_SESSION");
  });

  it("uses SettingsPanel directly without legacy layout shells", () => {
    const view = read("./WorkspaceView.tsx");
    const controllers = read("./useWorkspaceControllers.ts");
    const learning = read("./useLearningSessionRuntime.ts");
    const settings = read("../features/settings/SettingsPanel.tsx");

    expect(view).toContain('from "../features/settings/SettingsPanel"');
    expect(view).toContain("<SettingsPanel");
    expect(view).not.toContain("../layout/Sidebar");
    expect(view).not.toContain("<Sidebar");
    expect(learning).toContain('from "../features/settings/SettingsPanel"');
    expect(controllers).not.toContain('from "../features/settings/SettingsPanel"');
    expect(controllers).not.toContain("../layout/Sidebar");
    expect(learning).not.toContain("../layout/Sidebar");

    for (const retiredProp of [
      "ragUploadMode",
      "setRagUploadMode",
      "onNewSession",
      "onUploadClick",
      "uploadState",
    ]) {
      expect(settings).not.toContain(retiredProp);
    }

    expect(existsSync(new URL("../layout/Sidebar.tsx", import.meta.url))).toBe(false);
    expect(existsSync(new URL("../layout/Inspector.tsx", import.meta.url))).toBe(false);
  });
});
