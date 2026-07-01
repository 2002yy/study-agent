import { describe, expect, it, vi } from "vitest";

import { WorkspaceCoordinator } from "./WorkspaceCoordinator";

describe("WorkspaceCoordinator", () => {
  it("cancels every active feature through one command", () => {
    const ports = {
      cancelChat: vi.fn(),
      cancelGroup: vi.fn(),
      cancelNews: vi.fn(),
      cancelWebLookup: vi.fn(),
      invalidateTool: vi.fn(),
    };
    const coordinator = new WorkspaceCoordinator(ports, {
      clearRag: vi.fn(),
      clearToolRun: vi.fn(),
      clearWorkflow: vi.fn(),
    });
    coordinator.cancelAllActiveOperations();
    expect(Object.values(ports).every((port) => port.mock.calls.length === 1)).toBe(true);
  });

  it("clears cross-feature artifacts without knowing feature internals", () => {
    const artifacts = {
      clearRag: vi.fn(),
      clearToolRun: vi.fn(),
      clearWorkflow: vi.fn(),
    };
    const coordinator = new WorkspaceCoordinator(
      {
        cancelChat: vi.fn(),
        cancelGroup: vi.fn(),
        cancelNews: vi.fn(),
        cancelWebLookup: vi.fn(),
        invalidateTool: vi.fn(),
      },
      artifacts
    );
    coordinator.clearChatArtifacts();
    expect(Object.values(artifacts).every((port) => port.mock.calls.length === 1)).toBe(true);
  });
});
