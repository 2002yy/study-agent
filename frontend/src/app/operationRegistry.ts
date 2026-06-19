/**
 * Central async operation registry.
 *
 * Rules:
 * - start(scope) cancels the previous operation in the same scope.
 * - Different scopes do not invalidate each other.
 * - cancelAll() is reserved for workspace/session transitions.
 * - Async callbacks must check isCurrent(operationId, generationId).
 */

export type OperationScope =
  | "chat"
  | "group"
  | "news"
  | "tool"
  | "rag-search"
  | "rag-upload"
  | "memory"
  | "session-transition";

export type OperationState = {
  id: string;
  scope: OperationScope;
  status: "running" | "cancelling" | "completed" | "failed";
  ownerId?: string;
  controller: AbortController;
  generationId: number;
  startedAt: number;
};

let _nextId = 0;

function nextId(): string {
  return `op-${Date.now()}-${++_nextId}`;
}

export class OperationRegistry {
  private operations = new Map<string, OperationState>();
  private scopeGenerations = new Map<OperationScope, number>();

  /** Start a new operation and cancel the previous operation in the same scope. */
  start(scope: OperationScope, ownerId?: string): {
    operationId: string;
    controller: AbortController;
    generationId: number;
  } {
    this.cancel(scope);

    const gen = (this.scopeGenerations.get(scope) ?? 0) + 1;
    this.scopeGenerations.set(scope, gen);

    const id = nextId();
    const controller = new AbortController();

    this.operations.set(id, {
      id,
      scope,
      status: "running",
      ownerId,
      controller,
      generationId: gen,
      startedAt: Date.now(),
    });

    return { operationId: id, controller, generationId: gen };
  }

  /** Cancel running operations in one scope. */
  cancel(scope: OperationScope): void {
    const gen = (this.scopeGenerations.get(scope) ?? 0) + 1;
    this.scopeGenerations.set(scope, gen);

    for (const op of this.operations.values()) {
      if (op.scope === scope && op.status === "running") {
        op.status = "cancelling";
        try {
          op.controller.abort();
        } catch {
          // controller already aborted
        }
      }
    }
  }

  /** Cancel all running operations, used by workspace/session transitions. */
  cancelAll(): void {
    for (const scope of this.scopeGenerations.keys()) {
      this.cancel(scope);
    }
  }

  /** Return true only while the operation is the current running operation. */
  isCurrent(operationId: string, generationId: number): boolean {
    const op = this.operations.get(operationId);
    if (!op) return false;
    return op.generationId === generationId && op.status === "running";
  }

  /** Return the latest generation for a scope. */
  getGeneration(scope: OperationScope): number {
    return this.scopeGenerations.get(scope) ?? 0;
  }

  /** Return the active operation for a scope. */
  getActive(scope: OperationScope): OperationState | null {
    for (const op of this.operations.values()) {
      if (op.scope === scope && op.status === "running") {
        return op;
      }
    }
    return null;
  }

  /** Mark an operation as completed. */
  complete(operationId: string): void {
    const op = this.operations.get(operationId);
    if (op) {
      op.status = "completed";
    }
  }

  /** Return true if a scope has a running operation. */
  isRunning(scope: OperationScope): boolean {
    for (const op of this.operations.values()) {
      if (op.scope === scope && op.status === "running") {
        return true;
      }
    }
    return false;
  }

  /** Return all scopes with running operations. */
  getActiveScopes(): OperationScope[] {
    const scopes = new Set<OperationScope>();
    for (const op of this.operations.values()) {
      if (op.status === "running") {
        scopes.add(op.scope);
      }
    }
    return Array.from(scopes);
  }
}

/** Shared singleton used by feature controllers and App.tsx. */
export const operationRegistry = new OperationRegistry();
