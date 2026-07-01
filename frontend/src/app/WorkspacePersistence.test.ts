import { describe, expect, it } from "vitest";

import {
  parseWorkspaceRecovery,
  serializeWorkspaceRecovery,
  WORKSPACE_STORAGE_SCHEMA_VERSION,
} from "./WorkspacePersistence";

describe("WorkspacePersistence", () => {
  it("round-trips the versioned workspace envelope", () => {
    const raw = serializeWorkspaceRecovery({
      singleChatSessionId: "chat-1",
      toolRunId: "tool-1",
      ragEnabled: true,
    });
    expect(JSON.parse(raw).schemaVersion).toBe(WORKSPACE_STORAGE_SCHEMA_VERSION);
    expect(parseWorkspaceRecovery(raw)).toMatchObject({
      singleChatSessionId: "chat-1",
      toolRunId: "tool-1",
      ragEnabled: true,
    });
  });

  it("migrates the unversioned legacy payload", () => {
    expect(parseWorkspaceRecovery('{"sessionId":"legacy"}')).toMatchObject({
      sessionId: "legacy",
    });
  });
});
