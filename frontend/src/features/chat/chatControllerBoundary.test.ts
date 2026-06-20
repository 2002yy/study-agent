import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const appSource = readFileSync(
  fileURLToPath(new URL("../../App.tsx", import.meta.url)),
  "utf8"
);
const controllerSource = readFileSync(
  fileURLToPath(new URL("./chatController.ts", import.meta.url)),
  "utf8"
);

describe("chat controller ownership boundary", () => {
  it("keeps chat orchestration commands out of App", () => {
    for (const command of [
      "sendChatStream",
      "commitTurn",
      "loadSessionDetail",
      "archiveSession",
      "createNewSession",
    ]) {
      const invocation = new RegExp(`\\b${command}\\s*\\(`);
      expect(appSource).not.toMatch(invocation);
      expect(controllerSource).toMatch(invocation);
    }
  });

  it("keeps sending state and operation ownership in the controller", () => {
    expect(appSource).not.toContain("setIsSending");
    expect(controllerSource).toContain("const [isSending, setIsSending]");
    expect(controllerSource).toMatch(/operationRegistry\.start\(\s*"chat"/);
  });
});
