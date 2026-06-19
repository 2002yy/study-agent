import { describe, expect, it } from "vitest";
import { OperationRegistry } from "./operationRegistry";

describe("OperationRegistry", () => {
  it("cancels the previous operation only in the same scope", () => {
    const registry = new OperationRegistry();

    const chat = registry.start("chat");
    const tool = registry.start("tool");
    const nextChat = registry.start("chat");

    expect(chat.controller.signal.aborted).toBe(true);
    expect(registry.isCurrent(chat.operationId, chat.generationId)).toBe(false);
    expect(tool.controller.signal.aborted).toBe(false);
    expect(registry.isCurrent(tool.operationId, tool.generationId)).toBe(true);
    expect(registry.isCurrent(nextChat.operationId, nextChat.generationId)).toBe(true);
  });

  it("marks completed operations as no longer current", () => {
    const registry = new OperationRegistry();
    const operation = registry.start("news");

    registry.complete(operation.operationId);

    expect(registry.isCurrent(operation.operationId, operation.generationId)).toBe(false);
    expect(registry.isRunning("news")).toBe(false);
    expect(registry.size).toBe(0);
  });

  it("cancels all active scopes for workspace transitions", () => {
    const registry = new OperationRegistry();
    const chat = registry.start("chat");
    const group = registry.start("group");

    registry.cancelAll();

    expect(chat.controller.signal.aborted).toBe(true);
    expect(group.controller.signal.aborted).toBe(true);
    expect(registry.getActiveScopes()).toEqual([]);
    expect(registry.size).toBe(0);
  });

  it("rejects callbacks owned by a different thread", () => {
    const registry = new OperationRegistry();
    const operation = registry.start("chat", "chat-a");

    expect(registry.isCurrent(operation.operationId, operation.generationId, "chat-a")).toBe(true);
    expect(registry.isCurrent(operation.operationId, operation.generationId, "chat-b")).toBe(false);
  });
});
