import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const lessonSource = readFileSync(
  fileURLToPath(new URL("./FireflyDefaultLesson.tsx", import.meta.url)),
  "utf8",
);
const modelSource = readFileSync(
  fileURLToPath(new URL("./defaultFireflyLesson.ts", import.meta.url)),
  "utf8",
);
const visibleCopy = `${lessonSource}\n${modelSource}`;

describe("Firefly default lesson copy contract", () => {
  it("does not regress to the old database-index default material", () => {
    expect(visibleCopy).not.toContain("数据库索引");
  });

  it("avoids the frozen template-like teaching phrases", () => {
    expect(visibleCopy).not.toContain("本节学习");
    expect(visibleCopy).not.toContain("核心在于");
    expect(visibleCopy).not.toContain("本质上");
    expect(visibleCopy).not.toMatch(/不是[^。\n]{0,36}而是/);
  });

  it("keeps the visible route vocabulary aligned with the four required stages", () => {
    expect(lessonSource).toContain('"起步"');
    expect(lessonSource).toContain('"低金"');
    expect(lessonSource).toContain('"老牌配置"');
    expect(lessonSource).toContain('"高配"');
  });
});
