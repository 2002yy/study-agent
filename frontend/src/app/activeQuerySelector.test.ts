import { readdirSync, readFileSync, statSync } from "node:fs";
import { relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { selectActiveQuery } from "./activeQuerySelector";

const srcRoot = fileURLToPath(new URL("../", import.meta.url));
const compositionSource = readFileSync(
  fileURLToPath(new URL("./useWorkspaceControllers.ts", import.meta.url)),
  "utf8",
);
const extensionSource = readFileSync(
  fileURLToPath(new URL("./useExtensionRuntime.ts", import.meta.url)),
  "utf8",
);
const viewSource = readFileSync(
  fileURLToPath(new URL("./WorkspaceView.tsx", import.meta.url)),
  "utf8",
);
const selectorSource = readFileSync(
  fileURLToPath(new URL("./activeQuerySelector.ts", import.meta.url)),
  "utf8",
);

function productionFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = resolve(dir, name);
    if (statSync(path).isDirectory()) return productionFiles(path);
    if (!/\.(ts|tsx)$/.test(name) || /\.(test|spec)\.(ts|tsx)$/.test(name)) return [];
    return [path];
  });
}

describe("active query selector", () => {
  it("prefers trimmed current input", () => {
    expect(
      selectActiveQuery({ input: "  当前问题  ", lastRagQuery: "上一轮问题" }),
    ).toBe("当前问题");
  });

  it("falls back to the trimmed latest RAG query", () => {
    expect(
      selectActiveQuery({ input: "   ", lastRagQuery: "  上一轮问题  " }),
    ).toBe("上一轮问题");
  });

  it("returns an empty query when neither source is usable", () => {
    expect(selectActiveQuery({ input: "\n", lastRagQuery: "  " })).toBe("");
    expect(selectActiveQuery({ input: "" })).toBe("");
  });

  it("is the single production derivation shared by Sources and tools", () => {
    expect(extensionSource).toContain(
      'import { selectActiveQuery } from "./activeQuerySelector";',
    );
    expect(extensionSource).toContain("const activeQuery = selectActiveQuery({");
    expect(extensionSource).toContain("input: options.input,");
    expect(extensionSource).toContain("lastRagQuery: options.lastRagQuery,");
    expect(extensionSource).toContain("query: activeQuery,");
    expect(extensionSource).toContain("activeQuery,");
    expect(extensionSource).not.toContain(
      'options.input.trim() || options.lastRagQuery || ""',
    );
    expect(compositionSource).not.toContain(
      'import { selectActiveQuery } from "./activeQuerySelector";',
    );
    expect(compositionSource).not.toContain("activeQuery,");
    expect(selectorSource).not.toContain('from "react"');
    expect(selectorSource).toContain("const currentInput = input.trim();");
    expect(selectorSource).toContain('return lastRagQuery?.trim() ?? "";');

    const declarationOwners = productionFiles(srcRoot).flatMap((path) =>
      readFileSync(path, "utf8").includes("const activeQuery =")
        ? [relative(srcRoot, path).split(sep).join("/")]
        : [],
    );
    expect(declarationOwners).toEqual(["app/useExtensionRuntime.ts"]);

    expect(viewSource).not.toContain("onSearchSources=");
    expect(viewSource).toContain("await chatController.send(question ?? ui.input.trim())");
  });
});
