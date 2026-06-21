import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const appSource = readFileSync(
  fileURLToPath(new URL("../../App.tsx", import.meta.url)),
  "utf8"
);
const controllerSource = readFileSync(
  fileURLToPath(new URL("./groupChatController.ts", import.meta.url)),
  "utf8"
);

describe("group controller boundary", () => {
  it("keeps Group API orchestration out of App", () => {
    for (const command of [
      "createWechatOpening",
      "resetWechat",
      "markWechatRead",
      "sendWechatMessageStream",
    ]) {
      expect(appSource).not.toMatch(new RegExp(`\\b${command}\\s*\\(`));
      expect(controllerSource).toMatch(new RegExp(`\\b${command}\\s*\\(`));
    }
    expect(appSource).not.toContain("setIsWechatBusy");
  });
});
