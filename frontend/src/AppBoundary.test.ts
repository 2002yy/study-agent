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

describe("App shell boundary", () => {
  it("keeps App as a composition boundary under 250 lines", () => {
    expect(appSource.split(/\r?\n/).length).toBeLessThanOrEqual(250);
    expect(appSource).toContain("<AppShell");
  });

  it("does not own feature state or API orchestration", () => {
    expect(appSource).not.toMatch(/\buseState\s*\(/);
    expect(appSource).not.toMatch(/\b(load|save|create|archive)\w*\s*\(/);
  });

  it("prevents runtime persistence and server loading from returning to AppShell", () => {
    // Ratchet only: layout extraction will lower this ceiling in later slices.
    expect(shellSource.split(/\r?\n/).length).toBeLessThanOrEqual(1100);
    expect(shellSource).not.toContain("localStorage");
    expect(shellSource).not.toContain("SESSION_STORAGE_KEY");
    expect(shellSource).not.toContain("loadApiSnapshot");
    expect(shellSource).not.toContain("serverQueryCache");
    expect(shellSource).toContain("useWorkspaceBootstrap()");
    expect(shellSource).toContain("useWorkspacePersistence({");
    expect(shellSource).toContain("new WorkspaceCoordinator(");
  });
});
