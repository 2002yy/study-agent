import { useState } from "react";

import { loadWorkflowRun } from "../../api";
import { serverQueryCache } from "../../app/serverQueryCache";
import type { WorkflowRunDetail } from "../../types";

export function useWorkflowController() {
  const [selectedRun, setSelectedRun] = useState<WorkflowRunDetail | null>(null);
  const [loadingRunId, setLoadingRunId] = useState("");
  const selectRun = async (runId: string) => {
    setLoadingRunId(runId);
    try {
      setSelectedRun(
        await serverQueryCache.query(
          `workflow:${runId}`,
          () => loadWorkflowRun(runId),
          15_000
        )
      );
    } finally {
      setLoadingRunId("");
    }
  };
  const clear = () => setSelectedRun(null);
  return { selectedRun, loadingRunId, selectRun, clear };
}
