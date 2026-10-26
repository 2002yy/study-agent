import type { LearningClosureRunResponse } from "./closureTypes";
import { authHeaders } from "../../apiToken";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

async function requestClosure(
  path: string,
  options: RequestInit = {}
): Promise<LearningClosureRunResponse> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
      ...(options.headers ?? {}),
    },
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`${response.status} ${response.statusText}${body ? `: ${body}` : ""}`);
  }
  return (await response.json()) as LearningClosureRunResponse;
}

export async function createLearningClosure(
  sessionId: string
): Promise<LearningClosureRunResponse> {
  return requestClosure(
    `/sessions/${encodeURIComponent(sessionId)}/learning-closure-runs`,
    { method: "POST" }
  );
}

export async function loadLearningClosure(
  runId: string
): Promise<LearningClosureRunResponse> {
  return requestClosure(`/learning-closure-runs/${encodeURIComponent(runId)}`);
}

export async function retryLearningClosure(
  runId: string
): Promise<LearningClosureRunResponse> {
  return requestClosure(`/learning-closure-runs/${encodeURIComponent(runId)}/retry`, {
    method: "POST",
  });
}

export async function cancelLearningClosure(
  runId: string
): Promise<LearningClosureRunResponse> {
  return requestClosure(`/learning-closure-runs/${encodeURIComponent(runId)}/cancel`, {
    method: "POST",
  });
}

export async function commitLearningClosure(
  runId: string
): Promise<LearningClosureRunResponse> {
  return requestClosure(`/learning-closure-runs/${encodeURIComponent(runId)}/commit`, {
    method: "POST",
  });
}
