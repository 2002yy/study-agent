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
      learningClosureRunId: "closure-1",
      ragEnabled: true,
    });
    expect(JSON.parse(raw).schemaVersion).toBe(WORKSPACE_STORAGE_SCHEMA_VERSION);
    expect(parseWorkspaceRecovery(raw)).toMatchObject({
      singleChatSessionId: "chat-1",
      toolRunId: "tool-1",
      learningClosureRunId: "closure-1",
      ragEnabled: true,
    });
  });

  it("reads a previous versioned envelope after a schema upgrade", () => {
    expect(
      parseWorkspaceRecovery(
        JSON.stringify({
          schemaVersion: 2,
          savedAt: "2026-07-14T00:00:00Z",
          workspace: {
            singleChatSessionId: "chat-v2",
            memoryRunId: "memory-v2",
          },
        })
      )
    ).toMatchObject({
      singleChatSessionId: "chat-v2",
      memoryRunId: "memory-v2",
    });
  });

  it("migrates the unversioned legacy payload", () => {
    expect(parseWorkspaceRecovery('{"sessionId":"legacy"}')).toMatchObject({
      sessionId: "legacy",
    });
  });
});
