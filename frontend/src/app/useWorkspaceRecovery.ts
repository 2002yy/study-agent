import { useCallback, useEffect, useMemo, useRef } from "react";

import type { FireflyLessonState } from "../features/learning/defaultFireflyLesson";
import type { ApiSnapshot } from "../types";
import type { EvidenceRecoveryPort } from "./useEvidenceRuntime";
import type { ExtensionRecoveryPort } from "./useExtensionRuntime";
import type { LearningRecoveryPort } from "./useLearningSessionRuntime";
import {
  useWorkspacePersistence,
  type WorkspaceRecovery,
} from "./WorkspacePersistence";

type FireflyWorkspaceRecovery = WorkspaceRecovery & {
  fireflyLessonState?: FireflyLessonState;
};

export function useWorkspaceRecovery(options: {
  snapshot: ApiSnapshot;
  evidence: EvidenceRecoveryPort;
  learning: LearningRecoveryPort;
  extension: ExtensionRecoveryPort;
}) {
  const runtimeHydratedRef = useRef(false);
  const sessionSettingsRestoredRef = useRef(false);
  const { evidence, learning, extension } = options;

  const restoreWorkspace = useCallback(
    (parsed: WorkspaceRecovery | null) => {
      if (!parsed) {
        extension.restore(null);
        learning.restore(null);
        return;
      }
      extension.restore(parsed);
      const recovery = parsed as FireflyWorkspaceRecovery;
      if (
        learning.restore({
          singleChatSessionId: recovery.singleChatSessionId,
          sessionId: recovery.sessionId,
          memoryRunId: recovery.memoryRunId,
          learningClosureRunId: recovery.learningClosureRunId,
          chatSettings: recovery.chatSettings,
          keepCurrentRole: recovery.keepCurrentRole,
          conversationInstruction: recovery.conversationInstruction,
          fireflyLessonState: recovery.fireflyLessonState,
          lastRoute: recovery.lastRoute,
          lastRag: recovery.lastRag,
          lastSessionId: recovery.lastSessionId,
          cachedMessages: recovery.cachedMessages,
        })
      ) {
        sessionSettingsRestoredRef.current = true;
      }
      if (
        evidence.restore({
          ragQueryRunId: recovery.ragQueryRunId,
          ragWriteRunId: recovery.ragWriteRunId,
          webLookupRunId: recovery.webLookupRunId,
          ragSettings: recovery.ragSettings,
          ragEnabled: recovery.ragEnabled,
        })
      ) {
        sessionSettingsRestoredRef.current = true;
      }
    },
    [extension.restore, evidence.restore, learning.restore],
  );

  useEffect(() => {
    const settings = options.snapshot.runtimeSettings?.settings;
    if (!settings || runtimeHydratedRef.current) return;
    runtimeHydratedRef.current = true;
    if (sessionSettingsRestoredRef.current) return;
    learning.hydrateRuntimeSettings(settings);
    evidence.hydrateRuntimeSettings(settings);
  }, [
    options.snapshot.runtimeSettings,
    evidence.hydrateRuntimeSettings,
    learning.hydrateRuntimeSettings,
  ]);

  const persistenceState = useMemo(
    () => ({
      ...extension.state,
      ...learning.state,
      ...evidence.state,
    }),
    [extension.state, learning.state, evidence.state],
  );
  useWorkspacePersistence({ state: persistenceState, onRestore: restoreWorkspace });
}
