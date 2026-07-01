import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const appSource = readFileSync(
  fileURLToPath(new URL("./App.tsx", import.meta.url)),
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
});
