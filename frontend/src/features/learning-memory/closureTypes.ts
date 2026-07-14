import type { MemoryRunResponse } from "../../types";

export type LearningClosureStatus =
  | "created"
  | "collecting"
  | "generating"
  | "preview_ready"
  | "committing"
  | "completed"
  | "failed"
  | "cancelled";

export type LearningClosureRunResponse = {
  id: string;
  thread_id: string;
  source_thread_version: number;
  last_completed_turn_id: string;
  source_hash: string;
  closure_eligibility: "learning_summary" | "project_summary" | string;
  status: LearningClosureStatus;
  committed_snapshot: Record<string, unknown>;
  generated_result: Record<string, unknown>;
  memory_run_id?: string | null;
  memory_run?: MemoryRunResponse | null;
  error: string;
  reason: string;
  active_operation_id?: string | null;
  active_operation_started_at?: string | null;
  cancel_requested_at?: string | null;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
  version: number;
};
