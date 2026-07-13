import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const root = resolve(process.cwd(), "src");

function read(path: string): string {
  return readFileSync(resolve(root, path), "utf8");
}

describe("recoverable web research composition", () => {
  it("creates a durable run before execution and keeps same-query retry/resume", () => {
    const controller = read("features/web-lookup/webLookupController.ts");
    const createPosition = controller.indexOf("createResearchRun");
    const executePosition = controller.indexOf("executeResearchRun");

    expect(createPosition).toBeGreaterThanOrEqual(0);
    expect(executePosition).toBeGreaterThan(createPosition);
    expect(controller).toContain("const sameQuery");
    expect(controller).toContain("sameQuery && isResumable");
    expect(controller).toContain("sameQuery && isRetryable");
    expect(controller).toContain("cancelResearchRun");
  });

  it("keeps all recoverable research HTTP calls in the focused adapter", () => {
    const researchApi = read("features/web-lookup/researchApi.ts");

    expect(researchApi).toContain('"/research-runs"');
    expect(researchApi).toContain("/search");
    expect(researchApi).toContain("/retry");
    expect(researchApi).toContain("/resume");
    expect(researchApi).toContain("/cancel");
  });

  it("shows durable stages and exposes a server-side stop action", () => {
    const panel = read("features/wechat-workspace/WechatPanel.tsx");
    const workspace = read("features/news-workspace/NewsWorkspace.tsx");

    expect(panel).toContain('searching: "正在广域搜索"');
    expect(panel).toContain('reading: "正在读取网页或源码"');
    expect(panel).toContain("这不代表目标不存在");
    expect(panel).toContain("onStopLookup");
    expect(workspace).toContain("停止研究");
  });
});
