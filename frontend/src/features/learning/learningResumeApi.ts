import { authHeaders } from "../../apiToken";

export type LearningResumeEvidence = {
  evidence_id?: string;
  role?: string;
  repository?: string;
  commit_sha?: string;
  tree_sha?: string;
  path?: string;
  file_sha?: string;
  symbol?: string | null;
  symbol_kind?: string | null;
  start_line?: number | null;
  end_line?: number | null;
  evidence_kind?: string;
};

export type FreshnessDetail = {
  role?: string;
  path?: string;
  symbol?: string | null;
  reason?: string;
  head_file_sha?: string;
  materially_changed?: boolean;
  error?: string;
};

export type ClaimFreshness = {
  status: "current" | "stale_candidate" | "unavailable" | string;
  head_commit?: string;
  reason?: string;
  primary?: FreshnessDetail;
  supporting_drift?: FreshnessDetail[];
  unavailable_reason?: string;
};

export type LearningResumeClaim = {
  claim_id: string;
  revision_id: string;
  text: string;
  claim_kind: string;
  scope: string;
  understanding_status: "proposed" | "attempted" | "partial" | "confirmed";
  validation_result: "none" | "fail" | "partial" | "pass";
  latest_validation: {
    method?: string;
    result?: "fail" | "partial" | "pass";
    verified_at?: string;
  };
  primary_evidence: LearningResumeEvidence;
  supporting_evidence: LearningResumeEvidence[];
  freshness?: ClaimFreshness;
};

export type LearningResumeResponse = {
  source: "durable" | "legacy_fallback";
  status: "active" | "no_active_goal" | "legacy" | "empty" | string;
  topic: {
    topic_id?: string;
    title?: string;
    scope?: string;
  };
  goal: {
    goal_id?: string;
    topic_id?: string;
    objective?: string;
    status?: string;
  };
  claims: LearningResumeClaim[];
  claim_count: number;
  unresolved: Array<{
    hypothesis_id?: string;
    text: string;
    reason?: string;
  }>;
  next_step: {
    next_step_id?: string;
    text?: string;
    status?: string;
    is_primary?: boolean;
  };
  optional_next_steps: Array<{
    next_step_id?: string;
    text?: string;
    status?: string;
    is_primary?: boolean;
  }>;
  legacy_confirmed_points?: string[];
};

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

export async function getLearningResume(
  sessionId: string,
  signal?: AbortSignal,
): Promise<LearningResumeResponse> {
  const response = await fetch(
    `${API_BASE_URL}/sessions/${encodeURIComponent(sessionId)}/learning-resume`,
    {
      signal,
      headers: authHeaders(),
    },
  );
  if (!response.ok) {
    const body = await response.text();
    throw new Error(
      `${response.status} ${response.statusText}${body ? `: ${body}` : ""}`,
    );
  }
  return (await response.json()) as LearningResumeResponse;
}

export type RevalidationResult = {
  claim_id: string;
  outcome: string;
  revision_id?: string;
  unresolved_reason?: string;
  head_commit?: string;
  freshness_status?: string;
};

export async function revalidateClaim(
  sessionId: string,
  claimId: string,
  signal?: AbortSignal,
): Promise<RevalidationResult> {
  const response = await fetch(
    `${API_BASE_URL}/sessions/${encodeURIComponent(sessionId)}/claims/${encodeURIComponent(claimId)}/revalidate`,
    {
      method: "POST",
      signal,
      headers: authHeaders(),
    },
  );
  if (!response.ok) {
    const body = await response.text();
    throw new Error(
      `${response.status} ${response.statusText}${body ? `: ${body}` : ""}`,
    );
  }
  return (await response.json()) as RevalidationResult;
}
