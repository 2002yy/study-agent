import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const read = (path: string) =>
  readFileSync(fileURLToPath(new URL(path, import.meta.url)), "utf8");

const wrapperSource = read("./FireflyDefaultLesson.tsx");
const lessonSource = read("./FireflyMechanicsLesson.tsx");
const modelSource = read("./defaultFireflyLesson.ts");
const mechanicsModelSource = read("./fireflyLessonModel.ts");
const doupoSource = read("./DoupoDefaultLesson.tsx");
const stripSource = read("./LearningStrip.tsx");
const visibleCopy = `${wrapperSource}\n${lessonSource}\n${modelSource}\n${mechanicsModelSource}`;
const doupoVisibleCopy = `${wrapperSource}\n${doupoSource}\n${stripSource}`;

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

describe("Doupo delight-loop copy contract", () => {
  it("does not present the narrative analysis as a lesson, quiz, experiment, or grading system", () => {
    expect(doupoVisibleCopy).not.toContain("教学量表");
    expect(doupoVisibleCopy).not.toContain("课程目标");
    expect(doupoVisibleCopy).not.toContain("标准答案");
    expect(doupoVisibleCopy).not.toContain("先预测再对照");
    expect(doupoVisibleCopy).not.toContain("重新估值七门");
    expect(doupoVisibleCopy).not.toContain("诊断");
  });

  it("keeps the visible frame centered on the delight-loop mechanics", () => {
    expect(doupoSource).toContain("爽点循环总图");
    expect(doupoSource).toContain("旧估值");
    expect(doupoSource).toContain("公开硬证据");
    expect(doupoSource).toContain("回溯重构");
    expect(stripSource).toContain("旧账 → 兑现 → 新债");
  });
});
