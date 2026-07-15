import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const viteConfig = readFileSync(
  fileURLToPath(new URL("../../../vite.config.ts", import.meta.url)),
  "utf8"
);

describe("ToolRun development proxy", () => {
  it("forwards the server-owned ToolRun API to FastAPI", () => {
    expect(viteConfig).toContain('"/tool-runs": API_TARGET');
  });

  it("forwards knowledge-base document requests to FastAPI", () => {
    expect(viteConfig).toContain('"/knowledge-base": API_TARGET');
  });
});
