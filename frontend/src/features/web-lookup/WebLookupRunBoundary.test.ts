import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const root = resolve(process.cwd(), "src");

describe("recoverable web research composition", () => {
  it("creates a durable run before searching and exposes same-run retry", () => {
    const controller = readFileSync(
      resolve(root, "features/web-lookup/webLookupController.ts"),
      "utf8",
    );
    const createPosition = controller.indexOf("createResearchRun");
    const searchPosition = controller.indexOf("searchResearchRun");

    expect(createPosition).toBeGreaterThanOrEqual(0);
    expect(searchPosition).toBeGreaterThan(createPosition);
    expect(controller).toContain("retryResearchRun");
    expect(controller).toContain("loadResearchRun");
    expect(controller).toContain("RETRYABLE_STATUSES");
  });

  it("shows durable status and a visible retry action", () => {
    const panel = readFileSync(
      resolve(root, "features/wechat-workspace/WechatPanel.tsx"),
      "utf8",
    );
    expect(panel).toContain("研究状态");
    expect(panel).toContain("重试本次研究");
    expect(panel).toContain("这不代表目标不存在");
    expect(panel).toContain("attempts?.length");
  });

  it("keeps research HTTP calls inside a focused feature adapter", () => {
    const researchApi = readFileSync(
      resolve(root, "features/web-lookup/researchApi.ts"),
      "utf8",
    );
    expect(researchApi).toContain('"/research-runs"');
    expect(researchApi).toContain("/search");
    expect(researchApi).toContain("/retry");
  });
});
