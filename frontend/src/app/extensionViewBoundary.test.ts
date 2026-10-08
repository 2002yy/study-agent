import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const sourceOf = (relativePath: string) => {
  const path = fileURLToPath(new URL(relativePath, import.meta.url));
  return existsSync(path) ? readFileSync(path, "utf8") : "";
};

const runtimeSource = sourceOf("./WorkspaceRuntime.tsx");
const workspaceViewSource = sourceOf("./WorkspaceView.tsx");
const controllerCompositionSource = sourceOf("./useWorkspaceControllers.ts");
const extensionRuntimeSource = sourceOf("./useExtensionRuntime.ts");
const extensionDrawersSource = sourceOf("./ExtensionDrawers.tsx");
const chatPanelSource = sourceOf("../features/single-chat/WorkspaceActions.tsx");
const launcherSource = sourceOf("../features/extensions/ExtensionLauncher.tsx");
const labPanelSource = sourceOf("../features/extensions/ExtensionLabPanel.tsx");

describe("Extension view ownership boundary", () => {
  it("passes one Extension view model from Runtime to WorkspaceView", () => {
    expect(extensionRuntimeSource).toContain("export type ExtensionViewModel");
    expect(extensionRuntimeSource).toContain("const view:");
    expect(extensionRuntimeSource).toContain("activeSurface,");
    expect(extensionRuntimeSource).toContain("activeCapability,");
    expect(extensionRuntimeSource).toContain("group:");
    expect(extensionRuntimeSource).toContain("tools:");
    expect(extensionRuntimeSource).toContain("timeline:");
    expect(runtimeSource).toContain("extensionView={extension.view}");
    expect(workspaceViewSource).toContain("extensionView: ExtensionViewModel");
  });

  it("keeps panel binding out of WorkspaceView and controller composition", () => {
    expect(extensionDrawersSource).toContain("<WechatPanel");
    expect(extensionDrawersSource).toContain("<ToolPanel");
    expect(extensionDrawersSource).toContain("<TimelinePanel");
    expect(workspaceViewSource).toContain("<ExtensionDrawers");

    for (const owner of [
      "WechatPanel",
      "ToolPanel",
      "TimelinePanel",
      "groupController",
      "toolController",
      "workflowController",
      "groupThreadId",
    ]) {
      expect(workspaceViewSource).not.toContain(owner);
      expect(controllerCompositionSource).not.toContain(owner);
    }
  });

  it("uses an explicit capability contract and does not load the lab home", () => {
    expect(extensionRuntimeSource).toContain("selectExtensionSurface(state.activeDrawer)");
    expect(extensionRuntimeSource).toContain("if (!activeCapability) return;");
    expect(extensionRuntimeSource).toContain("EXTENSION_DRAWER_CONFIG[activeCapability]");
    expect(extensionRuntimeSource).not.toContain('["group", "tools", "timeline"].includes');
  });

  it("isolates experimental choices behind one laboratory launcher", () => {
    expect(launcherSource).toContain("export function ExtensionLauncher");
    expect(launcherSource).toContain("onOpen(LAB_DRAWER");
    expect(launcherSource).not.toContain('onOpen("group"');
    expect(launcherSource).not.toContain('onOpen("tools"');
    expect(launcherSource).not.toContain('onOpen("timeline"');
    expect(labPanelSource).toContain('id: "group"');
    expect(labPanelSource).toContain('id: "tools"');
    expect(labPanelSource).toContain('id: "timeline"');
    expect(chatPanelSource).toContain("<ExtensionLauncher");
    expect(chatPanelSource).not.toContain('openFromMenu("group"');
    expect(chatPanelSource).not.toContain('openFromMenu("tools"');
    expect(chatPanelSource).not.toContain('openFromMenu("timeline"');
  });
});
