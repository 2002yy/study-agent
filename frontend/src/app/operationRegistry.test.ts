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

  it("keeps upload, memory and research work alive when chat is invalidated", () => {
    const registry = new OperationRegistry();
    const chat = registry.start("chat", "chat-a");
    const upload = registry.start("rag-upload", "upload-a");
    const memory = registry.start("memory", "memory-a");
    const research = registry.start("web_lookup", "research-a");

    registry.invalidate("chat");

    expect(chat.controller.signal.aborted).toBe(true);
    expect(registry.isCurrent(chat.operationId, chat.generationId, "chat-a")).toBe(false);
    expect(registry.isCurrent(upload.operationId, upload.generationId, "upload-a")).toBe(true);
    expect(registry.isCurrent(memory.operationId, memory.generationId, "memory-a")).toBe(true);
    expect(registry.isCurrent(research.operationId, research.generationId, "research-a")).toBe(true);
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

  it("preserves ownership for user abort settlement", () => {
    const registry = new OperationRegistry();
    const operation = registry.start("chat", "chat-a");

    registry.abort("chat");

    expect(operation.controller.signal.aborted).toBe(true);
    expect(registry.isCurrent(operation.operationId, operation.generationId, "chat-a")).toBe(false);
    expect(registry.isOwned(operation.operationId, operation.generationId, "chat-a")).toBe(true);
    expect(registry.size).toBe(1);
  });

  it("invalidates old settlement when a replacement starts", () => {
    const registry = new OperationRegistry();
    const first = registry.start("chat", "chat-a");
    const second = registry.start("chat", "chat-a");

    expect(registry.isOwned(first.operationId, first.generationId, "chat-a")).toBe(false);
    expect(registry.isCurrent(second.operationId, second.generationId, "chat-a")).toBe(true);
  });

  it("invalidates a cancelling operation during a workspace transition", () => {
    const registry = new OperationRegistry();
    const operation = registry.start("chat", "chat-a");

    registry.abort("chat");
    registry.cancelAll();

    expect(registry.isOwned(operation.operationId, operation.generationId, "chat-a")).toBe(false);
    expect(registry.size).toBe(0);
  });

  it("invalidates a cancelling operation when a replacement starts", () => {
    const registry = new OperationRegistry();
    const first = registry.start("chat", "chat-a");

    registry.abort("chat");
    const second = registry.start("chat", "chat-a");

    expect(registry.isOwned(first.operationId, first.generationId, "chat-a")).toBe(false);
    expect(registry.isCurrent(second.operationId, second.generationId, "chat-a")).toBe(true);
    expect(registry.size).toBe(1);
  });
});
