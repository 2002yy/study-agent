import type {
  ApiSnapshot,
  HealthResponse,
  MemoryStatusResponse,
  RagStatusResponse,
  RuntimeSettingsResponse,
  SessionRow,
  ToolSpec,
  WechatStateResponse,
  WorkflowRunSummary,
} from "../types";
import { authHeaders } from "../apiToken";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

export type WorkspaceFeature = "rag" | "tools" | "workflows" | "memory" | "wechat";

export type CoreSnapshotPatch = Pick<
  ApiSnapshot,
  "health" | "sessions" | "runtimeSettings" | "error" | "errors"
>;

let lastCore: CoreSnapshotPatch | null = null;
let coreGeneration = 0;

async function requestJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
    },
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`${response.status} ${response.statusText}${body ? `: ${body}` : ""}`);
  }
  return (await response.json()) as T;
}

function errorMessage(reason: unknown): string {
  return reason instanceof Error ? reason.message : String(reason);
}

export async function loadCoreWorkspaceSnapshot(): Promise<CoreSnapshotPatch> {
  const generation = ++coreGeneration;
  const results = await Promise.allSettled([
    requestJson<HealthResponse>("/health"),
    requestJson<{ sessions: SessionRow[] }>("/sessions"),
    requestJson<RuntimeSettingsResponse>("/runtime/settings"),
  ]);
  const errors: Record<string, string> = {};
  const read = <T>(index: number, key: string): T | null => {
    const result = results[index];
    if (result.status === "fulfilled") return result.value as T;
    errors[key] = errorMessage(result.reason);
    return null;
  };

  const health = read<HealthResponse>(0, "health");
  const sessions = read<{ sessions: SessionRow[] }>(1, "sessions");
  const runtimeSettings = read<RuntimeSettingsResponse>(2, "settings");

  if (generation !== coreGeneration) {
    return lastCore ?? {
      health: null,
      sessions: [],
      runtimeSettings: null,
      error: "core snapshot refresh superseded",
      errors: {},
    };
  }

  const next: CoreSnapshotPatch = {
    health: health ?? lastCore?.health ?? null,
    sessions: sessions?.sessions ?? lastCore?.sessions ?? [],
    runtimeSettings: runtimeSettings ?? lastCore?.runtimeSettings ?? null,
    error: errors.health ?? "",
    errors,
  };
  lastCore = next;
  return next;
}

export async function loadWorkspaceFeature(
  feature: WorkspaceFeature,
  options: { groupThreadId?: string } = {},
): Promise<Partial<ApiSnapshot>> {
  if (feature === "rag") {
    return { ragStatus: await requestJson<RagStatusResponse>("/rag/status") };
  }
  if (feature === "tools") {
    const response = await requestJson<{ tools: ToolSpec[] }>("/tools");
    return { tools: response.tools };
  }
  if (feature === "workflows") {
    const response = await requestJson<{ runs: WorkflowRunSummary[] }>("/workflows/runs");
    return { workflowRuns: response.runs };
  }
  if (feature === "memory") {
    return { memoryStatus: await requestJson<MemoryStatusResponse>("/memory") };
  }
  const suffix = options.groupThreadId
    ? `?group_thread_id=${encodeURIComponent(options.groupThreadId)}`
    : "";
  return { wechat: await requestJson<WechatStateResponse>(`/wechat${suffix}`) };
}
