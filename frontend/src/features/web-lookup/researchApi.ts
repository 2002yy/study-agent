import type { NewsLookupResponse } from "../../types";
import { authHeaders } from "../../apiToken";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

export type ResearchRunStatus =
  | "pending"
  | "running"
  | "completed"
  | "partial"
  | "failed"
  | "cancelled";

export type ResearchRunStage =
  | "planned"
  | "searching"
  | "assessing"
  | "reading"
  | "synthesizing"
  | "completed"
  | "failed"
  | "cancelled";

export type ResearchLookupResponse = NewsLookupResponse & {
  status: ResearchRunStatus;
  stage: ResearchRunStage;
  research_context: Record<string, unknown>;
  query_attempts: Array<Record<string, unknown>>;
  selected_sources: Array<Record<string, unknown>>;
  rejected_sources: Array<Record<string, unknown>>;
  provider_status: string;
  stop_reason: string;
  answer_confidence: string;
  error: string;
  max_items: number;
  active_operation_id?: string | null;
  active_operation_started_at?: string | null;
  stage_started_at?: string | null;
  cancel_requested_at?: string | null;
  owner_thread_id?: string | null;
  parent_run_id?: string | null;
  root_run_id?: string | null;
  lineage_depth?: number;
  create_request_id?: string | null;
  lineage_summary?: Record<string, number>;
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
  research_context: Record<string, unknown>;
  query_attempts: Array<Record<string, unknown>>;
  selected_sources: Array<Record<string, unknown>>;
  rejected_sources: Array<Record<string, unknown>>;
  provider_status: string;
  stop_reason: string;
  answer_confidence: string;
  items: Array<Record<string, unknown>>;
  source_block: string;
  warnings: string[];
  error: string;
  max_items: number;
  active_operation_id?: string | null;
  active_operation_started_at?: string | null;
  stage_started_at?: string | null;
  cancel_requested_at?: string | null;
  owner_thread_id?: string | null;
  parent_run_id?: string | null;
  root_run_id?: string | null;
  lineage_depth?: number;
  create_request_id?: string | null;
  lineage_summary?: Record<string, number>;
  version: number;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
};

type ResearchRequestOptions = {
  signal?: AbortSignal;
  ownerThreadId?: string;
  parentRunId?: string;
  createRequestId?: string;
  suggestionStatus?: "not_checked" | "not_found" | "accepted" | "declined" | "unavailable";
};

export type ResearchFollowUpCandidate = {
  available: boolean;
  reason: string;
  parent_run_id?: string | null;
  parent_query: string;
  parent_status: string;
  source_count: number;
  note_count: number;
  overlap_tokens: string[];
  requires_explicit_confirmation: boolean;
  steering_required: boolean;
};

type ResearchCancelOptions = ResearchRequestOptions & {
  pollIntervalMs?: number;
  timeoutMs?: number;
};

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
    research_context: run.research_context,
    query_attempts: run.query_attempts,
    selected_sources: run.selected_sources,
    rejected_sources: run.rejected_sources,
    provider_status: run.provider_status,
    stop_reason: run.stop_reason,
    answer_confidence: run.answer_confidence,
    error: run.error,
    max_items: run.max_items,
    active_operation_id: run.active_operation_id,
    active_operation_started_at: run.active_operation_started_at,
    stage_started_at: run.stage_started_at,
    cancel_requested_at: run.cancel_requested_at,
    owner_thread_id: run.owner_thread_id,
    parent_run_id: run.parent_run_id,
    root_run_id: run.root_run_id,
    lineage_depth: run.lineage_depth,
    create_request_id: run.create_request_id,
    lineage_summary: run.lineage_summary,
    version: run.version,
    created_at: run.created_at,
    updated_at: run.updated_at,
    completed_at: run.completed_at,
  };
}

function abortError(): DOMException {
  return new DOMException("The operation was aborted", "AbortError");
}

function wait(milliseconds: number, signal?: AbortSignal): Promise<void> {
  if (signal?.aborted) return Promise.reject(abortError());
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, Math.max(0, milliseconds));
    const onAbort = () => {
      window.clearTimeout(timer);
      signal?.removeEventListener("abort", onAbort);
      reject(abortError());
    };
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

export async function createResearchRun(
  query: string,
  maxItems = 8,
  requestOptions: ResearchRequestOptions = {},
): Promise<ResearchLookupResponse> {
  const run = await requestJson<ResearchRunPayload>("/research-runs", {
    method: "POST",
    signal: requestOptions.signal,
    body: JSON.stringify({
      query,
      max_items: maxItems,
      owner_thread_id: requestOptions.ownerThreadId,
      parent_run_id: requestOptions.parentRunId,
      create_request_id: requestOptions.createRequestId,
      suggestion_status: requestOptions.suggestionStatus ?? "not_checked",
    }),
  });
  return toResponse(run);
}

export async function loadResearchFollowUpCandidate(
  threadId: string,
  query: string,
  requestOptions: ResearchRequestOptions = {},
): Promise<ResearchFollowUpCandidate> {
  return requestJson<ResearchFollowUpCandidate>(
    `/sessions/${encodeURIComponent(threadId)}/research-runs/follow-up-candidate?query=${encodeURIComponent(query)}`,
    { signal: requestOptions.signal },
  );
}

export async function steerResearchRun(
  runId: string,
  content: string,
  requestOptions: ResearchRequestOptions = {},
): Promise<ResearchLookupResponse> {
  const run = await requestJson<ResearchRunPayload>(
    `/research-runs/${encodeURIComponent(runId)}/steer`,
    {
      method: "POST",
      signal: requestOptions.signal,
      body: JSON.stringify({ content }),
    },
  );
  return toResponse(run);
}

export async function executeResearchRun(
  runId: string,
  requestOptions: ResearchRequestOptions = {},
): Promise<ResearchLookupResponse> {
  const run = await requestJson<ResearchRunPayload>(
    `/research-runs/${encodeURIComponent(runId)}/search`,
    { method: "POST", signal: requestOptions.signal },
  );
  return toResponse(run);
}

export async function retryResearchRun(
  runId: string,
  requestOptions: ResearchRequestOptions = {},
): Promise<ResearchLookupResponse> {
  const run = await requestJson<ResearchRunPayload>(
    `/research-runs/${encodeURIComponent(runId)}/retry`,
    { method: "POST", signal: requestOptions.signal },
  );
  return toResponse(run);
}

export async function resumeResearchRun(
  runId: string,
  requestOptions: ResearchRequestOptions = {},
): Promise<ResearchLookupResponse> {
  const run = await requestJson<ResearchRunPayload>(
    `/research-runs/${encodeURIComponent(runId)}/resume`,
    { method: "POST", signal: requestOptions.signal },
  );
  return toResponse(run);
}

export async function loadResearchRun(
  runId: string,
  requestOptions: ResearchRequestOptions = {},
): Promise<ResearchLookupResponse> {
  const run = await requestJson<ResearchRunPayload>(
    `/research-runs/${encodeURIComponent(runId)}`,
    { signal: requestOptions.signal },
  );
  return toResponse(run);
}

export async function cancelResearchRun(
  runId: string,
  requestOptions: ResearchCancelOptions = {},
): Promise<ResearchLookupResponse> {
  let current = toResponse(
    await requestJson<ResearchRunPayload>(
      `/research-runs/${encodeURIComponent(runId)}/cancel`,
      { method: "POST", signal: requestOptions.signal },
    ),
  );
  if (current.status !== "running") return current;

  const pollIntervalMs = Math.max(0, requestOptions.pollIntervalMs ?? 100);
  const timeoutMs = Math.max(0, requestOptions.timeoutMs ?? 5000);
  const deadline = Date.now() + timeoutMs;

  while (current.status === "running") {
    if (Date.now() >= deadline) {
      throw new Error(
        `联网研究停止请求仍在处理中（${current.stage}）；刷新后可继续查看或重试。`,
      );
    }
    await wait(pollIntervalMs, requestOptions.signal);
    current = await loadResearchRun(runId, { signal: requestOptions.signal });
  }
  return current;
}
