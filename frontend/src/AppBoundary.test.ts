import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const appSource = readFileSync(
  fileURLToPath(new URL("./App.tsx", import.meta.url)),
  "utf8"
);
const shellSource = readFileSync(
  fileURLToPath(new URL("./AppShell.tsx", import.meta.url)),
  "utf8"
);
const runtimeSource = readFileSync(
  fileURLToPath(new URL("./app/WorkspaceRuntime.tsx", import.meta.url)),
  "utf8"
);

describe("App shell boundary", () => {
  it("keeps App as a composition boundary under 250 lines", () => {
    expect(appSource.split(/\r?\n/).length).toBeLessThanOrEqual(250);
    expect(appSource).toContain("<WorkspaceRuntime");
  });

  it("does not own feature state or API orchestration", () => {
    expect(appSource).not.toMatch(/\buseState\s*\(/);
    expect(appSource).not.toMatch(/\b(load|save|create|archive)\w*\s*\(/);
  });

  it("keeps AppShell as a small layout-only component", () => {
    expect(shellSource.split(/\r?\n/).length).toBeLessThanOrEqual(50);
    expect(shellSource).not.toContain("localStorage");
    expect(shellSource).not.toMatch(/from ["'].\/api["']/);
    expect(shellSource).not.toContain("useState");
    expect(shellSource).toContain('className="app-shell"');
  });

  it("keeps runtime side effects behind dedicated boundaries", () => {
    expect(runtimeSource).not.toContain("localStorage");
    expect(runtimeSource).not.toContain("SESSION_STORAGE_KEY");
    expect(runtimeSource).not.toContain("loadApiSnapshot");
    expect(runtimeSource).not.toContain("serverQueryCache");
    expect(runtimeSource).toContain("useWorkspaceBootstrap()");
    expect(runtimeSource).toContain("useWorkspacePersistence({");
    expect(runtimeSource).toContain("new WorkspaceCoordinator(");
  });
});
