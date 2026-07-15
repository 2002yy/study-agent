export type SessionSummaryStatus =
  | "not_summarized"
  | "summarized"
  | "needs_update";

export type SessionSummary = {
  thread_id: string;
  status: SessionSummaryStatus;
  source_thread_version?: number | null;
  last_completed_turn_id?: string | null;
  current_last_completed_turn_id?: string | null;
  closure_run_id?: string | null;
  summarized_at?: string | null;
  updated_at?: string;
  version?: number;
  can_summarize: boolean;
};

export function emptySessionSummary(threadId = ""): SessionSummary {
  return {
    thread_id: threadId,
    status: "not_summarized",
    source_thread_version: null,
    last_completed_turn_id: null,
    current_last_completed_turn_id: null,
    closure_run_id: null,
    summarized_at: null,
    can_summarize: false,
  };
}
