import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const sourceOf = (relativePath: string) => {
  const path = fileURLToPath(new URL(relativePath, import.meta.url));
  return existsSync(path) ? readFileSync(path, "utf8") : "";
};

const chatPanelSource = sourceOf("../features/single-chat/WorkspaceActions.tsx");
const launcherSource = sourceOf("../features/extensions/ExtensionLauncher.tsx");
const contractSource = sourceOf("../features/extensions/extensionDrawerContract.ts");
const labPanelSource = sourceOf("../features/extensions/ExtensionLabPanel.tsx");
const runtimeSource = sourceOf("./useExtensionRuntime.ts");
const drawersSource = sourceOf("./ExtensionDrawers.tsx");

describe("single laboratory product boundary", () => {
  it("keeps one laboratory entry in the ordinary learning menu", () => {
    expect(contractSource).toContain('export const LAB_DRAWER: DrawerId = "lab"');
    expect(chatPanelSource).toContain("<ExtensionLauncher");
    expect(launcherSource).toContain("onOpen(LAB_DRAWER");
    expect(launcherSource).toContain("实验室");
    expect(launcherSource).not.toContain('onOpen("group"');
    expect(launcherSource).not.toContain('onOpen("tools"');
    expect(launcherSource).not.toContain('onOpen("timeline"');
  });

  it("owns experimental choices inside the laboratory panel", () => {
    expect(labPanelSource).toContain("export function ExtensionLabPanel");
    expect(labPanelSource).toContain("群聊讨论");
    expect(labPanelSource).toContain("受控工具");
    expect(labPanelSource).toContain("开发者诊断");
    expect(labPanelSource).toContain("onSelect");
    expect(drawersSource).toContain("<ExtensionLabPanel");
  });

  it("keeps the laboratory home dormant until one capability is selected", () => {
    expect(runtimeSource).toContain("activeCapability");
    expect(runtimeSource).toContain("selectCapability");
    expect(runtimeSource).toContain("if (!activeCapability) return;");
    expect(runtimeSource).toContain("EXTENSION_DRAWER_CONFIG[activeCapability]");
    expect(drawersSource).toContain('view.activeSurface === "lab"');
  });

  it("does not retain legacy capability drawer surfaces", () => {
    expect(runtimeSource).not.toContain("selectExtensionDrawer");
    expect(drawersSource).not.toContain("isLegacySurface");
    expect(launcherSource).not.toContain('onOpen("group"');
    expect(launcherSource).not.toContain('onOpen("tools"');
    expect(launcherSource).not.toContain('onOpen("timeline"');
  });
});
