import { useCallback, useEffect, useState } from "react";

import { loadApiSnapshot } from "../api";
import type { ApiSnapshot } from "../types";
import { serverQueryCache } from "./serverQueryCache";

const EMPTY_SNAPSHOT: ApiSnapshot = {
  health: null,
  ragStatus: null,
  tools: [],
  workflowRuns: [],
  sessions: [],
  runtimeSettings: null,
  memoryStatus: null,
  wechat: null,
  error: "",
  errors: {},
};

export function useWorkspaceBootstrap() {
  const [snapshot, setSnapshot] = useState<ApiSnapshot>(EMPTY_SNAPSHOT);
  const refresh = useCallback(async () => {
    setSnapshot(
      await serverQueryCache.query("snapshot:main", loadApiSnapshot, 1_500)
    );
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { snapshot, setSnapshot, refresh };
}
