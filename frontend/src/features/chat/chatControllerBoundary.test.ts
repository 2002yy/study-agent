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

function sectionBetween(start: string, end: string): string {
  const tail = controllerSource.split(start)[1] ?? "";
  return tail.split(end)[0] ?? tail;
}

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

  it("cancels only the chat scope during session transitions", () => {
    const cancellation = sectionBetween(
      "const cancelWorkspaceRuns",
      "const send = async"
    );
    expect(cancellation).toContain('operationRegistry.invalidate("chat")');
    expect(cancellation).not.toContain("operationRegistry.cancelAll()");
  });

  it("does not archive the active thread when starting a new session", () => {
    const startNewSession = sectionBetween(
      "const startNewSession = async",
      "return {"
    );
    expect(startNewSession).toContain("const created = await createNewSession()");
    expect(startNewSession).not.toContain("archiveSession(state.activeChatThreadId)");
    expect(startNewSession).not.toContain("loadSessionDetail(state.activeChatThreadId)");
  });

  it("restores committed learning state and ignores uncommitted phase history", () => {
    const restore = sectionBetween(
      "const applySessionDetail",
      "const restoreSession = async"
    );
    expect(restore).toContain("learning_state: committedLearningState");
    expect(restore).toContain('.filter((turn) => turn.status === "completed")');
    expect(restore).toContain("committed_learning_state");
  });
});
