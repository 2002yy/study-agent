import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const root = resolve(process.cwd(), "src");

function read(path: string): string {
  return readFileSync(resolve(root, path), "utf8");
}

describe("recoverable web research composition", () => {
  it("creates a durable run before execution and keeps same-query retry/resume", () => {
    const entry = read("features/web-lookup/webLookupController.ts");
    const controller = read("features/web-lookup/webLookupControllerCore.ts");
    const createPosition = controller.indexOf("createResearchRun");
    const executePosition = controller.indexOf("executeResearchRun");

    expect(entry).toContain('export { useWebLookupController } from "./webLookupControllerCore"');
    expect(createPosition).toBeGreaterThanOrEqual(0);
    expect(executePosition).toBeGreaterThan(createPosition);
    expect(controller).toContain("const sameQuery");
    expect(controller).toContain("sameQuery && isResumable");
    expect(controller).toContain("sameQuery && isRetryable");
    expect(controller).toContain("cancelResearchRun");
    expect(controller).toContain('operationRegistry.abort("web_lookup")');
  });

  it("keeps all recoverable research HTTP calls in the focused adapter", () => {
    const researchApi = read("features/web-lookup/researchApi.ts");

    expect(researchApi).toContain('"/research-runs"');
    expect(researchApi).toContain("/search");
    expect(researchApi).toContain("/retry");
    expect(researchApi).toContain("/resume");
    expect(researchApi).toContain("/cancel");
    expect(researchApi).toContain("while (current.status === \"running\")");
  });

  it("proxies recoverable research routes to FastAPI in development", () => {
    const viteConfig = readFileSync(resolve(process.cwd(), "vite.config.ts"), "utf8");

    expect(viteConfig).toContain('"/research-runs": API_TARGET');
  });

  it("keeps durable research status in group display while chat owns cancellation", () => {
    const panel = read("features/wechat-workspace/WechatPanel.tsx");
    const chatController = read("features/chat/chatController.ts");

    expect(panel).toContain('searching: "正在广域搜索"');
    expect(panel).toContain('reading: "正在读取网页或源码"');
    expect(panel).toContain("这不代表目标不存在");
    expect(panel).not.toContain("onStopLookup");
    expect(chatController).toContain("cancelChatResearchRuns");
    expect(chatController).toContain("cancelActiveResearch(activeTurnId)");
  });
});
