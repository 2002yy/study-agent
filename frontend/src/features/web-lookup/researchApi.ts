import type { NewsLookupResponse } from "../../types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";
const API_TOKEN = import.meta.env.VITE_STUDY_AGENT_API_TOKEN ?? "";

export type ResearchRunStatus = "pending" | "running" | "completed" | "empty" | "failed";
export type ResearchRunStage = "planned" | "searching" | "completed" | "empty" | "failed";

export type ResearchLookupResponse = NewsLookupResponse & {
  status: ResearchRunStatus;
  stage: ResearchRunStage;
  query_plan: Record<string, unknown>;
  attempts: Array<Record<string, unknown>>;
  empty_reason: string;
  error: string;
  max_items: number;
  active_operation_id?: string | null;
  active_operation_started_at?: string | null;
  stage_started_at?: string | null;
  version: number;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
};

type ResearchRunPayload = {
  id: string;
  query: string;
  stage: ResearchRunStage;
  status: ResearchRunStatus;
  query_plan: Record<string, unknown>;
  attempts: Array<Record<string, unknown>>;
  items: Array<Record<string, unknown>>;
  source_block: string;
  warnings: string[];
  empty_reason: string;
  error: string;
  max_items: number;
  active_operation_id?: string | null;
  active_operation_started_at?: string | null;
  stage_started_at?: string | null;
  version: number;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
};

function authHeaders(): HeadersInit {
  return API_TOKEN ? { "X-Study-Agent-Token": API_TOKEN } : {};
}

async function requestJson<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
      ...(options?.headers ?? {}),
    },
    ...options,
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`${response.status} ${response.statusText}${body ? `: ${body}` : ""}`);
  }
  return (await response.json()) as T;
}

function toResponse(run: ResearchRunPayload): ResearchLookupResponse {
  return {
    run_id: run.id,
    query_text: run.query,
    news_items: run.items,
    source_block: run.source_block,
    warnings: run.warnings,
    status: run.status,
    stage: run.stage,
    query_plan: run.query_plan,
    attempts: run.attempts,
    empty_reason: run.empty_reason,
    error: run.error,
    max_items: run.max_items,
    active_operation_id: run.active_operation_id,
    active_operation_started_at: run.active_operation_started_at,
    stage_started_at: run.stage_started_at,
    version: run.version,
    created_at: run.created_at,
    updated_at: run.updated_at,
    completed_at: run.completed_at,
  };
}

export async function createResearchRun(
  query: string,
  maxItems = 8,
  requestOptions: { signal?: AbortSignal } = {},
): Promise<ResearchLookupResponse> {
  const run = await requestJson<ResearchRunPayload>("/research-runs", {
    method: "POST",
    signal: requestOptions.signal,
    body: JSON.stringify({ query, max_items: maxItems }),
  });
  return toResponse(run);
}

export async function searchResearchRun(
  runId: string,
  requestOptions: { signal?: AbortSignal } = {},
): Promise<ResearchLookupResponse> {
  const run = await requestJson<ResearchRunPayload>(
    `/research-runs/${encodeURIComponent(runId)}/search`,
    { method: "POST", signal: requestOptions.signal },
  );
  return toResponse(run);
}

export async function retryResearchRun(
  runId: string,
  requestOptions: { signal?: AbortSignal } = {},
): Promise<ResearchLookupResponse> {
  const run = await requestJson<ResearchRunPayload>(
    `/research-runs/${encodeURIComponent(runId)}/retry`,
    { method: "POST", signal: requestOptions.signal },
  );
  return toResponse(run);
}

export async function loadResearchRun(runId: string): Promise<ResearchLookupResponse> {
  const run = await requestJson<ResearchRunPayload>(
    `/research-runs/${encodeURIComponent(runId)}`,
  );
  return toResponse(run);
}
