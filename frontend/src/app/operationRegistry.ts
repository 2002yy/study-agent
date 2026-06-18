/**
 * 统一异步操作注册器 — 替代分散的 generation refs 和 AbortController refs。
 *
 * 规则：
 *  - start(scope) 自动取消同 scope 旧操作
 *  - 不同 scope 互不影响
 *  - cancelAll() 只在 Workspace 切换时调用
 *  - 每个回调通过 isCurrent(id, genId) 检查是否被取代
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

class OperationRegistry {
  private operations = new Map<string, OperationState>();
  private scopeGenerations = new Map<OperationScope, number>();

  /** 启动新操作，自动 cancel 同 scope 旧操作 */
  start(scope: OperationScope, ownerId?: string): {
    operationId: string;
    controller: AbortController;
    generationId: number;
  } {
    // 取消同 scope 旧操作
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

  /** 取消指定 scope 的所有运行中操作 */
  cancel(scope: OperationScope): void {
    // 递增 generation 使旧回调无效
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

  /** 取消所有 scope 的所有操作（Workspace 切换时使用） */
  cancelAll(): void {
    for (const scope of this.scopeGenerations.keys()) {
      this.cancel(scope);
    }
  }

  /** 检查 operation 是否仍是最新的 */
  isCurrent(operationId: string, generationId: number): boolean {
    const op = this.operations.get(operationId);
    if (!op) return false;
    return op.generationId === generationId && op.status === "running";
  }

  /** 获取指定 scope 的当前 generation */
  getGeneration(scope: OperationScope): number {
    return this.scopeGenerations.get(scope) ?? 0;
  }

  /** 获取 scope 的活跃操作 */
  getActive(scope: OperationScope): OperationState | null {
    for (const op of this.operations.values()) {
      if (op.scope === scope && op.status === "running") {
        return op;
      }
    }
    return null;
  }

  /** 标记操作完成 */
  complete(operationId: string): void {
    const op = this.operations.get(operationId);
    if (op) {
      op.status = "completed";
    }
  }

  /** 检查 scope 是否有运行中的操作 */
  isRunning(scope: OperationScope): boolean {
    for (const op of this.operations.values()) {
      if (op.scope === scope && op.status === "running") {
        return true;
      }
    }
    return false;
  }

  /** 获取所有活跃的 scope */
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

/** 全局单例 */
export const operationRegistry = new OperationRegistry();
